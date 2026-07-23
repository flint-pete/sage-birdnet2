# Building and Deploying sage-birdnet2

How to build the Docker image, side-load it onto a Sage Thor node, and run it as
a v2 audio cache-consumer.

> **ECR portal build:** sage-birdnet2 is **CPU-only** (BirdNET V2.4 via TFLite —
> no CUDA base, no GPU inference on ARM64; see `RESEARCH.md`). CPU-only plugins
> build fine in the ECR portal, unlike the NVIDIA/CUDA-base family (sage-yolo2 /
> sage-bioclip2), which still crash cross-building `linux/arm64` under QEMU
> (Infra #3, open). The **native aarch64 + k3s side-load** path below is the
> proven dev/test loop and works regardless of the ECR pipeline state.

## Native aarch64 build + k3s side-load (the working dev/test path)

Run from the repo root **on the Thor node** (arm64, no QEMU; needs podman/docker
+ k3s + sudo):

```bash
# 1. build natively (arm64)
sudo podman build -t registry.sagecontinuum.org/beckman/sage-birdnet2:2.0.0 .

# 2. import into k3s containerd (pods use imagePullPolicy=IfNotPresent, so a
#    locally-imported tag is used with no registry pull)
sudo podman save registry.sagecontinuum.org/beckman/sage-birdnet2:2.0.0 \
  | sudo k3s ctr images import -
sudo k3s ctr images ls | grep sage-birdnet2   # verify present
```

## Run as a v2 audio cache-consumer (pluginctl)

`pluginctl run` bypasses the ECR catalog gate — no registration needed for
dev/test. `--selector zone=core` is required whenever you use a `-v` volume
mount. Mount the shared cache host path (`/media/plugin-data/local-cache`, from
`wes-local-cache-manager`) to `/local-cache`:

```bash
# CONSUMER: sage-birdnet2 reads 15-second FLAC clips a producer wrote to the cache
sudo pluginctl run --name sage-birdnet2-consumer \
  --selector zone=core \
  -v /media/plugin-data/local-cache:/local-cache \
  -e WAGGLE_JOB_NAME=hummingcam -e WAGGLE_TASK_NAME=sage-birdnet2 \
  registry.sagecontinuum.org/beckman/sage-birdnet2:2.0.0 -- \
  --source cache --input /local-cache/hummingcam/mic \
  --every 10m --all-unseen --max-frames 0 \
  --model 2.4 --top-k 5 --min-confidence 0.25

# teardown
sudo pluginctl rm sage-birdnet2-consumer
```

Verify the publish reached the cloud via the data API:

```bash
curl -s -X POST https://data.sagecontinuum.org/api/v1/query \
  -H 'Content-Type: application/json' \
  -d '{"start":"-15m","filter":{"vsn":"H00F","name":"env.detection.species"}}'
# record timestamp == clip CAPTURE time (frame-anchored); meta.vsn=H00F,
# meta.plugin=.../beckman/sage-birdnet2:2.0.0
```

## What's verified here vs CI/node-owned

| | Covered by | Notes |
|---|---|---|
| v2 clip selection (stride / all-unseen / newest) | `make test` (offline) | byte-identical vendored `selection.py` |
| seen-store dedup + persistence | `make test` (offline) | byte-identical vendored `seenstore.py` |
| audio `.flac.json` sidecar metadata read | `make test` (offline) | the ONE consumer.py divergence; `tests/test_sidecar_meta.py` |
| real BirdNET V2.4 inference on real audio | **node/CI-owned** | not in the offline suite (no model, no node) |
| end-to-end producer→consumer on H00F | **node-owned** | see `HANDOFF.md` |
