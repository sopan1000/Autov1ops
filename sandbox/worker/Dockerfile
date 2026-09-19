FROM python:3.11-slim
WORKDIR /app
COPY worker.py .
ENV IMAGE_TAG=worker:v2.2
CMD ["python", "worker.py"]
