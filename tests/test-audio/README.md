# Test audio

| File | What it is | Source and licence |
|------|-----------|--------------------|
| `eastern-bluebird-XC179669.flac` | 15 s, 16 kHz mono FLAC (the camera-mic format) of an Eastern Bluebird (*Sialia sialis*) singing and calling. Used by the install guide's seeded-audio test (Step 6b). | First 15 s of xeno-canto [XC179669](https://xeno-canto.org/179669) by **Jonathon Jongsma**, Murphy-Hanrehan Park Reserve, Minnesota, 2014-05-25. Obtained via Wikimedia Commons under **CC BY-SA**; trimmed and resampled (ffmpeg `-t 15 -ac 1 -ar 16000`). This file keeps its own CC BY-SA licence, separate from the repository licence. |

The same recording (full length, MP3) is in the original
[birdnet](https://github.com/flint-pete/birdnet) plugin's `tests/audio/`, where
BirdNET V2.4 rates it Eastern Bluebird at 99.99%.
