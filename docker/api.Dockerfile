# The API: FastAPI + the parsing and retrieval pipeline.
#
# Two stages, for one reason worth stating: the parsers pull in pdfplumber ->
# pdfminer.six -> cryptography, and lxml, all of which will fall back to
# compiling from source if a wheel is missing for the platform. Giving the
# builder a toolchain means that fallback works; leaving the toolchain out of
# the runtime keeps ~250 MB of compilers out of the shipped image.

# ---------------------------------------------------------------- builder ---
FROM python:3.12-slim-bookworm AS builder

# Only needed if a dependency has no wheel for this platform. On amd64 and
# arm64 every one of them does, and this layer is then pure cost -- it is kept
# so a build on a less common platform degrades to slow rather than broken.
RUN apt-get update \
 && apt-get install --no-install-recommends -y build-essential \
 && rm -rf /var/lib/apt/lists/*

# A virtualenv rather than the system site-packages, so the runtime stage can
# take the whole dependency tree as one directory.
ENV VIRTUAL_ENV=/opt/venv
RUN python -m venv "$VIRTUAL_ENV"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Dependencies before source: the requirements file changes rarely and the
# source changes constantly, so this layer survives almost every rebuild.
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# ---------------------------------------------------------------- runtime ---
FROM python:3.12-slim-bookworm AS runtime

ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # Bind to every interface. The application default is 127.0.0.1, which is
    # correct on a laptop and unreachable inside a container.
    API_HOST=0.0.0.0 \
    API_PORT=8000

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY pyproject.toml README.md ./

# Non-root. The two writable paths are created here and owned by the app user
# so a *named volume* mounts cleanly; a bind mount from a Linux host carries
# the host's ownership instead, which is what the `user:` override in
# docker-compose.yml is for.
RUN useradd --create-home --uid 10001 app \
 && mkdir -p /app/storage /app/filings \
 && chown -R app:app /app
USER app

EXPOSE 8000

# No curl in a slim image, and adding it for this would be 10 MB to call one
# URL the interpreter can already reach.
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4).status == 200 else 1)"]

# uvicorn directly rather than scripts/serve_api.py: one less indirection, and
# worker/host/port belong to the deployment rather than to the script.
CMD ["uvicorn", "analyst_copilot.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
