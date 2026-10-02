"""
sage-birdnet2 — BirdNET V2.4 audio species classifier, v2 cache-consumer architecture.

Reads self-describing `-v2-` AUDIO frames that media-sampler3 (the audio producer)
wrote to the shared on-node `/local-cache`, runs BirdNET V2.4 inference on each
15-second FLAC clip, and publishes per-species detections frame-anchored (observation
time = clip capture time, NOT wall-clock).

THE SWITCH: like sage-bioclip2, the cache dir is a single `--input` parameter, so the
same plugin consumes any v2 audio stream with no code change:
  --source cache --input /local-cache/camera-audio/mic

Architecture mirrors sage-bioclip2 / sage-yolo2: the cache-consumer machinery
(consumer / selection / seenstore / node_info) is vendored from sage-yolo2 — see
VENDORED.md. consumer.py carries ONE documented divergence: an audio JSON-sidecar
metadata reader (image frames use EXIF; audio frames use `<clip>.flac.json`). This
file is the birdnet-specific brains: the BirdNETClassifier + eBird geo/season filter
+ the soundscape-ecology publish routing, ported from the v1 BirdNET plugin onto the
v2 wake loop.

Secondary dev/offline sources are kept: --source file (a local audio file) and
--source camera (ffmpeg capture) — these mirror the v1 plugin's non-cache paths.

Measurement topics (routed by soundscape-ecology category):
  env.detection.biophony.<scientific_name>    — living organisms (birds/frogs/insects)
  env.detection.anthrophony.<name>            — human-made (engine, siren, dog…)
  env.detection.geophony.<name>               — abiotic ambient (noise, environmental)
  env.detection.audio.summary                 — JSON summary / per-frame heartbeat
  upload                                       — FLAC clip (when --save-match matches)
"""
import argparse
import json
import logging
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime

from waggle.plugin import Plugin

from save_match import parse_save_match, should_save, SaveMatchError
import consumer
import selection
import seenstore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("sage-birdnet2")


# ── classifier (grafted from v1 BirdNET plugin, essentially intact) ───────────
class BirdNETClassifier:
    """Wraps the birdnet library for Sage plugin use.

    Heavy model construction + geo-filter build are deferred to load() so they can be
    timed inside the Plugin context (plugin.duration.loadmodel). birdnet is imported
    lazily in load() so the module (and offline tests) import without the model stack.
    """

    def __init__(
        self,
        min_confidence: float = 0.6,
        sensitivity: float = 1.0,
        overlap: float = 0.0,
        top_k: int = 5,
        lat: float = -1.0,
        lon: float = -1.0,
        week: int = -1,
        sf_thresh: float = 0.03,
        bandpass_fmin: int = 0,
        bandpass_fmax: int = 8000,
        batch_size: int = 1,
    ):
        self.min_confidence = min_confidence
        self.sensitivity = sensitivity
        self.overlap = overlap
        self.top_k = top_k
        self.lat = lat
        self.lon = lon
        self.week = week
        self.sf_thresh = sf_thresh
        self.bandpass_fmin = bandpass_fmin
        self.bandpass_fmax = bandpass_fmax
        self.batch_size = batch_size
        self.model = None
        self.species_filter = None

    def load(self):
        """Load the acoustic model and (if coordinates are set) build the geo
        species filter."""
        import birdnet

        lat, lon, week = self.lat, self.lon, self.week
        logger.info("Loading BirdNET V2.4 acoustic model...")
        self.model = birdnet.load("acoustic", "2.4", "tf")
        logger.info(
            "Acoustic model loaded (sample rate: %d Hz)",
            self.model.get_sample_rate(),
        )

        # Build species filter from geo model if coordinates are set.
        # NOTE: -1/-1 is the "unset" sentinel. We must NOT use `lon > -1` as the
        # "is set" test — real Western-Hemisphere longitudes are negative (e.g.
        # H00F is -87.98), so `lon > -1` is False for all of the Americas and the
        # geo filter would silently never build. Test against the sentinel + ranges.
        coords_set = not (lat == -1 and lon == -1)
        coords_valid = -90 <= lat <= 90 and -180 <= lon <= 180
        if coords_set and coords_valid:
            logger.info(
                "Loading geo model for species filtering (%.4f, %.4f, week=%s)...",
                lat, lon, week if week > 0 else "all",
            )
            geo = birdnet.load("geo", "2.4", "tf")
            geo_week = week if 1 <= week <= 48 else None
            species_result = geo.predict(
                lat, lon, week=geo_week, min_confidence=self.sf_thresh,
            )
            self.species_filter = species_result.to_set()
            logger.info(
                "Geo filter: %d species expected at this location/time",
                len(self.species_filter),
            )

    def classify_file(self, audio_path: str) -> list[dict]:
        """Classify an audio file. Returns list of detection dicts."""
        predictions = self.model.predict(
            audio_path,
            top_k=self.top_k,
            overlap_duration_s=self.overlap,
            apply_sigmoid=True,
            sigmoid_sensitivity=self.sensitivity,
            default_confidence_threshold=self.min_confidence,
            custom_species_list=self.species_filter,
            bandpass_fmin=self.bandpass_fmin,
            bandpass_fmax=self.bandpass_fmax,
            batch_size=self.batch_size,
        )

        df = predictions.to_dataframe()
        if df.empty:
            return []

        detections = []
        for _, row in df.iterrows():
            species_name = row["species_name"]
            parts = species_name.split("_", 1)
            scientific = parts[0] if len(parts) > 0 else species_name
            common = parts[1] if len(parts) > 1 else ""

            detections.append({
                "scientific_name": scientific,
                "common_name": common,
                "confidence": float(row["confidence"]),
                "start_time": float(row["start_time"]),
                "end_time": float(row["end_time"]),
            })

        return detections


