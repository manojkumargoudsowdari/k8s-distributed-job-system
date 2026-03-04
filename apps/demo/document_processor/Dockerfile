FROM python:3.12-slim

WORKDIR /app
COPY worker.py /app/worker.py
COPY sample_docs /app/sample_docs

ENTRYPOINT ["python", "/app/worker.py"]
