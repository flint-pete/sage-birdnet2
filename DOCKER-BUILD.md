# Building and deploying sage-birdnet2

The canonical end-to-end recipe is the media-sampler3 install guide
([INSTALLING-MEDIA-SAMPLER3.md](https://github.com/flint-pete/media-sampler3/blob/master/INSTALLING-MEDIA-SAMPLER3.md):
build in Step 5, run and test in Step 6). This page covers the build itself.

## The image

- **Base:** `python:3.12-slim` plus `ffmpeg`, `libsndfile1` and `libasound2-dev`.
  It is **CPU-only**: BirdNET V2.4 runs on TensorFlow, with no CUDA, so the Thor
  GPU question doesn't arise.
- **BirdNET is pinned to `birdnet==0.2.16`,** the version `app.py`'s calls were
  written against. birdnet 1.x made TensorFlow optional. With an unpinned
  `birdnet>=0.2.16`, pip installed 1.1.1 without TensorFlow, and the build failed
  at the model-preload step ("Backend 'tf' ... requires TensorFlow"; H039, Oct
  2026). 0.2.16 depends on TensorFlow, so pip installs it.
- **All other dependencies are pinned too** (`requirements.txt`), to the versions
  that built and ran on H039. To upgrade, change a pin, rebuild, and re-run the
  seeded test.
- **Models baked in:** the Dockerfile loads BirdNET's acoustic and geo models
  (V2.4) at build time, so the pod needs no network at runtime.
- **ECR:** the Sage ECR portal can build this image. The stack builds all three
  consumers the same way, natively on the node and then side-loaded, because that
  is the verified path and the images aren't published yet.

## Build and side-load (on the Thor node, repo root)

```bash
scripts/deploy-sideload.sh --skip-register    # arm64 build + import into k3s (a few minutes)
sudo k3s ctr images ls | grep sage-birdnet2   # registry.sagecontinuum.org/beckman/sage-birdnet2:2.0.1
```

- **Tag:** the name, namespace and version come from `sage.yaml`. The tag is only
  the local image name; nothing is pushed. `--dry-run` prints the plan.
- **The script** is identical to sage-yolo2's and sage-bioclip2's.

## Run

See the [README](README.md) ("Run it on a Thor node") for the
`sudo pluginctl-nodeinfo run` command and what each flag is for. To remove the
consumer: `sudo pluginctl rm sage-birdnet2-consumer`. The producer and other
consumers keep running.

**Memory.** Measured on H039: 0.53 GB peak (cgroup `memory.peak`) while loading
both models and classifying a 15 s clip, 0.31 GB steady. The command sets
`limit.memory=2Gi,request.memory=1Gi`.

## What's verified where

| | Covered by | Status |
|---|---|---|
| clip selection (stride / all-unseen / newest) | `make test` | passing (copied `selection.py`) |
| seen-store dedup and persistence | `make test` | passing (copied `seenstore.py`) |
| `.flac.json` sidecar metadata read (media-sampler3 audio contract) | `make test`, `tests/test_sidecar_meta.py` | passing |
| arm64 image build on a Thor | `deploy-sideload.sh` on H039 | **verified** (Oct 2026, after the birdnet pin) |
| real BirdNET V2.4 on a cached clip, node GPS for the eBird filter, `env.detection.*` in Beehive | install guide seeded-audio test, H039 | **verified**: bluebird clip, 3 × *Sialia sialis* (0.89–0.9996), geo filter from node GPS (131 species), summary + biophony records with lat/lon |
| media-sampler3 audio producer writing clips + sidecars | on node (H00F) | **verified** (media-sampler3) |
| live camera mic → producer → birdnet2 | on node | **pending** (needs a camera) |
