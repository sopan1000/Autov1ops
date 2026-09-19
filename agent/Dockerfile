# Build from the REPO ROOT: docker build -f agent/Dockerfile .
# (docker-compose.yml already does this)
FROM python:3.11-slim

WORKDIR /app

COPY agent/requirements.txt ./agent/requirements.txt
RUN pip install --no-cache-dir -r agent/requirements.txt

COPY agent ./agent

ENV PYTHONPATH=/app
ENV MOCK_TOOLS=true
ENV STORE_BACKEND=local
ENV PORT=8000

EXPOSE 8000
CMD ["sh", "-c", "uvicorn agent.main:app --host 0.0.0.0 --port ${PORT}"]
