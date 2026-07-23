# Wildlife Audio Classification — State of the Art (June 2026)

Research survey of models for real-time wildlife audio classification
on Sage edge nodes (NVIDIA Thor, Xavier NX). Conducted as groundwork
for modernizing the bird-diversity plugin, which currently uses the
deprecated BirdNET Lite (v0.2.5, TFLite, ~56 MB, 6,000 species).


## 1. BirdNET V2.4 — Direct Replacement for BirdNET Lite

The original plugin used BirdNET Lite, which has been deprecated
and replaced by BirdNET-Analyzer.

| Feature | BirdNET Lite (old) | BirdNET V2.4 (current) |
|---------|--------------------|------------------------|
| Species | ~6,000 birds | 6,522 classes (birds + frogs + insects) |
| Model | TFLite only, 56 MB | TFLite (FP32/FP16/INT8) + ProtoBuf (GPU) |
| Architecture | CNN | EfficientNetB0-like, 0.826 GFLOPs |
| Audio | 3s chunks | 3s chunks at 48 kHz, dual mel-spectrograms |
| Geo-filter | None | eBird lat/lon/week species range model |
| Python API | Manual TFLite calls | `pip install birdnet` (auto model download) |
| Status | Deprecated | Active development |

### Key Details

- **Latest release**: V2.4.0 (November 7, 2025)
- **Core library**: `pip install birdnet` (v0.2.16, lightweight inference only)
- **Full suite**: `pip install birdnet-analyzer` (v2.4.0, adds GUI, training, eval)
- **Model formats and sizes**:
  - ProtoBuf (SavedModel): 124.5 MB — CPU + GPU (FP32)
  - TFLite FP32: 76.8 MB — CPU only
  - TFLite FP16: 53.0 MB — CPU only
  - TFLite INT8: 45.9 MB — CPU only, fastest on edge
- **Audio pipeline**: 48 kHz sample rate (auto-resamples), two mel-spectrograms
  (0–3 kHz and 500 Hz–15 kHz), 96×511 pixels each per 3-second chunk
- **1024-dimensional embeddings** — useful for downstream classification
- **License**: MIT (source code), CC BY-NC-SA 4.0 (models). All educational
  and research purposes are considered non-commercial.
- **GitHub**: https://github.com/birdnet-team/BirdNET-Analyzer
- **Documentation**: https://birdnet-team.github.io/BirdNET-Analyzer/
- **Model weights**: https://zenodo.org/records/15050749
- **PyPI (core)**: https://pypi.org/project/birdnet/
- **PyPI (full)**: https://pypi.org/project/birdnet-analyzer/

### Non-Avian Species in BirdNET V2.4

BirdNET V2.4 is not birds-only. It includes approximately:

