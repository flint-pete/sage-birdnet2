# sage-birdnet2

A **BirdNET V2.4 audio species classifier** for Sage/Waggle, built as a v2 **cache
consumer**. It reads the 15-second FLAC clips that media-sampler3's audio producer
writes into the node's shared `/local-cache`, runs BirdNET on each clip, and
publishes per-species detections. Each detection's timestamp is the time the clip
was **recorded**, not the time BirdNET ran.

> **Status: verified on H039 with a seeded clip; the live microphone is next.**
> - **On-node test (H039, Oct 2026):** a seeded 15 s Eastern Bluebird clip in
>   `/local-cache/camera-audio/mic/`. It came back as *Sialia sialis* in three
>   3-second windows (0.89–0.9996). The eBird filter used the node's GPS (131
>   species). `env.detection.audio.summary` and `env.detection.biophony.sialia_sialis`
>   reached Beehive with the node's VSN and lat/lon.
> - **The producer side is proven:** the media-sampler3 audio producer ran on H00F,
>   recording 15 s FLAC clips with `.flac.json` sidecars once a minute.
> - **Not yet done:** producer and birdnet2 together on a live camera microphone.
> - `make test` passes **48 tests**, including the audio-sidecar metadata reader.

## Where this fits

sage-birdnet2 is the **audio** example consumer in the media-sampler3 stack. It's
the counterpart to the two image examples:

```
camera mic ─▶ media-sampler3 --media audio ─▶ /local-cache/camera-audio/mic/ ─▶ sage-birdnet2 ─▶ env.detection.* ─▶ Beehive
                                               (clip.flac + clip.flac.json)

camera ─▶ media-sampler3 ─▶ /local-cache/camera/top/ ─▶ sage-yolo2 ─▶ camera-crops/ ─▶ sage-bioclip2      (image examples)
```

