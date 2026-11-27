FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
# Exactly the versions in uv.lock, hash-verified, nothing else (--no-deps):
# what CI tests and audits is what ships. Regenerate after changing deps:
#   uv export --frozen --no-dev --no-emit-project --format requirements-txt -o api/requirements.lock
COPY requirements.lock .
RUN pip install --no-deps --require-hashes -r requirements.lock

COPY . .

# Run as an unprivileged user with no shell and no home. The image needs no
# writable paths (bytecode writing is off), so it also runs with a read-only
# root filesystem (the Kubernetes manifests set readOnlyRootFilesystem).
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin erid
USER 10001

EXPOSE 8000

# One uvicorn process per container: scale with replicas, not workers (each
# worker would hold its own DB pool and LISTEN connection, and Prometheus
# metrics are per process). On SIGTERM uvicorn stops accepting, closes
# WebSockets with 1012 so clients reconnect to another replica with ?since=,
# and waits up to 25s for in-flight requests. Proxy headers are honoured only
# from FORWARDED_ALLOW_IPS (default 127.0.0.1); deployments behind a proxy set it.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--timeout-graceful-shutdown", "25", "--no-server-header"]
