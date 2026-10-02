# Changelog

All notable changes to the `sage-birdnet2` Sage plugin.

## Unreleased (docs/naming only; image stays 2.0.0)

### Added
- `README.md`: what it does, where it fits (the audio example consumer for
  media-sampler3), its link to the original [birdnet](https://github.com/flint-pete/birdnet)
  plugin, a code map, the Thor run command, published topics, and an honest status
  (offline-tested; on-node run pending).
- `scripts/deploy-sideload.sh` (+ `register-ecr-version.py`), identical to
  sage-yolo2/sage-bioclip2, so all three example consumers build the same way.

### Changed
- Example paths now match media-sampler3's audio producer
  (`/local-cache/camera-audio/mic`); the old hummingcam / image-sampler2 names are
  gone from code comments, docs and test fixtures (no behaviour change; 48 tests
  pass).
- `sage.yaml` inputs now list exactly the CLI flags in `app.py`:
  - removed `model`, `geo-filter` and `upload-audio`, which don't exist
  - added the dev-capture, model, location and runtime flags
  - corrected the `min-confidence` default to 0.6 and the sources to
    cache/file/camera
- `DOCKER-BUILD.md`:
  - removed the non-existent `--model` flag and the non-existent
    `env.detection.species` topic
  - the real topics are `env.detection.{biophony,anthrophony,geophony}.*` and
    `env.detection.audio.summary`
- The vendored `node_info.py` was re-synced to pywaggle2-nodeinfo v0.1.1 (a
  doc-link line only).
- `HANDOFF.md` (a 2026-07 skeleton with TODOs) moved to `docs/history/`.
  `VENDORED.md` documents the seen-store directory quirk.

## 2.0.0 — 2026-07-23

First version: BirdNET V2.4 re-architected onto the sage-yolo2 v2 cache-consumer
pattern, reading media-sampler3 audio clips and their `.flac.json` sidecars from
`/local-cache`. Offline suite: 48 tests.
