FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    EFDRR_DATA_ROOT=/app \
    EFDRR_RESOURCE_ROOT=/app

WORKDIR /app/backend

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements.txt

COPY VERSION /app/VERSION
COPY backend/app ./app
COPY backend/scripts ./scripts
COPY backend/docs ./docs
COPY backend/config.yaml.example ./config.yaml.example

RUN mkdir -p /app/data /app/downloads

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
