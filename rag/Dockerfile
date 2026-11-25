# The desk service as a container. Build and run from the rag folder:
#   docker build -t arcaence-desk .
# No secret is baked in: the three settings below are given when the container starts.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    FASTEMBED_CACHE_PATH=/opt/fastembed-cache \
    PATH="/app/.venv/bin:$PATH"

RUN pip install --no-cache-dir uv==0.13.10

WORKDIR /app

# libraries first, so a code change does not reinstall them
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# the search model is downloaded now, not at the first customer request
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5')"

COPY . .

# the service runs as a user with no shell and no home, never as root
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin desk \
    && chown -R desk /opt/fastembed-cache
USER desk

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status == 200 else 1)"

# ANTHROPIC_API_KEY, DATABASE_URL (the desk_service login) and SERVICE_API_KEYS come from the environment
CMD ["uvicorn", "service:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]