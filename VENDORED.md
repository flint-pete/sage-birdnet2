# Vendored code

Modules vendored from `sage-yolo2` — this is the v2 cache-consumer pattern,
shared across the v2 plugin family (media-sampler3 producer → sage-yolo2 /
sage-bioclip2 / sage-birdnet2 consumers). sage-birdnet2 is the AUDIO consumer of
the same contract, so it reuses the read-side machinery. Four of the five modules
are **byte-identical**; `consumer.py` carries **one intentional divergence** for
audio (see below).

| Module | Source | Role |
|---|---|---|
| `selection.py` | sage-yolo2 (byte-identical) | frame/clip selection (stride / all-unseen / newest), duration parsing |
| `seenstore.py` | sage-yolo2 (byte-identical) | dedup memory (seen unique_ids), bounded, restart-durable |
| `node_info.py` | sage-yolo2 (byte-identical) | pod self-identity from WAGGLE_NODE_* env (itself vendored from pywaggle2-nodeinfo) |
| `save_match.py` | sage-yolo2 (byte-identical) | `Name:confidence` OR-rule parsing + matching |
| `consumer.py` | sage-yolo2 (**vendored-with-ONE-divergence**) | v2 cache read: scan/parse/newest, metadata read, identity resolution — **plus an added `.flac.json` sidecar metadata reader for audio frames** |

## The one divergence: `consumer.py`'s audio sidecar reader

Image frames (media-sampler3 / sage-yolo2 crops) are self-describing via a JSON
blob embedded in the JPEG's EXIF **UserComment**. A **FLAC audio clip has no EXIF
container**, so the v2 audio producer instead writes a **sidecar JSON** next to
each clip:

```
<ts>-v2-<vsn>-<camera>.flac          # the 15-second audio clip
<ts>-v2-<vsn>-<camera>.flac.json     # its self-describing metadata sidecar
```

sage-birdnet2's `consumer.py` is therefore **NOT byte-identical** to sage-yolo2's:
it adds a `.flac.json` sidecar reader path so `read_frame_metadata(...)` can
resolve audio-frame metadata (`media_type=audio`, `capture_timestamp_ns`,
`unique_id`, `vsn`, `camera`, `source_type=camera_mic`, `schema_version=
sage-media-1`, `lat`/`lon`, `acquisition_path`). The **contract is unchanged**:
`capture_ts_ns` is taken from the FILENAME (authoritative ordering key); the
sidecar supplies identity; `lat`/`lon` are `None` when absent (never fabricated);
and reading is **fail-soft** (a clip with no/corrupt sidecar still yields the
filename-derived fields and does not crash). That divergence is the sole reason
`consumer.py` is not diff-clean against sage-yolo2 — everything else in the file
is the shared v2 read machinery.

Concretely, the divergence in `consumer.py` is two small, adjacent, clearly
commented parts (see the `DIVERGENCE` banner in the file):

1. **Frame extensions** — `parse_v2_name` / `scan_frames` accept `.flac`/`.wav`
   in addition to `.jpg` (`_FRAME_EXTS`). The `-v2-` split logic is **unchanged**;
   only the accepted trailing extension set is generalized, so `.flac` clips are
   discovered and ordered exactly like `.jpg` frames. Sidecar `.flac.json` files
   are NOT in `_FRAME_EXTS`, so `scan_frames` correctly ignores them as frames.
2. **Sidecar reader** — `read_frame_metadata(frame, media_type=None)` routes AUDIO
   frames to `_read_sidecar_json()` (a `<clip>.<ext>.json` reader); `media_type`
   defaults to extension-inferred (`.flac`/`.wav` → audio → sidecar, else → EXIF).

Guard: `tests/test_sidecar_meta.py` is the contract test for the audio sidecar
reader.

## Verify identity of the four byte-identical modules

The four byte-identical modules must diff-clean against sage-yolo2. `consumer.py`
is deliberately excluded (it has the audio-sidecar divergence above).

```sh
Y=../sage-yolo2
for m in selection.py seenstore.py node_info.py save_match.py; do
  diff "$m" "$Y/$m" && echo "$m: identical" || echo "$m: DRIFT"
done
# consumer.py is intentionally NOT byte-identical (audio .flac.json sidecar
# reader). Its contract is guarded by tests, not a diff:
#   make test   # -> tests/test_sidecar_meta.py (+ carried-over vendored tests)
```

## Known quirk: seen-store directory

The vendored `seenstore.py` hard-codes `PLUGIN_NAME = "sage-yolo2"`, so
sage-birdnet2's seen-store lives under
`/local-cache/.state/sage-yolo2/<consumer-id>/camera-audio/mic/seen`. Its
consumer-id (e.g. `camera-sage-birdnet2`) keeps it separate from yolo2's and
bioclip2's stores. Same quirk as sage-bioclip2; documented, not changed.

## Sync obligation

These modules are the **v2 read contract**. sage-birdnet2 reads exactly the v2
frames the producer writes. If the v2 format changes (media-sampler3
`metadata.py` / `audio_metadata.py` sidecar schema), re-vendor the four
byte-identical modules from sage-yolo2, mirror any sidecar-schema change in
`consumer.py`'s audio reader, and re-run `make test`. The carried-over
`tests/test_selection.py` / `tests/test_seenstore.py` guard the byte-identical
modules; `tests/test_sidecar_meta.py` guards the audio-reader divergence.

## Future: extract a shared package

Vendoring was chosen (matching the sage-yolo2 / sage-bioclip2 precedent) to keep
this a single-repo build. With THREE consumers now on the same contract,
extracting a shared `sage-cache-consumer` package is the cleaner long-term move —
tracked as a family-wide follow-up.
