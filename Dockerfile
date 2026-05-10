FROM python:3.12-slim

# System deps for matplotlib
RUN apt-get update && apt-get install -y --no-install-recommends \
    libfreetype6-dev \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Layer 1: dependencies (cached unless pyproject.toml/uv.lock change)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Layer 2: application code
COPY run.py .
COPY investbrief/ investbrief/
COPY templates/ templates/

# Config and data mounted at runtime
VOLUME /app/config.json
VOLUME /app/.env
VOLUME /app/logs
VOLUME /app/reports

ENTRYPOINT ["uv", "run", "run.py"]
