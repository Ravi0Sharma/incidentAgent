FROM python:3.11.15-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY requirements.lock ./
RUN python -m pip install --upgrade pip==26.2.1 setuptools==84.0.0 && \
    python -m pip install --require-hashes --prefix=/install -r requirements.lock

FROM python:3.11.15-slim-bookworm AS runtime

ARG BUILD_REVISION=unknown
LABEL org.opencontainers.image.title="incident-agent" \
      org.opencontainers.image.revision="${BUILD_REVISION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH=/home/incident/.local/bin:${PATH}

RUN groupadd --gid 10001 incident && \
    useradd --uid 10001 --gid incident --create-home --shell /usr/sbin/nologin incident

COPY --from=builder /install /usr/local
WORKDIR /app
COPY --chown=incident:incident . ./
RUN mkdir -p /app/output && chown incident:incident /app/output

USER 10001:10001
EXPOSE 8000
CMD ["python", "scripts/start_api.py"]
