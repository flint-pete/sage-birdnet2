FROM python:3.12-slim

# System deps for audio processing
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        libsndfile1 \
        libasound2-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps (birdnet downloads model on first use)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download BirdNET models at build time so container starts fast
RUN python3 -c "\
import birdnet; \
birdnet.load('acoustic', '2.4', 'tf'); \
birdnet.load('geo', '2.4', 'tf'); \
print('Models downloaded successfully')"

COPY save_match.py .
COPY consumer.py .
COPY selection.py .
COPY seenstore.py .
COPY node_info.py .
COPY app.py .

ENTRYPOINT ["python3", "app.py"]