| Related | Role |
|---|---|
| [media-sampler3](https://github.com/flint-pete/media-sampler3) | The producer whose clips this reads. Hub repo: [install guide](https://github.com/flint-pete/media-sampler3/blob/master/INSTALLING-MEDIA-SAMPLER3.md), [REBOOT-RECOVERY.md](https://github.com/flint-pete/media-sampler3/blob/master/REBOOT-RECOVERY.md), [HOW-IT-WORKS.md](https://github.com/flint-pete/media-sampler3/blob/master/docs/HOW-IT-WORKS.md) |
| [sage-yolo2](https://github.com/flint-pete/sage-yolo2) | Source of the copied cache-consumer modules (see `VENDORED.md`) |
| [wes-local-cache-manager](https://github.com/flint-pete/wes-local-cache-manager) | Provides and bounds `/local-cache`; never evicts `.state/`, where the seen-store lives |

**What's different from the image consumers.** Audio has no EXIF, so
media-sampler3 writes each clip's provenance into a **sidecar** file,
`<clip>.flac.json`. The sidecar is written *before* the clip, so whenever a clip
is visible, its sidecar already exists. The sidecar's `unique_id` is the SHA-256 of
the clip. sage-birdnet2's `consumer.py` is yolo2's, plus a small, clearly marked
**sidecar reader**. That reader is the only code that differs from the copied
modules.

**Code map**

| File | What it does | Origin |
|---|---|---|
| `app.py` | CLI, wake loop, `BirdNETClassifier`, eBird geo/season filter, topic routing, clip upload (`--save-match`) | this repo; the loop follows sage-yolo2/bioclip2 |
| `consumer.py` | Read side of the v2 cache contract: scans `-v2-` names (`.flac`/`.wav` too) and reads metadata (**sidecar** for audio). Fails fast if the cache is missing. Resolves identity (clip first, pod env as fallback). | sage-yolo2 + the audio-sidecar addition |
| `selection.py`, `seenstore.py`, `node_info.py`, `save_match.py` | Clip selection, seen-store dedup, pod identity, `Name:confidence` rules | copied unchanged from sage-yolo2 |
| `scripts/deploy-sideload.sh` | Native Thor build plus k3s import (identical to yolo2's and bioclip2's) | sage-yolo2 |
| `RESEARCH.md` | Survey of wildlife-audio models (why BirdNET V2.4) | this repo |

## Run it on a Thor node

The install guide covers this end to end: build in Step 5, the seeded-audio test
in Steps 6b–6g, and the live camera microphone in 6h. The command:

```bash
cd ~/AI-projects/sage-birdnet2
scripts/deploy-sideload.sh --skip-register     # CPU image (python:3.12-slim + BirdNET), arm64 build -> k3s

sudo pluginctl-nodeinfo run --name sage-birdnet2-consumer --selector zone=core \
  --resource limit.memory=2Gi,request.memory=1Gi \
  -v /media/plugin-data/local-cache:/local-cache \
  -e WAGGLE_JOB_NAME=camera -e WAGGLE_TASK_NAME=sage-birdnet2 \
  registry.sagecontinuum.org/beckman/sage-birdnet2:2.0.0 -- \
  --source cache --input /local-cache/camera-audio/mic \
  --every 10m --all-unseen --max-frames 0 --min-confidence 0.6 &
```

`pluginctl-nodeinfo` is the patched `pluginctl` from install Step 3 (same flags).

What the flags do:

- **`--input`** is the producer's `--cache-name`/`--stream`
  (`camera-audio` / `mic`). If you change the producer, change this to match.
- **`-e WAGGLE_JOB_NAME/-e WAGGLE_TASK_NAME`** name the seen-store. Keep them the
  same across relaunches. Because of a quirk in the copied code, the store lives at
  `/local-cache/.state/sage-yolo2/camera-sage-birdnet2/camera-audio/mic/seen`
  (see VENDORED.md).
- **Location, for BirdNET's eBird range filter** (species plausible at that place
  and week). The location comes from, in order:
  1. `--lat/--lon`, if given (an override);
  2. the node's GPS from the pod env (`WAGGLE_NODE_GPS_*`), which
     `pluginctl-nodeinfo` provides;
  3. otherwise, none. The filter is then off and you get the global species list,
     with more false positives. The startup log says which source was used.

  (Each clip's sidecar also carries the node's GPS, written by the producer, and
  that is what appears in the published records' `lat`/`lon`.)
- **`--resource`**: BirdNET is CPU-only, and measured 0.53 GB peak and 0.31 GB
  steady on H039, so 2Gi leaves plenty of headroom. (The GPU consumers need
  `16Gi`.)
- **Expect a backlog on the first run.** With `--all-unseen`, the first wake
  classifies every clip already in the ring. That's up to 500 at the producer's
  `--cache-max-count 500`. Use `--select-every 0 --max-frames K` with a new
  `--consumer-id` to do only the newest K.

**Check it reached the cloud:**

```bash
q() { curl -s -X POST https://data.sagecontinuum.org/api/v1/query -H 'Content-Type: application/json' \
      -d "{\"start\":\"-30m\",\"filter\":{\"vsn\":\"$VSN\",\"name\":\"$1\"}}" | tail -2; }
q env.detection.audio.summary      # one per clip, even with no detections (heartbeat)
q 'env.detection.biophony.*'       # bird/frog/insect detections, if any
```

**Quick model check without the cache** (dev). This classifies one file instead
of reading the cache. Run inside a pod, it publishes like a normal run:

```bash
python3 app.py --source file --input ./clip.flac --lat 41.88 --lon -87.98
```

## Published data

| Topic | Value | When |
|---|---|---|
| `env.detection.biophony.<scientific_name>` | confidence (float) | each detection of a living organism (birds, frogs, insects), e.g. `env.detection.biophony.cardinalis_cardinalis` |
| `env.detection.anthrophony.<name>` | confidence | human-made sounds (engine, siren, dog, …) |
| `env.detection.geophony.<name>` | confidence | abiotic sounds (noise, environmental) |
| `env.detection.audio.summary` | JSON | **every clip**, even with zero detections: totals, per-category counts, best confidence per species |
| upload (FLAC) | the clip | only when a detection matches `--save-match` (e.g. `"Northern Cardinal:0.5"`) |

- **Meta on every detection:**
  - the clip identity: `camera` (the stream, e.g. `mic`), `vsn`, `node_id`, and
    `lat`/`lon`/`location_source` when known
  - `common_name`, `category`, and `start_time_s`/`end_time_s` (where in the clip
    the 3-second window was)
- **Timestamp:** the clip's **capture time** from its filename, so it is
  frame-anchored.
- **Thresholds:** `--min-confidence` (default 0.6) drops weak predictions.
  `--bandpass-fmax 8000` (the default) matches the 16 kHz camera-mic stream.

## Wake, select and seen-memory

These work the same as sage-yolo2 (see its README §7):

- `--every` sets the wake cadence.
- `--all-unseen` drains the backlog.
- `--max-frames 0` means no cap per wake.
- The seen-store is keyed on each clip's `unique_id` from its sidecar.
- A clip with a missing or corrupt sidecar still gets processed (its name gives
  the time and stream), but it has no `unique_id`. So it is **reprocessed on
  every wake** until the ring evicts it. A hand-copied test clip, such as the
  install guide's seeded bluebird (`tests/test-audio/`), behaves the same way;
  delete it after use.

## Testing

`make test` sets up its own throwaway venv and runs the offline suite: selection,
seen-store, and the audio-sidecar contract (`tests/test_sidecar_meta.py`). It
needs no BirdNET model and no node. The real-model check is the install guide's
seeded-audio test: `tests/test-audio/eastern-bluebird-XC179669.flac` (CC BY-SA;
see that folder's README) should come back as `Sialia sialis`.

## Docs in this repo

- [DOCKER-BUILD.md](DOCKER-BUILD.md): build and side-load, plus what's verified where.
- [VENDORED.md](VENDORED.md): copied modules, the one sidecar addition, and what must stay in sync.
- [RESEARCH.md](RESEARCH.md): the model survey behind BirdNET V2.4.
- [CHANGELOG.md](CHANGELOG.md): release notes.
- [docs/history/](docs/history/): the original handoff skeleton (not maintained).

## Contact

Pete Beckman, pete.beckman@northwestern.edu