# ── audio sources (dev/offline modes, from v1) ───────────────────────────────
def record_from_microphone(duration_s: float, sample_rate: int = 48000) -> str:
    """Record audio from the node's USB microphone via pywaggle (dev mode).

    Saved as FLAC (lossless): smaller than WAV, no quality loss for BirdNET, and the
    Sage portal inlines .flac.
    """
    from waggle.data.audio import Microphone

    mic = Microphone(samplerate=sample_rate)
    logger.info("Recording %g seconds from USB microphone at %d Hz...", duration_s, sample_rate)
    sample = mic.record(duration_s)

    tmpdir = tempfile.mkdtemp(prefix="birdnet_")
    flac_path = os.path.join(tmpdir, "recording.flac")
    sample.save(flac_path)
    logger.info("Audio saved to %s (FLAC)", flac_path)
    return flac_path


def record_from_camera(url: str, duration_s: float, sample_rate: int = 48000) -> str:
    """Capture audio from a network camera via ffmpeg (dev mode).

    Captures to FLAC (lossless): same fidelity as WAV for BirdNET, ~50-70% smaller,
    and the Sage portal inlines an <audio> player only for .flac uploads. Supports any
    ffmpeg-compatible source (Mobotix MxPEG, RTSP, HTTP streams).
    """
    tmpdir = tempfile.mkdtemp(prefix="birdnet_")
    flac_path = os.path.join(tmpdir, "camera_audio.flac")

    input_args = []
    if "faststream" in url and "MxPEG" in url:
        input_args = ["-f", "mxg"]
    elif url.startswith("rtsp://"):
        input_args = ["-rtsp_transport", "tcp"]

    cmd = (
        ["ffmpeg", "-y"]
        + input_args
        + ["-i", url,
           "-vn",                     # no video
           "-acodec", "flac",         # lossless FLAC (portal inlines .flac)
           "-ar", str(sample_rate),   # resample to target rate
           "-ac", "1",               # mono
           "-t", str(duration_s),
           flac_path]
    )

    safe_url = url.split("@")[-1] if "@" in url else url
    logger.info("Capturing %g seconds from camera %s...", duration_s, safe_url)

    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=int(duration_s) + 30,
    )
    if result.returncode != 0:
        logger.error("ffmpeg failed (exit %d): %s", result.returncode, result.stderr[-300:])
        raise RuntimeError(f"ffmpeg failed to capture audio from camera: {result.stderr[-200:]}")
    if not os.path.exists(flac_path) or os.path.getsize(flac_path) < 1000:
        raise RuntimeError("ffmpeg produced no audio output — check camera URL and credentials")

    logger.info("Camera audio saved to %s (%d bytes, FLAC)", flac_path, os.path.getsize(flac_path))
    return flac_path


