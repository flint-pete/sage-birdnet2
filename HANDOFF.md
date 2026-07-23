# HANDOFF — sage-birdnet2 2.0.0 (skeleton)

Records plugin state, the deploy path, and (once proven) the live node state.
Fill the TODO blocks as on-node verification lands.

## Plugin state
- Version **2.0.0**, branch `master`.
- Architecture: **pywaggle2 v2 cache consumer** (the sage-yolo2 / sage-bioclip2
  pattern), adapted for **audio**. Reads self-describing `-v2-` 15-second FLAC
  clips from the shared `/local-cache`; the `--input` dir selects the audio
  stream. Publishes per-species detections (`env.detection.*`). Metadata is read
  from a `.flac.json` sidecar the producer writes next to each clip — the ONE
  divergence from the byte-identical sage-yolo2 vendor (see `VENDORED.md`).
- Offline suite: `make test` → carried-over vendored tests (`test_selection.py`,
  `test_seenstore.py`) + the audio sidecar contract (`test_sidecar_meta.py`).
  Pure-stdlib pytest, no BirdNET / model / node. **TODO: record pass count once
  consumer.py's audio reader lands and the suite is green.**

## Deploy path
- **CPU-only** (BirdNET V2.4 TFLite; no CUDA base). ECR portal build should work
  for a CPU-only plugin; the proven dev/test path is native aarch64 build + k3s
  side-load + `pluginctl run` — see `DOCKER-BUILD.md`.
- New private repos have no fresh-clone creds on the node; transfer via git
  bundle if needed (`git bundle create /tmp/x.bundle --all` → scp → clone).

## Verified on H00F (Thor/arm64) — TODO
End-to-end producer → **sage-birdnet2 (audio consumer)** on H00F.
- [ ] TODO: confirm `env.detection.species` published via the data API, with
      frame-anchored timestamp, `vsn=H00F`, `meta.plugin=.../beckman/
      sage-birdnet2:2.0.0`, `camera=<mic stream>`.
- [ ] TODO: confirm seen-store dedup persists across restarts.

## Changes made OUTSIDE this repo (live node state — not git-tracked) — TODO
- [ ] TODO: image side-loaded into H00F k3s containerd
      (`registry.sagecontinuum.org/beckman/sage-birdnet2:2.0.0`).
- [ ] TODO: consumer pod launched via `pluginctl run` (record exact args).
- [ ] TODO: audio producer stream feeding `/local-cache/<name>/<mic>`.

## Rollback
`sudo pluginctl rm sage-birdnet2-consumer` — removes only this consumer; the
producer (and any co-running consumers) keep running. The image stays imported
for a re-launch.

## Known follow-ups — TODO
- [ ] TODO: geo-filter (`--geo-filter`) tuning once clips carry lat/lon.
- [ ] TODO: min-confidence tuning after first on-node species results.
