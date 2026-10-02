# Building and deploying sage-birdnet2

The canonical end-to-end recipe is the media-sampler3 install guide
([INSTALLING-MEDIA-SAMPLER3.md](https://github.com/flint-pete/media-sampler3/blob/master/INSTALLING-MEDIA-SAMPLER3.md),
Steps 5 and 6e). This page covers the build itself.

## The image

- **Base:** `python:3.12-slim` plus `ffmpeg`, `libsndfile1` and `libasound2-dev`.
  It is **CPU-only**: BirdNET V2.4 runs on TensorFlow/TFLite, with no CUDA.
- **Models baked in:** the Dockerfile loads BirdNET's acoustic and geo models
  (V2.4) at build time, so the pod needs no network at runtime.
- **ECR:** CPU-only plugins *can* build in the Sage ECR portal; the CUDA plugins
  (yolo2, bioclip2) can't. For consistency, and because it is proven on Thor, the
  stack builds all three the same way: natively on the node, then side-loaded.

## Build and side-load (on the Thor node, repo root)

```bash
scripts/deploy-sideload.sh --dry-run          # show the plan
scripts/deploy-sideload.sh --skip-register    # sudo docker build (arm64) + import into k3s
sudo k3s ctr images ls | grep sage-birdnet2   # registry.sagecontinuum.org/beckman/sage-birdnet2:2.0.0
```

- **Tag:** the name, namespace and version come from `sage.yaml`. The tag is only
  the local image name; nothing is pushed.
- **The script** is identical to sage-yolo2's and sage-bioclip2's.

## Run

See the [README](README.md) ("Run it on a Thor node") for the `sudo pluginctl run`
command and what each flag is for. To remove the consumer:
`sudo pluginctl rm sage-birdnet2-consumer`. The producer and other consumers keep
running.

## What's verified where

| | Covered by | Status |
|---|---|---|
| clip selection (stride / all-unseen / newest) | `make test` | passing (copied `selection.py`) |
| seen-store dedup and persistence | `make test` | passing (copied `seenstore.py`) |
| `.flac.json` sidecar metadata read (media-sampler3 audio contract) | `make test`, `tests/test_sidecar_meta.py` | passing |
| media-sampler3 audio producer writing clips + sidecars | on node (H00F) | **verified** (media-sampler3) |
| real BirdNET V2.4 inference on cached clips, `env.detection.*` reaching Beehive | on node | **pending**: first run still to do |
