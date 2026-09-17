FROM python:3.11-slim

LABEL org.opencontainers.image.authors="Arnav <arnavhpd@gmail.com>"
LABEL org.opencontainers.image.title="Automatron"
LABEL org.opencontainers.image.description="Multi-agent decision support for space, quant, e-commerce and real estate"
LABEL org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=7860 \
    RUNTIME_DIR=/tmp/automatron \
    HF_HOME=/app/.cache \
    FASTEMBED_CACHE_PATH=/app/.cache/fastembed

RUN useradd -m -u 1000 appuser
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appuser . .

# Build the modules and pre-download the embedding models so the first request
# does not pay for either.
RUN python scripts/build_notebooks.py \
 && python -c "from fastembed import TextEmbedding, SparseTextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/app/.cache/fastembed'); SparseTextEmbedding('Qdrant/bm25', cache_dir='/app/.cache/fastembed')" \
 && chown -R appuser:appuser /app

USER appuser
EXPOSE 7860
CMD ["python", "app.py"]
