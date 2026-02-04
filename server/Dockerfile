ARG PYTHON_VERSION=3.13-slim
FROM python:${PYTHON_VERSION}

LABEL maintainer="Komal Thareja <komal.thareja@gmail.com>"

# System deps (keep minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    vim-tiny cron iputils-ping ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

# Python stdout/stderr unbuffered
ENV PYTHONUNBUFFERED=1

# App config (override at runtime)
ENV REPORTS_API_BASE_URL="https://reports.fabric-testbed.net/reports" \
    PORT=5000

# Create app user (non-root)
RUN useradd -m -u 10001 appuser

WORKDIR /app

# Leverage layer caching
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir uv \
 && uv pip install --system --no-cache -r /app/requirements.txt

# App code (package + resources)
COPY . /app/server

# Use an unprivileged user
USER appuser

# Expose the configurable port
EXPOSE ${PORT}

# Healthcheck uses a simple TCP probe so we don't depend on a specific HTTP route
HEALTHCHECK --interval=30s --timeout=3s --retries=5 CMD bash -c "exec 3<>/dev/tcp/127.0.0.1/${PORT} && exit 0 || exit 1"

# Start the FastMCP HTTP server (the module reads PORT env)
CMD ["python", "-m", "server"]
