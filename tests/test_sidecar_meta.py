#!/usr/bin/env python3
"""Unit tests for the AUDIO sidecar metadata reader (consumer.read_frame_metadata).

sage-birdnet2 is a v2 cache CONSUMER of AUDIO frames. Unlike the image family
(media-sampler3 / sage-yolo2 / sage-bioclip2), whose self-describing metadata is
embedded in EXIF UserComment inside the JPEG, an audio clip (FLAC) has no EXIF
container. The v2 audio producer therefore writes the metadata to a SIDECAR JSON
file next to the clip:

    <ts>-v2-<vsn>-<camera>.flac          <- the audio clip
    <ts>-v2-<vsn>-<camera>.flac.json     <- its metadata sidecar (self-describing)

This is the ONE intentional divergence of sage-birdnet2's consumer.py from the
byte-identical sage-yolo2 vendor (see VENDORED.md): a ``.flac.json`` sidecar
reader for audio frames. Everything else (scan / parse / newest / selection /
seenstore / identity) is the shared v2 read contract.

These tests assert the reader's CONTRACT, pure-stdlib against /tmp fixtures:
  * capture_ts_ns comes from the FILENAME (authoritative ordering key), even if
    the sidecar carries a differing capture_timestamp_ns.
  * unique_id / vsn / camera come from the sidecar when present.
  * lat / lon are None when the sidecar has null coordinates (never fabricated).
  * fail-soft: a .flac with NO sidecar still yields filename-derived
    capture_ts + vsn + camera and does NOT crash.

CONTRACT NOTE (consumer.py authored by a parallel worker):
These tests exercise ``consumer.read_frame_metadata(frame, media_type='audio')``
and expect a FrameMeta with attributes ``capture_ts_ns, unique_id, vsn, node_id,
camera, lat, lon, acquisition_path`` -- the same FrameMeta shape used by
sage-bioclip2 / sage-yolo2's consumer.py. The landed consumer.py takes a **Frame
object** (from a Stage-1 ``scan_frames`` / ``newest_frame`` scan), not a raw
path, so ``_read()`` below builds the Frame via ``consumer.newest_frame(dir)``
(the fixture writes exactly one clip per tmp dir). This is the documented single
point of coupling: if a future consumer.py changes the entry point again, edit
``_read()`` only -- the asserted behaviour (filename ts is authoritative, sidecar
supplies identity, no/corrupt sidecar is fail-soft) is the stable contract.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import consumer  # noqa: E402


# --- the single point of coupling to consumer.py's signature -----------------
# All tests go through here so a signature change is a one-line edit, not a
# scatter of call-site rewrites. read_frame_metadata takes a Frame object (not a
# path); we obtain it from a real Stage-1 scan of the clip's directory. Each
# fixture writes exactly ONE clip per tmp dir, so newest_frame() returns it.
def _read(clip_path):
    """Read audio-frame metadata via the documented consumer contract."""
    frame = consumer.newest_frame(os.path.dirname(clip_path))
    assert frame is not None, "fixture clip was not scanned as a v2 frame"
    return consumer.read_frame_metadata(frame, media_type="audio")


# --- fixture: a fake v2 FLAC clip + its .flac.json sidecar -------------------

# Real audio sidecar schema (mirrors the image UserComment JSON field set, minus
# the EXIF-only bits). vsn=H00F, camera=mic, source_type=camera_mic.
_VSN = "H00F"
_CAMERA = "mic"
_CAPTURE_TS_NS = 1_700_000_000_123_456_789


def _write_clip(dir_path, *, capture_ts_ns=_CAPTURE_TS_NS, vsn=_VSN,
                camera=_CAMERA, unique_id="cafef00d", node_id="000048b02d",
                lat=None, lon=None, acquisition_path="native-raw",
                write_sidecar=True, sidecar_overrides=None):
    """Create ``<ts>-v2-<vsn>-<camera>.flac`` (empty) + optional sidecar JSON.

    Returns the absolute path to the .flac clip.
    """
    name = "%d-v2-%s-%s.flac" % (capture_ts_ns, vsn, camera)
    clip = os.path.join(str(dir_path), name)
    # An empty file is fine -- the reader must not decode audio, only read the
    # filename + the sidecar.
    open(clip, "wb").close()

    if write_sidecar:
        fields = {
            "media_type": "audio",
            "capture_timestamp_ns": capture_ts_ns,
            "unique_id": unique_id,
            "vsn": vsn,
            "node_id": node_id,
            "camera": camera,
            "source_type": "camera_mic",
            "schema_version": "sage-media-1",
            "lat": lat,
            "lon": lon,
            "acquisition_path": acquisition_path,
        }
        if sidecar_overrides:
            fields.update(sidecar_overrides)
        with open(clip + ".json", "w") as f:
            json.dump(fields, f, separators=(",", ":"), sort_keys=True)

    return clip


# --- happy path: sidecar supplies identity, filename supplies ts -------------

def test_reads_authoritative_fields_from_sidecar(tmp_path):
    clip = _write_clip(tmp_path, unique_id="abc123", vsn="H00F",
                       camera="mic", node_id="000048b02d",
                       acquisition_path="native-raw")
    m = _read(clip)
    # capture_ts is the FILENAME prefix (authoritative ordering key).
    assert m.capture_ts_ns == _CAPTURE_TS_NS
    # identity from the sidecar.
    assert m.unique_id == "abc123"
    assert m.vsn == "H00F"
    assert m.camera == "mic"
    assert m.node_id == "000048b02d"
    assert m.acquisition_path == "native-raw"


def test_observation_ts_is_capture_ts_from_filename(tmp_path):
    clip = _write_clip(tmp_path, capture_ts_ns=42_000_000_000)
    assert _read(clip).capture_ts_ns == 42_000_000_000


def test_null_coords_are_none_never_fabricated(tmp_path):
    # sidecar carries lat=null, lon=null -> reader must yield None, not 0.0.
    clip = _write_clip(tmp_path, lat=None, lon=None)
    m = _read(clip)
    assert m.lat is None
    assert m.lon is None


def test_signed_coords_roundtrip_when_present(tmp_path):
    clip = _write_clip(tmp_path, lat=-33.8688, lon=-151.2093)
    m = _read(clip)
    assert m.lat == pytest.approx(-33.8688)
    assert m.lon == pytest.approx(-151.2093)


# --- filename ts is authoritative even against the sidecar -------------------

def test_filename_ts_wins_over_sidecar_ts(tmp_path):
    # filename says _CAPTURE_TS_NS; sidecar disagrees -> reader keeps the filename.
    clip = _write_clip(tmp_path, capture_ts_ns=_CAPTURE_TS_NS,
                       sidecar_overrides={"capture_timestamp_ns": 999})
    m = _read(clip)
    assert m.capture_ts_ns == _CAPTURE_TS_NS


# --- fail-soft: no sidecar at all -------------------------------------------

def test_no_sidecar_falls_back_to_filename(tmp_path):
    # A .flac with NO .flac.json sidecar must still yield filename-derived
    # capture_ts + vsn + camera, and MUST NOT crash.
    clip = _write_clip(tmp_path, vsn="W999", camera="deck_mic",
                       write_sidecar=False)
    m = _read(clip)
    assert m.capture_ts_ns == _CAPTURE_TS_NS
    assert m.vsn == "W999"          # filename fallback
    assert m.camera == "deck_mic"   # filename fallback
    assert m.unique_id is None      # only the sidecar carries this
    assert m.lat is None and m.lon is None


def test_corrupt_sidecar_is_fail_soft(tmp_path):
    # A present-but-unparseable sidecar must degrade to filename-derived fields,
    # not raise.
    clip = _write_clip(tmp_path, write_sidecar=False)
    with open(clip + ".json", "w") as f:
        f.write("{not valid json")
    m = _read(clip)
    assert m.capture_ts_ns == _CAPTURE_TS_NS   # still usable
    assert m.unique_id is None
