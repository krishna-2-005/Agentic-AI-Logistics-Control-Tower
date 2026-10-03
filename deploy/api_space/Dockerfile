# The public API (WP-04, D-072): FastAPI + the v2 model on Spark, nothing else.
# Built by Hugging Face from the folder `scripts/deploy_api_space.py` stages.
FROM eclipse-temurin:17-jre AS java

FROM python:3.13-slim
# Spark needs a JVM. Copied from the official Temurin image rather than installed from the
# distro, so the Java version does not move when the base image's Debian release does.
COPY --from=java /opt/java/openjdk /opt/java/openjdk
ENV JAVA_HOME=/opt/java/openjdk PATH=/opt/java/openjdk/bin:$PATH

# Hugging Face runs Spaces as uid 1000; give it a home and a writable app directory.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:/opt/java/openjdk/bin:$PATH \
    PYTHONUNBUFFERED=1 PYTHONPATH=/home/user/app \
    SPARK_DRIVER_MEMORY=2g LLM_PROVIDER=gemini
WORKDIR /home/user/app

COPY --chown=user requirements-api.txt .
RUN pip install --no-cache-dir --user -r requirements-api.txt

COPY --chown=user . .

# The assistant's index is built into the image, so a cold start does not embed 1,100
# documents before it can answer (WP-04). The first build downloads the ~80 MB ONNX
# embedding model chromadb uses; it is cached in the image with the index.
RUN python -m src.common.vectordb --build

EXPOSE 7860
CMD ["python", "-m", "uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "7860", "--proxy-headers"]
