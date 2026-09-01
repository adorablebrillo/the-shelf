FROM python:3.11-slim

# The Shelf — monthly romance page with built-in pipeline + scheduler.
# Build from the the-shelf project root:
#   docker build -t the-shelf -f container/Dockerfile .
# Run (or just use docker-compose.yml for Unraid).

WORKDIR /app
COPY pipeline/ ./pipeline/
COPY container/server.py ./server.py
COPY .lavish/assets ./assets

RUN mkdir -p /app/dist/assets && \
    cp -r /app/assets/. /app/dist/assets/ 2>/dev/null || true && \
    python3 -m py_compile /app/server.py /app/pipeline/*.py && \
    echo "BUILD OK"

ENV PORT=8787
EXPOSE 8787
VOLUME ["/config"]

# drop the pipeline's runtime data into the mounted volume via symlink-free layout:
# /app/pipeline/data is bind-mounted by the compose file (Unraid appdata).
CMD ["python3", "/app/server.py"]