# ── publishing (soundscape-ecology routing, from v1, intact) ─────────────────
# BirdNET V2.4's label set is NOT birds-only: alongside real taxa it carries a small,
# fixed set of human-made and abiotic "distractor" classes. We route detections to
# three standard soundscape-ecology topics so consumers can separate biological signal
# from anthropogenic/geophysical sound. Anything NOT listed is treated as biophony, so
# new species in future model releases default to the biological bucket automatically.
ANTHROPHONY_CLASSES = {
    "Engine", "Siren", "Gun", "Fireworks", "Power tools", "Dog",
    "Human vocal", "Human non-vocal", "Human whistle",
}
GEOPHONY_CLASSES = {"Noise", "Environmental"}


def sound_category(scientific_name: str) -> str:
    """Map a BirdNET class to 'anthrophony' / 'geophony' / 'biophony' (default)."""
    if scientific_name in ANTHROPHONY_CLASSES:
        return "anthrophony"
    if scientific_name in GEOPHONY_CLASSES:
        return "geophony"
    return "biophony"


def publish_detections(plugin, detections: list[dict], timestamp: int, *, base_meta=None):
    """Publish detections to Waggle, routed by soundscape-ecology category, FRAME-
    ANCHORED (timestamp = clip capture_ts_ns in cache mode, not wall-clock).

    Each detection publishes to env.detection.<category>.<name>. The summary topic is
    ALWAYS published — even with zero detections — so the data API carries a per-frame
    heartbeat that proves the job ran ("running fine, no birds" vs "job is dead").

    base_meta (cache mode) carries frame identity (vsn/node_id/lat/lon/camera) so every
    published detection is attributable to the node + clip it came from.
    """
    base_meta = dict(base_meta or {})

    for det in detections:
        category = sound_category(det["scientific_name"])
        topic_name = det["scientific_name"].lower().replace(" ", "_")
        meta = dict(base_meta)
        meta.update({
            "common_name": str(det["common_name"]),
            "category": category,
            # pywaggle requires meta values to be strings — stringify the floats.
            "start_time_s": str(det["start_time"]),
            "end_time_s": str(det["end_time"]),
        })
        plugin.publish(
            f"env.detection.{category}.{topic_name}",
            det["confidence"],
            timestamp=timestamp,
            meta=meta,
        )

    # Always publish a summary (heartbeat) with a per-category breakdown.
    species_best = {}
    cat_counts = {"biophony": 0, "anthrophony": 0, "geophony": 0}
    for det in detections:
        cat_counts[sound_category(det["scientific_name"])] += 1
        key = det["scientific_name"]
        if key not in species_best or det["confidence"] > species_best[key]["confidence"]:
            species_best[key] = det

    summary = {
        "total_detections": len(detections),
        "unique_species": len(species_best),
        "biophony": cat_counts["biophony"],
        "anthrophony": cat_counts["anthrophony"],
        "geophony": cat_counts["geophony"],
        "species": [
            {
                "scientific_name": d["scientific_name"],
                "common_name": d["common_name"],
                "confidence": round(d["confidence"], 4),
                "category": sound_category(d["scientific_name"]),
            }
            for d in sorted(species_best.values(), key=lambda x: x["confidence"], reverse=True)
        ],
    }
    plugin.publish(
        "env.detection.audio.summary",
        json.dumps(summary),
        timestamp=timestamp,
        meta=base_meta,
    )


def _log_detections(detections: list[dict]):
    for det in detections:
        logger.info(
            "  %s (%s): %.4f [%.1f-%.1fs]",
            det["scientific_name"], det["common_name"], det["confidence"],
            det["start_time"], det["end_time"],
        )


# ── location / season utilities ──────────────────────────────────────────────
def current_birdnet_week() -> int:
    """Current BirdNET week (1–48, 4 weeks per month). Jan 1 = 1, Dec 31 = 48."""
    now = datetime.now()
    week = (now.month - 1) * 4 + min(4, math.ceil(now.day / 7.5))
    return max(1, min(48, week))


