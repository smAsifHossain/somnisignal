FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/backend:/app

WORKDIR /app
COPY pyproject.toml LICENSE ./
COPY backend ./backend
RUN pip install --no-cache-dir ".[test]"
COPY frontend ./frontend
COPY training ./training
COPY tests ./tests
COPY artifacts ./artifacts
RUN python -m training.create_dev_artifact --output-dir ./artifacts

CMD ["pytest", "-q"]
