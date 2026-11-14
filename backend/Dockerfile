FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HF_HOME=/opt/repopilot-model-cache
WORKDIR /app
COPY pyproject.toml ./
COPY app ./app
ARG INSTALL_LOCAL_EMBEDDINGS=true
ARG RERANKER_ENABLED=false
RUN pip install --no-cache-dir . && \
    if [ "$INSTALL_LOCAL_EMBEDDINGS" = "true" ]; then \
      pip install --no-cache-dir ".[ai]" && \
      python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"; \
    fi && \
    if [ "$RERANKER_ENABLED" = "true" ]; then \
      pip install --no-cache-dir ".[ai]" && \
      python -c "from sentence_transformers import CrossEncoder; CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')"; \
    fi
COPY alembic.ini ./
COPY alembic ./alembic
RUN useradd --create-home --uid 10001 repopilot && chown -R repopilot:repopilot /app /opt/repopilot-model-cache
USER repopilot
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
