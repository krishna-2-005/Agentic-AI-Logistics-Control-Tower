# The public dashboard (G-08): Streamlit on the cloud-safe dependency set, nothing else.
FROM python:3.12-slim

# Hugging Face runs Spaces as uid 1000; give it a home and a writable app directory.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH PYTHONUNBUFFERED=1
WORKDIR /home/user/app

COPY --chown=user requirements-cloud.txt .
RUN pip install --no-cache-dir --user -r requirements-cloud.txt

COPY --chown=user . .

EXPOSE 8501
CMD ["streamlit", "run", "src/dashboard/app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
