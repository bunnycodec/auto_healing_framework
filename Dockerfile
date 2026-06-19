# AI Auto-Healing Framework — container image
# Build:  docker build -t ai-auto-healer .
# Serve:  docker run -p 8000:8000 --env-file .env ai-auto-healer
# Heal :  docker run --rm -v ${PWD}:/work -w /work --env-file .env ai-auto-healer heal test-results

FROM python:3.12-slim

# Avoid .pyc files and buffer issues in containers
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first for better layer caching
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application
COPY pyproject.toml README.md ./
COPY config.py ./
COPY ai ./ai
COPY app ./app
COPY healer ./healer
COPY scripts ./scripts
COPY docker-entrypoint.sh ./

# Install the package so the `auto-healer` console command is available, and
# make the entrypoint executable.
RUN pip install --no-cache-dir . \
    && chmod +x /app/docker-entrypoint.sh

EXPOSE 8000

# Default: serve the dashboard + API. Override the command to use the CLI, e.g.
#   docker run ... ai-auto-healer heal test-results --auto-pr
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["serve"]
