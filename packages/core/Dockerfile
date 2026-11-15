# syntax=docker/dockerfile:1
# Cato API – self-hosted privacy engine with spaCy models included.
# Build:  docker build -t cato-api packages/core
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first for layer caching.
COPY pyproject.toml README.md ./
COPY src ./src
# Optional CA bundle for TLS-intercepting corporate proxies, passed as a build
# secret (never stored in the image):
#   docker build --secret id=ca_bundle,src=/path/to/ca.crt ...
RUN --mount=type=secret,id=ca_bundle,required=false \
    if [ -f /run/secrets/ca_bundle ]; then \
      export PIP_CERT=/run/secrets/ca_bundle REQUESTS_CA_BUNDLE=/run/secrets/ca_bundle SSL_CERT_FILE=/run/secrets/ca_bundle; \
    fi \
 && pip install . \
 && python -m spacy download de_core_news_lg \
 && python -m spacy download en_core_web_lg

# Unprivileged runtime user; data (vault, policies, traces, accounts, audit log) lives in a volume.
RUN useradd --system --uid 10001 --home /nonexistent --shell /usr/sbin/nologin cato \
 && mkdir -p /data && chown cato /data
USER cato

ENV CATO_HOST=0.0.0.0 \
    CATO_PORT=8080 \
    CATO_VAULT_PATH=/data/vault.json \
    CATO_POLICY_DIR=/data/policies \
    CATO_TRACE_DB=/data/traces.db \
    CATO_ACCOUNTS_DB=/data/accounts.db \
    CATO_AUDIT_DB=/data/audit.db \
    CATO_CONVERSATIONS_DB=/data/conversations.db \
    CATO_PROMPTS_DB=/data/prompts.db

VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4).status == 200 else 1)"

CMD ["cato-api"]
