FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./
RUN mkdir -p /app/output

# Railway provides PORT at runtime. The development deployment stays in
# ENVIRONMENT=development and requires explicit review credentials.
CMD ["sh", "-c", "uvicorn webhook.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
