FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FASTEMBED_CACHE_PATH=/opt/fastembed_cache

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Cache the compact Chinese embedding model in the image. This avoids a model
# download on the first public query and keeps the Railway runtime deterministic.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2', cache_dir='/opt/fastembed_cache')"

COPY app ./app
COPY frontend ./frontend

EXPOSE 8000

# Railway injects PORT at runtime. Shell expansion is required here so Uvicorn
# listens on the platform-assigned port; local Docker falls back to 8000.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