def resolve_location(args, node_info):
    """Resolve (lat, lon) for eBird geo-filtering, in priority order:

      1. Explicit --lat/--lon on the CLI (override).
      2. The node's own identity (WAGGLE_NODE_GPS_* via node_info) — the fixed-node
         GPS, present when the pod is launched with pluginctl-nodeinfo or by the
         patched scheduler.
      3. Sentinel (-1, -1) — geo-filtering disabled (full global species list).

    The geo filter is a per-run construct, so a per-clip sidecar lat/lon is not used
    to build it. (The media-sampler3 producer does write the node's GPS into each
    sidecar when it has it; consumer.resolve_identity surfaces that per clip for the
    published records' lat/lon.)
    """
    if not (args.lat == -1 and args.lon == -1):
        logger.info("Location from --lat/--lon: (%.4f, %.4f)", args.lat, args.lon)
        return args.lat, args.lon
    if node_info is not None and node_info.lat is not None and node_info.lon is not None:
        logger.info("Location from node identity: (%.4f, %.4f)", node_info.lat, node_info.lon)
        return node_info.lat, node_info.lon
    logger.info("No node location (sidecar null, node GPS absent, no --lat/--lon) — "
                "geo-filtering disabled. Pass --lat/--lon to enable it explicitly.")
    return -1.0, -1.0


# ── consumer-id + cache-input parsing (from sage-bioclip2 / sage-yolo2) ───────
def resolve_consumer_id(override):
    if override:
        return override
    job = os.environ.get("WAGGLE_JOB_NAME", "").strip()
    task = os.environ.get("WAGGLE_TASK_NAME", "").strip()
    if job and task:
        return "%s-%s" % (job, task)
    app_id = os.environ.get("WAGGLE_APP_ID", "").strip()
    if app_id:
        logger.warning("no WAGGLE_JOB_NAME/TASK_NAME; using WAGGLE_APP_ID as consumer-id")
        return app_id
    logger.warning("no consumer identity in env; using 'default' consumer-id")
    return "default"


def parse_cache_input(input_path, cache_root):
    """Split <root>/<cache-name>/<source> → (cache_name, source)."""
    rel = os.path.relpath(os.path.abspath(input_path), os.path.abspath(cache_root))
    parts = [p for p in rel.split(os.sep) if p and p != "."]
    if len(parts) >= 2:
        return parts[0], parts[-1]
    return (parts[0] if parts else "cache"), os.path.basename(input_path.rstrip("/"))


# ── CLI ──────────────────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="BirdNET V2.4 audio species classifier — v2 cache consumer.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  # Production: consume 15s FLAC clips from the shared cache
  python3 app.py --source cache \\
      --input /local-cache/camera-audio/mic \\
      --every 10m --all-unseen --min-confidence 0.6

  # Local dev: classify a single audio file (offline)
  python3 app.py --source file --input ./clip.flac --lat 41.88 --lon -87.98

  # Dev: capture from a network camera / USB mic (no cache)
  python3 app.py --source camera --camera 'rtsp://user:pass@IP/media.smp'
