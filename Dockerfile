FROM node:24-bookworm-slim AS web
WORKDIR /src/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend ./
COPY VERSION /src/VERSION
RUN npm run build

FROM python:3.13-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 EFDRR_RESOURCE_ROOT=/app EFDRR_DATA_ROOT=/app/userdata
WORKDIR /app
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir --require-hashes -r /app/backend/requirements.txt
COPY backend/app /app/backend/app
COPY backend/config.yaml.example /app/backend/config.yaml.example
COPY desktop/server.py desktop/desktop_runtime.py /app/desktop/
COPY VERSION /app/VERSION
COPY --from=web /src/frontend/dist /app/frontend/dist
RUN mkdir -p /app/userdata
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4)" || exit 1
ENTRYPOINT ["python", "/app/desktop/server.py"]
CMD ["--host", "0.0.0.0", "--port", "8000"]
