FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/workspace/backend:/workspace

WORKDIR /workspace
COPY pyproject.toml LICENSE ./
COPY backend ./backend
RUN pip install --no-cache-dir ".[training]"
COPY training ./training

ENTRYPOINT ["python", "-m"]
