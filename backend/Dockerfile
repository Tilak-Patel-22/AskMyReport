# AskMyReport API: FastAPI + retrieval models on CPU.
# Data (backend/data) and the Chroma index (backend/vectorstore) are not baked in: docker-compose mounts them.
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    HF_HOME=/root/.cache/huggingface

# CPU-only torch first: the default Linux wheel pulls ~2.5 GB of CUDA libraries this image never uses
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
EXPOSE 8000
CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000"]
