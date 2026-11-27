# syntax=docker/dockerfile:1
# Arca (Prototyp): Service (vault.db/visible.db, Cato, lokales OCR) und Claude-Terminal in einem Container.
# Wird in GitHub Actions gebaut und per SSH geladen (wie das Dashboard).
#   docker build -f deploy/arca.Dockerfile -t anonymizer-arca .
# Kein Port nach außen: Dashboard (Service :8100) und Caddy (Terminal :8101) erreichen ihn im Docker-Netz.
# Basis Ubuntu 24.04: Tesseract 5.3.4 und Python 3.12 wie in der Testumgebung. Node kommt aus dem offiziellen Image.
# Optional CA-Bundle für TLS-inspizierende Proxys als Build-Secret (landet nicht im Image):
#   docker build --secret id=ca_bundle,src=/pfad/ca.crt ...
FROM node:22-bookworm-slim AS node

FROM ubuntu:24.04 AS build
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      python3 python3-venv python3-dev make g++ ca-certificates \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
RUN python3 -m venv /venv
COPY packages/core/pyproject.toml packages/core/README.md packages/core/
COPY packages/core/src packages/core/src
COPY arca/pyproject.toml arca/
COPY arca/src arca/src
RUN --mount=type=secret,id=ca_bundle,required=false \
    if [ -f /run/secrets/ca_bundle ]; then export PIP_CERT=/run/secrets/ca_bundle; fi \
 && /venv/bin/pip install --no-cache-dir "./packages/core[ocr]" ./arca
# node-pty wird hier kompiliert (braucht make/g++), das Ergebnis wird kopiert.
COPY arca/terminal/package.json arca/terminal/package-lock.json arca/terminal/
RUN --mount=type=secret,id=ca_bundle,required=false \
    if [ -f /run/secrets/ca_bundle ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/ca_bundle; fi \
 && cd arca/terminal && npm ci --omit=dev --no-audit --no-fund

FROM ubuntu:24.04
ENV NODE_ENV=production PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PATH=/venv/bin:$PATH \
    ANONYMIZER_CATO_PATH=/app/models/cato-1.1 \
    ARCA_DATA_DIR=/data/arca ARCA_CLAUDE_HOME=/data/claude \
    ARCA_PYTHON=/venv/bin/python ARCA_HOST=0.0.0.0 ARCA_TERMINAL_HOST=0.0.0.0 \
    DISABLE_AUTOUPDATER=1
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN --mount=type=secret,id=ca_bundle,required=false \
    if [ -f /run/secrets/ca_bundle ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/ca_bundle; fi \
 && ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      python3 tesseract-ocr tesseract-ocr-deu ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && npm install -g --no-audit --no-fund @anthropic-ai/claude-code@2.1.332 \
 && npm cache clean --force
WORKDIR /app
COPY --from=build /venv /venv
COPY packages/core/models/cato-1.1 models/cato-1.1
RUN test "$(wc -c < models/cato-1.1/ner/model)" -gt 100000 \
 || { echo "models/cato-1.1 enthält nur Git-LFS-Zeiger (git lfs pull)"; exit 1; }
COPY arca/mcp/server.py arca/mcp/server.py
COPY arca/terminal/server.mjs arca/terminal/package.json arca/terminal/
COPY --from=build /app/arca/terminal/node_modules arca/terminal/node_modules
COPY deploy/arca-entrypoint.sh /usr/local/bin/arca-entrypoint
# Nicht-root: Nutzer "ubuntu" (uid 1000) aus dem Basisimage.
RUN mkdir -p /data/arca /data/claude /app/arca/workspace \
 && chown -R ubuntu:ubuntu /data /app/arca/workspace
USER ubuntu
CMD ["arca-entrypoint"]
