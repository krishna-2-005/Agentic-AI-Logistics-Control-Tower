# The public API (WP-04, D-072, D-073). Built from the repository root:
#   docker build -f deploy/api/Dockerfile .
# No JVM: the served model's trees are walked in numpy (`src.ml.gbt_local`), proven identical
# to Spark on every leg, so the container fits a free 512 MB host.
FROM python:3.13-slim

RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 PYTHONPATH=/home/user/app \
    SERVING_ENGINE=numpy LLM_PROVIDER=gemini
WORKDIR /home/user/app

COPY --chown=user deploy/api/requirements-api.txt .
RUN pip install --no-cache-dir --user -r requirements-api.txt

COPY --chown=user src ./src
COPY --chown=user docs ./docs
COPY --chown=user benchmarks/raw ./benchmarks/raw
COPY --chown=user deploy/api/serving ./data/serving
RUN mkdir -p data/traces && mv data/serving/agent_calls.jsonl data/traces/agent_calls.jsonl

# The assistant's index is built into the image, so a cold start does not embed ~1,600
# documents before it can answer. This also caches the ~80 MB ONNX embedding model.
RUN python -m src.common.vectordb --build

EXPOSE 7860
# Hosts set $PORT (Render: 10000); 7860 otherwise.
CMD ["sh", "-c", "exec python -m uvicorn src.api.app:app --host 0.0.0.0 --port ${PORT:-7860} --proxy-headers --forwarded-allow-ips='*'"]