""")

    parser.add_argument("--source", required=True,
                        choices=["cache", "file", "camera"],
                        help="cache = consume v2 audio frames from the shared cache "
                             "(production); file = a local audio file (dev); "
                             "camera = ffmpeg/USB-mic capture (dev).")
    parser.add_argument("--input", "-i",
                        help="cache: per-stream dir <root>/<cache-name>/<source>. "
                             "file: path to an audio file.")

    # Cache consumer knobs (identical set to sage-bioclip2 / sage-yolo2)
    cache = parser.add_argument_group("cache consumer (--source cache)")
    cache.add_argument("--every", default="0",
                       help="Wake cadence. 0 = single-shot. Accepts s/m/h.")
    cache.add_argument("--select-every", default="0",
                       help="Sampling stride (one frame per this much capture-time). "
                            "0 = the newest unseen frame.")
    cache.add_argument("--max-frames", type=int, default=1,
                       help="Cap frames per wake (0 = unlimited).")
    cache.add_argument("--all-unseen", action="store_true",
                       help="Backlog mode: classify every not-yet-seen frame.")
    cache.add_argument("--max-runtime", type=int, default=0,
                       help="Wall-clock bound in seconds (0 = forever).")
    cache.add_argument("--consumer-id", default=None,
                       help="Override the seen-store consumer-id segment.")
    cache.add_argument("--seen-store", default=None, help="Override seen-store path.")
    cache.add_argument("--reprocess", action="store_true",
                       help="Ignore the seen-store (still records what it processes).")

    # Dev capture parameters (--source camera)
    dev = parser.add_argument_group("dev capture (--source camera)")
    dev.add_argument("--camera",
                     help="URL for network camera audio (Mobotix MxPEG, RTSP, or any "
                          "ffmpeg source). If --source camera and --camera is omitted, "
                          "records from the node USB microphone.")
    dev.add_argument("--duration", type=float, default=15.0,
                     help="Recording duration in seconds (camera / microphone).")
    dev.add_argument("--sample-rate", type=int, default=48000,
                     help="Capture sample rate in Hz (camera / microphone).")

    # Model parameters
    model = parser.add_argument_group("model parameters")
    model.add_argument("--min-confidence", type=float, default=0.6,
                       help="Minimum confidence threshold (0.01–0.99).")
    model.add_argument("--sensitivity", type=float, default=1.0,
                       help="Detection sensitivity (0.5–1.5). Higher = more sensitive.")
    model.add_argument("--overlap", type=float, default=0.0,
                       help="Overlap in seconds between 3-second analysis windows (0.0–2.9).")
    model.add_argument("--top-k", type=int, default=5,
                       help="Max predictions per 3-second chunk.")
    model.add_argument("--bandpass-fmin", type=int, default=0,
                       help="Bandpass filter minimum frequency in Hz.")
    model.add_argument("--bandpass-fmax", type=int, default=8000,
                       help="Bandpass filter maximum frequency in Hz. Default 8000 for "
                            "the 16kHz cache substream (Nyquist); raise for wideband mics.")
    model.add_argument("--batch-size", type=int, default=1,
                       help="Number of 3-second chunks to process in parallel.")

    # Location filtering (eBird)
    loc = parser.add_argument_group("location filtering (eBird)")
    loc.add_argument("--lat", type=float, default=-1,
                     help="Latitude for species range filtering. -1 = auto (node identity).")
    loc.add_argument("--lon", type=float, default=-1,
                     help="Longitude for species range filtering. -1 = auto (node identity).")
    loc.add_argument("--week", type=str, default="auto",
                     help="Week of year (1–48) for seasonal filtering. "
                          "'auto' = from current date. -1 for year-round.")
    loc.add_argument("--sf-thresh", type=float, default=0.03,
                     help="Species filter threshold for geo model (0.0–1.0).")

    # Save / upload
    save = parser.add_argument_group("save / upload")
    save.add_argument("--save-match", type=str, default="",
                      help="OR-list of 'Name:confidence' rules (matches common OR "
                           "scientific name), e.g. \"Northern Cardinal:0.5\" or "
                           "\"*:0.5\". Upload the FLAC clip when ANY detection matches. "
                           "Omit to save no audio (topics + heartbeat still publish).")

    return parser


# ── cache wake loop (mirrors sage-bioclip2) ──────────────────────────────────
def _frame_uid(frame):
    """unique_id for dedup — from the sidecar; falls back to the frame name."""
    meta = consumer.read_frame_metadata(frame)
    return meta.unique_id or frame.name


def _identity_meta(identity, camera):
    """Build the frame-anchored base meta (vsn/node_id/lat/lon/camera) for publishes."""
    base = {"camera": camera}
    if identity is not None:
        if identity.vsn:
            base["vsn"] = identity.vsn
        if identity.node_id:
            base["node_id"] = identity.node_id
        if identity.has_location:
            base["lat"] = str(identity.lat)
            base["lon"] = str(identity.lon)
            base["location_source"] = identity.location_source
    return base


def _maybe_upload_clip(plugin, args, save_rules, detections, clip_path, timestamp,
                       base_meta):
    """Upload the FLAC clip per --save-match (matches common OR scientific name)."""
    if not (save_rules and detections):
        return
    if not should_save(save_rules, detections,
                       name_keys=["common_name", "scientific_name"]):
        return
    try:
        top = max(detections, key=lambda d: d["confidence"])
        meta = dict(base_meta)
        meta.update({
            "top_species": str(top["scientific_name"]),
            "common_name": str(top["common_name"]),
            "confidence": str(top["confidence"]),
        })
        plugin.upload_file(clip_path, timestamp=timestamp, meta=meta)
        logger.info("Saved audio clip (save-match matched: %s %.4f)",
                    top["scientific_name"], top["confidence"])
    except Exception:
        logger.exception("Audio clip upload failed")


def _process_cache_wake(plugin, classifier, args, save_rules, seen, node_info,
                        last_wake_ts_ns, select_every_s):
    """One cache wake: scan → select → per frame read sidecar meta + identity,
    analyze the FLAC, publish frame-anchored, mark seen."""
    frames = consumer.scan_frames(args.input)
    selected = selection.select_frames(
        frames, last_wake_ts_ns=last_wake_ts_ns,
        select_every_ns=select_every_s * 1_000_000_000,
        all_unseen=args.all_unseen, max_frames=args.max_frames,
        seen=seen, reprocess=args.reprocess, uid_of=_frame_uid)
    if not selected:
        logger.info("cache wake: 0 clips to classify")
        return

    for frame in selected:
        if not os.path.exists(frame.path):
            logger.warning("clip vanished before read: %s", frame.name)
            continue
        meta = consumer.read_frame_metadata(frame)     # audio → sidecar reader
        identity = consumer.resolve_identity(meta, node_info=node_info)
        ts = meta.capture_ts_ns                        # FRAME-ANCHORED timestamp
        cam = meta.camera or frame.camera
        base_meta = _identity_meta(identity, cam)

        with plugin.timeit("plugin.duration.inference"):
            detections = classifier.classify_file(frame.path)

        logger.info("Classified %s: %d detections", frame.name, len(detections))
        publish_detections(plugin, detections, ts, base_meta=base_meta)
        if detections:
            _log_detections(detections)
        _maybe_upload_clip(plugin, args, save_rules, detections, frame.path, ts,
                           base_meta)

        if meta.unique_id:
            seen.mark(meta.unique_id)


# ── dev/offline single-shot (--source file | camera) ─────────────────────────
def _get_dev_audio(args) -> tuple[str, bool]:
    """Acquire audio for a dev/offline run. Returns (path, needs_cleanup)."""
    if args.source == "file":
        if not args.input:
            logger.error("--source file requires --input <audio file>")
            sys.exit(2)
        return args.input, False
    # --source camera: a URL captures via ffmpeg, else the USB microphone.
    if args.camera:
        return record_from_camera(args.camera, args.duration, args.sample_rate), True
    return record_from_microphone(args.duration, args.sample_rate), True


def _process_dev(plugin, classifier, args, save_rules):
    """One dev/offline classify cycle. Frame-anchored to wall-clock (no cache ts)."""
    timestamp = time.time_ns()
    with plugin.timeit("plugin.duration.input"):
        audio_path, cleanup = _get_dev_audio(args)
    try:
        with plugin.timeit("plugin.duration.inference"):
            detections = classifier.classify_file(audio_path)
        logger.info("Classified %s: %d detections",
                    os.path.basename(audio_path), len(detections))
        publish_detections(plugin, detections, timestamp)
        if detections:
            _log_detections(detections)
        _maybe_upload_clip(plugin, args, save_rules, detections, audio_path,
                           timestamp, {})
    finally:
        if cleanup and os.path.exists(audio_path):
            shutil.rmtree(os.path.dirname(audio_path), ignore_errors=True)


# ── main ──────────────────────────────────────────────────────────────────────
def main():
    args = build_parser().parse_args()

    # Clamp parameters to valid ranges.
    args.min_confidence = max(0.01, min(args.min_confidence, 0.99))
    args.sensitivity = max(0.5, min(args.sensitivity, 1.5))
    args.overlap = max(0.0, min(args.overlap, 2.9))

    # Parse --save-match up front and FAIL FAST on a malformed spec.
    try:
        save_rules = parse_save_match(args.save_match)
    except SaveMatchError as e:
        logger.error("Invalid --save-match: %s", e)
        sys.exit(2)
    if save_rules:
        logger.info("Audio save rules (--save-match): %s",
                    ", ".join(f"{'*' if r.is_wildcard else r.name}>={r.min_confidence}"
                              for r in save_rules))
    else:
        logger.info("No --save-match rules: audio clips will NOT be saved "
                    "(detection topics + heartbeat still publish every frame).")

    # Resolve --week: "auto" → current week, or parse as int.
    if str(args.week).lower() == "auto":
        args.week = current_birdnet_week()
        logger.info("Auto-detected BirdNET week: %d", args.week)
    else:
        args.week = int(args.week)

    try:
        every_s = selection.parse_duration(args.every)
        select_every_s = selection.parse_duration(args.select_every)
    except ValueError as e:
        logger.error("Invalid duration: %s", e)
        sys.exit(2)

    is_cache = args.source == "cache"

    # Node identity (WAGGLE_NODE_* env) — the pod's own view. Its GPS is the eBird
    # location fallback when the sidecar lat/lon is null (which it currently is).
    node_info = consumer.get_node_info()

    # Cache-consumer setup + fail-fast on an absent cache (mirrors bioclip2).
    seen = None
    if is_cache:
        if not args.input:
            logger.error("--source cache requires --input <cache dir>")
            sys.exit(2)
        try:
            consumer.assert_cache_available(args.input)
        except consumer.CacheError as e:
            logger.error("%s", e)
            sys.exit(2)
        cache_root = consumer.resolve_cache_root()
        cache_name, source = parse_cache_input(args.input, cache_root)
        consumer_id = resolve_consumer_id(args.consumer_id)
        store_path = args.seen_store or seenstore.seen_store_path(
            cache_root, consumer_id, cache_name, source)
        seen = seenstore.SeenStore(store_path, reprocess=args.reprocess)
        logger.info("cache consumer: input=%s consumer-id=%s seen-store=%s (%d known)",
                    args.input, consumer_id, store_path, len(seen))

    # Resolve eBird location (CLI > node identity > disabled) and wire the classifier.
    lat, lon = resolve_location(args, node_info)
    classifier = BirdNETClassifier(
        min_confidence=args.min_confidence, sensitivity=args.sensitivity,
        overlap=args.overlap, top_k=args.top_k, lat=lat, lon=lon, week=args.week,
        sf_thresh=args.sf_thresh, bandpass_fmin=args.bandpass_fmin,
        bandpass_fmax=args.bandpass_fmax, batch_size=args.batch_size,
    )

    with Plugin() as plugin:
        logger.info("sage-birdnet2 started — source=%s input=%s min_conf=%.2f "
                    "bandpass_fmax=%d every=%ds",
                    args.source, args.input, args.min_confidence,
                    args.bandpass_fmax, every_s)
        with plugin.timeit("plugin.duration.loadmodel"):
            classifier.load()

        if not is_cache:
            # Dev/offline: single classify cycle then exit.
            try:
                _process_dev(plugin, classifier, args, save_rules)
            except Exception:
                logger.exception("dev-run error")
            return

        # Cache production loop (two clocks: --every wake cadence + --select-every stride).
        deadline = None
        if every_s > 0 and args.max_runtime > 0:
            deadline = time.monotonic() + args.max_runtime

        last_wake_ts_ns = 0
        while True:
            try:
                _process_cache_wake(plugin, classifier, args, save_rules, seen,
                                    node_info, last_wake_ts_ns, select_every_s)
                last_wake_ts_ns = time.time_ns()
            except Exception:
                logger.exception("wake error")

            if every_s == 0:
                break
            if deadline is not None and time.monotonic() + every_s >= deadline:
                logger.info("Max runtime reached — self-exiting to free the node")
                break
            time.sleep(every_s)


if __name__ == "__main__":
    main()
