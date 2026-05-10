FROM python:3.12-slim

# System deps for matplotlib
RUN apt-get update && apt-get install -y --no-install-recommends \
    libfreetype6-dev \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install uv
RUN pip install --no-cache-dir uv

# Copy dependency declaration first (layer caching)
COPY pyproject.toml uv.lock .

# Copy application code
COPY run.py .
COPY investbrief/ investbrief/
COPY templates/ templates/

# Install dependencies
RUN uv sync

# Config and data mounted at runtime
VOLUME /app/config.json
VOLUME /app/.env
VOLUME /app/logs
VOLUME /app/reports

ENTRYPOINT ["uv", "run", "run.py"]
