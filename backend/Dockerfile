# BOE Analytics API — uvicorn on 8000.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first: pyproject changes far less often than source, so a code
# push reuses this layer instead of reinstalling the whole tree.
COPY pyproject.toml ./
COPY finclone/__init__.py ./finclone/
RUN pip install --no-cache-dir .

COPY finclone ./finclone
RUN pip install --no-cache-dir --no-deps .

# Unprivileged: the API takes untrusted input (tickers, Scout queries, Stripe
# webhooks) and has no reason to be able to write its own code.
RUN useradd --system --uid 10001 --create-home boe && chown -R boe /app
USER boe

EXPOSE 8000

# httpx is already a dependency, so the check costs no extra image weight —
# curl is not installed in slim and does not need to be.
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import sys,httpx; sys.exit(0 if httpx.get('http://127.0.0.1:8000/health',timeout=4).status_code==200 else 1)"

CMD ["uvicorn", "finclone.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
