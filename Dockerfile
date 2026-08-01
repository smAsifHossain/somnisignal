FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app app ./app
COPY --chown=app:app frontend ./frontend
COPY --chown=app:app artifacts ./artifacts

RUN test -f ./artifacts/candidates/rr_cnn.onnx \
    && test -f ./artifacts/candidates/rr_cnn.onnx.data \
    && test -f ./artifacts/candidates/rr_cnn_metadata.json \
    && test -f ./artifacts/candidates/demo_rr_sequences.npz

USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