- ~26 frog species (American Bullfrog, Spring Peeper, Pacific Chorus Frog, etc.)
- ~15 toad/spadefoot species (American Toad, Fowler's Toad, etc.)
- ~14 katydid species (True Katydid, bush katydids, meadow katydids)
- ~4 conehead species (Robust Conehead, Sword-bearing Conehead, etc.)
- ~20+ cricket species (Fall Field Cricket, Snowy Tree Cricket, etc.)
- 11 "non-event" classes for noise rejection

Full species lists:
- Avian: https://www.ravensoundsoftware.com/wp-content/uploads/2024/08/Avian-Species-List-BirdNET-V2.4.pdf
- Non-avian: https://www.ravensoundsoftware.com/wp-content/uploads/2024/08/Non-Avian-Species-List-BirdNET-V2.4.pdf

### Python API Example

```python
import birdnet

# Load model (auto-downloads ~125 MB on first use)
model = birdnet.load("acoustic", "2.4", "tf")

# Predict species in audio file
predictions = model.predict(
    "recording.wav",
    min_confidence=0.25,
    top_k=5,
)

# Results as dataframe
df = predictions.to_dataframe()
# Columns: input, start_time, end_time, species_name, confidence

# Species filtering by location + time
geo_model = birdnet.load("geo", "2.4", "tf")
species = geo_model.predict(41.88, -87.62, week=22, min_confidence=0.03)
species_set = species.to_set()

predictions = model.predict(
    "recording.wav",
    custom_species_list=species_set,
    min_confidence=0.25,
)
```

### Real-Time / Streaming

The primary API is file-based, but array-based inference is supported:

```python
with model.encode_session(batch_size=1) as session:
    # 3 seconds at 48 kHz = 144,000 samples
    audio_chunk = np.array(...)  # shape: (144000,)
    result = session.run_arrays([(audio_chunk, 48000)])
    embeddings = result.embeddings  # shape: (1, 1, 1024)
```

BirdNET-Pi demonstrates 24/7 real-time on Raspberry Pi 4 (ARM64, CPU-only).

### ARM64 / Edge Deployment

| Platform | ProtoBuf-CPU | ProtoBuf-GPU | TFLite | LiteRT |
|----------|-------------|-------------|--------|--------|
| Linux ARM64 | Python 3.11–3.13 | NOT supported | Python 3.11–3.13 | Python 3.11–3.12 |
| Linux x86_64 | Python 3.11–3.13 | Python 3.11–3.13 | Python 3.11–3.13 | Python 3.11–3.12 |

**Important**: GPU inference on ARM64 is not supported in the standard
`birdnet` package. For NVIDIA Thor (Blackwell GPU on ARM64), options are:
1. Use TFLite CPU inference (proven fast enough on Raspberry Pi, will be
   excellent on Thor's ARM64 cores)
2. Build TensorFlow from source with ARM64 CUDA support
3. Use NVIDIA's JetPack/L4T TensorFlow builds

### Speed Benchmarks

| Device | Throughput/sec | 1 hr audio |
|--------|---------------|------------|
| Intel i7 8th Gen (4 cores) | 50 s | 72 s |
| Ryzen 7 3800X (8 cores) | 7 min | 8.5 s |
| Nvidia Titan RTX (24 GB) | 41 min | 1.5 s |
| Raspberry Pi 4 (ARM64, CPU) | Real-time | Real-time |

At 0.826 GFLOPs per 3-second chunk, even CPU inference on Thor's ARM64
cores (far more capable than a Raspberry Pi) will be more than adequate
for real-time audio classification.


## 2. Google Perch 2.0 — Broader Taxonomy, Better License

Perch is Google DeepMind's bioacoustics foundation model. It produces
1536-dimensional audio embeddings for downstream classification.

| Feature | BirdNET V2.4 | Perch 2.0 |
|---------|-------------|-----------|
| Species | ~6,500 | ~15,000 (birds, frogs, insects, mammals) |
| Architecture | EfficientNetB0 | EfficientNet-B3 |
| Parameters | ~30M | ~12M (embeddings) + ~91M (classifier) |
| Embedding | 1024-dim | 1536-dim |
| Primary use | Direct classifier | Foundation model + agile classifiers |
| License | CC-BY-NC-SA 4.0 | **Apache 2.0** (fully permissive) |
| Edge formats | TFLite (native) | TFLite, ONNX (via BirdNET-Go) |
| Strengths | Mature, lightweight, battle-tested | Broader taxonomy, few-shot learning |

### Key Advantages

- **Apache 2.0 license** — no non-commercial restriction (unlike BirdNET)
- **"Agile modeling"** — train a linear classifier on top of embeddings
  with just a handful of labeled examples for any new species
- **Broader taxonomy** — insects, mammals, frogs beyond what BirdNET covers
- **Already running at the edge** — integrated into BirdNET-Go on ARM64

### Links

- GitHub: https://github.com/google-research/perch
- Kaggle: https://www.kaggle.com/models/google/bird-vocalization-classifier
- HuggingFace: https://huggingface.co/cgeorgiaw/Perch


## 3. Bat Detection

### BatDetect2

CNN-based bat echolocation detection and species classification.

- **Accuracy**: F1-score 0.9578, 97.5% on 8 species
- **Architecture**: CNN object detection on spectrograms (YOLO-style bounding boxes)
- **Size**: Lightweight (few MB)
- **License**: CC-BY-NC-4.0
- **Edge**: Proven on Raspberry Pi 4B, NVIDIA Jetson Nano, Google Coral
- **GitHub**: https://github.com/macaodha/batdetect2
- **Edge package**: https://acoupi.github.io/acoupi_batdetect2/

### BattyBirdNET-Analyzer

BirdNET cross-trained for bat echolocation. 11 regional classifiers
(Europe, North America, UK, East Asia, Africa, Middle East, etc.).

- **Architecture**: TFLite (based on BirdNET), Raspberry Pi compatible
- **Sampling**: 256 kHz / 384 kHz for ultrasonic bat calls
- **License**: CC-BY-NC-SA
- **Already in BirdNET-Go** as a model option
- **GitHub**: https://github.com/rdz-oss/BattyBirdNET-Analyzer


## 4. Amphibian / Frog Detection

### AnuraSet

Dataset + baseline CNN for 42 Neotropical frog/toad species.

- **Architecture**: PyTorch CNN on 3-second mel spectrograms
- **Dataset**: 93,000 samples, 27 hours expert annotations
- **License**: MIT (code), CC-BY 4.0 (dataset)
- **Edge**: Needs ONNX/TFLite conversion (PyTorch native)
- **GitHub**: https://github.com/soundclim/anuraset
- **HuggingFace**: https://huggingface.co/AnuraSet

Note: BirdNET V2.4 already includes ~26 frog + ~15 toad species natively,
which may be sufficient for North American deployment without a separate
frog model.


## 5. General Environmental Audio

### YAMNet (Google)

General-purpose audio event classification — 521 classes including
animals, environment, human sounds, machinery.

- **Architecture**: MobileNet_v1, depthwise-separable convolution
- **Size**: 3.7 MB (designed for mobile)
- **License**: Apache 2.0
- **Edge**: Runs on anything (TFLite available)
- **Use case**: Pre-filter to detect "interesting" audio events before
  running species-specific classifiers. Could gate BirdNET inference
  to save compute — only classify when YAMNet detects animal sounds.
- **GitHub**: https://github.com/tensorflow/models/tree/master/research/audioset/yamnet

### NatureLM-audio (Earth Species Project)

Bioacoustic foundation model with natural language prompting.

- **Architecture**: BEATs audio encoder + Llama 3.1 8B Instruct
- **Size**: 0.7B parameters (~2-3 GB VRAM)
- **What it does**: Zero-shot species classification, call type
  identification, life-stage detection, audio captioning — all via
  text prompts. No task-specific fine-tuning needed.
- **License**: CC-BY-NC-SA 4.0
- **Edge**: Thor only (128 GB unified memory). Too large for Xavier NX.
- **HuggingFace**: https://huggingface.co/EarthSpeciesProject/NatureLM-audio
- **GitHub**: https://github.com/earthspecies/NatureLM-audio

### CLAP (Contrastive Language-Audio Pretraining)

Zero-shot audio classification using text descriptions.

- **Architecture**: HTSAT audio encoder + RoBERTa text encoder, ~200M params
- **License**: Apache 2.0
- **Edge**: Thor only (too large for Xavier NX)
- **Use case**: Classify any sound described in text without training
- **HuggingFace**: https://huggingface.co/laion/clap-htsat-fused


## 6. Multi-Model Platform: BirdNET-Go

BirdNET-Go runs multiple models in parallel with cross-model consensus:

- BirdNET V2.4 (TFLite) — birds
- Perch 2.0 (ONNX) — birds + frogs + insects + mammals
- BattyBirdNET (TFLite) — bats
- Custom TFLite models

Written in Go, pre-built Docker images for linux/arm64 and linux/amd64.
Real-time audio analysis with web dashboard.

- **GitHub**: https://github.com/tphakala/birdnet-go
- **License**: CC-BY-NC-SA 4.0


## Edge Deployment Summary

| Model | Thor (Blackwell, 128 GB) | Xavier NX | Raspberry Pi 5 | Size |
|-------|-------------------------|-----------|----------------|------|
| BirdNET V2.4 (TFLite INT8) | Excellent (CPU) | Excellent (CPU) | Yes | 46 MB |
| Perch 2.0 (ONNX) | Excellent | Good | Slow | ~103M params |
| BatDetect2 | Excellent | Good | Yes | few MB |
| BattyBirdNET (TFLite) | Excellent | Excellent | Yes | TFLite |
| YAMNet (TFLite) | Excellent | Excellent | Yes | 3.7 MB |
| AnuraSet (PyTorch→ONNX) | Excellent | Good | Needs conversion | ~CNN |
| NatureLM-audio (0.7B) | Good (GPU) | Too large | No | ~2-3 GB |
| CLAP (~200M) | Good (GPU) | Tight | No | ~800 MB |


## Recommendation for bird-diversity Plugin

**Primary model: BirdNET V2.4** via `pip install birdnet`

Rationale:
1. Drop-in replacement for the existing BirdNET Lite code
2. Already covers birds + frogs + insects (no separate models needed)
3. 3-second audio chunks match the existing plugin architecture exactly
4. Clean Python API with auto model download
5. eBird geo-filtering reduces false positives with zero extra work
6. TFLite INT8 (46 MB) runs real-time on Raspberry Pi — will be trivial
   on Thor's ARM64 cores
7. Proven ecosystem (BirdNET-Pi, BirdNET-Go, birdnetlib)

**GPU-on-ARM64 limitation**: The `birdnet` package doesn't support GPU
on ARM64. CPU-only via TFLite is the path for Thor and Xavier NX. Given
that it runs real-time on a Raspberry Pi 4, CPU inference on Thor's much
more powerful ARM cores should be more than sufficient.

**Future extensions** (after initial deployment):
- Add Perch 2.0 as a second model for broader taxonomy (Apache 2.0 license)
- Add BattyBirdNET or BatDetect2 if bat monitoring is desired
- Explore NatureLM-audio on Thor for zero-shot wildlife sound captioning
- Use YAMNet as a pre-filter to gate expensive inference

**Dependencies for the new plugin**:
- `birdnet>=0.2.16` (core inference library)
- `librosa>=0.11` (audio loading)
- `numpy`, `soundfile`
- System: `ffmpeg`, `libsndfile1`
- Audio input: pywaggle `Microphone` API or ALSA/PulseAudio recording


## References

- BirdNET project: https://birdnet.cornell.edu
- BirdNET-Analyzer docs: https://birdnet-team.github.io/BirdNET-Analyzer/
- BirdNET-Pi (edge reference): https://github.com/Nachtzuster/BirdNET-Pi
- BirdNET-Go (multi-model): https://github.com/tphakala/birdnet-go
- Google Perch: https://github.com/google-research/perch
- BatDetect2: https://github.com/macaodha/batdetect2
- BattyBirdNET: https://github.com/rdz-oss/BattyBirdNET-Analyzer
- AnuraSet: https://github.com/soundclim/anuraset
- YAMNet: https://github.com/tensorflow/models/tree/master/research/audioset/yamnet
- NatureLM-audio: https://huggingface.co/EarthSpeciesProject/NatureLM-audio
- OpenSoundscape: https://github.com/kitzeslab/opensoundscape
- Original plugin: https://github.com/dariodematties/BirdNET_Lite_Plugin
