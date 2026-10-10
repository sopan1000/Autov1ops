# Build from the repo root. `gcloud run deploy --source .` picks this up automatically.
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=8000

WORKDIR /app

COPY agent/requirements.txt ./agent/requirements.txt
RUN pip install --no-cache-dir -r agent/requirements.txt && \
    useradd --create-home --uid 10001 appuser

COPY agent ./agent
COPY dashboard ./dashboard

RUN mkdir -p /app/agent/data && chown -R appuser:appuser /app
USER 10001

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT', '8000'), timeout=3)"

CMD ["sh", "-c", "exec uvicorn agent.main:app --host 0.0.0.0 --port ${PORT} --workers 1"]
