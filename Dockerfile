# AI-CEO platform image: API + dashboard + headless browser for QA.
# Not verified in this environment (Docker was not installed); see README "Docker".

# ---- dashboard build ----
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---- runtime (Playwright image ships Chromium + system deps) ----
FROM mcr.microsoft.com/playwright/python:v1.63.0-noble
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    AICEO_HOST=0.0.0.0 AICEO_DATA_DIR=/data AICEO_BROWSER_CHANNEL=chromium \
    AICEO_OLLAMA_HOST=http://host.docker.internal:11434
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends git nodejs && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY ai_ceo/ ai_ceo/
COPY main.py pyproject.toml ./
COPY --from=web /web/dist web/dist
RUN useradd --create-home aiceo && mkdir -p /data && chown aiceo /data
USER aiceo
EXPOSE 8000
VOLUME ["/data"]
CMD ["python", "main.py", "serve", "--no-browser"]
