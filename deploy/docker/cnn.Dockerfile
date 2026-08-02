FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/workspace/backend:/workspace \
    OMP_NUM_THREADS=2 \
    MKL_NUM_THREADS=2

WORKDIR /workspace
COPY pyproject.toml LICENSE ./
COPY backend ./backend
# The default PyPI torch package pulls multi-gigabyte NVIDIA libraries on Linux.
# This project is CPU-only, so use PyTorch's official CPU wheel index explicitly.
RUN pip install --no-cache-dir \
      --index-url https://download.pytorch.org/whl/cpu \
      "torch>=2.2,<3.0"
RUN pip install --no-cache-dir ".[test,cnn]"
COPY training ./training

ENTRYPOINT ["python", "-m"]
