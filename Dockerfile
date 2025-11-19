# Dockerfile - robust build for projects requiring C build tools, crypto/rust, image libs and DB clients.
FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Install system deps required for building many Python wheels (aiohttp, cryptography, Pillow, psycopg2, tgcrypto, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    python3-dev \
    libffi-dev \
    libssl-dev \
    libjpeg-dev \
    zlib1g-dev \
    libpq-dev \
    git \
    curl \
    ca-certificates \
    make \
    pkg-config \
    cargo \
    rustc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage build cache
COPY requirements.txt .

# Upgrade packaging tools then install Python deps
RUN pip install --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt

# Copy the rest of the app
COPY . .

# Add a lightweight startup script (see next file)
RUN chmod +x /app/start.sh

EXPOSE 8080

# Use the startup wrapper which launches both the web app and the bot
CMD ["/app/start.sh"]
