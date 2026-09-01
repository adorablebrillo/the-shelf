FROM python:3.11-slim

# The Shelf — monthly romance page with built-in pipeline + scheduler.
# Build from the the-shelf project root:
#   docker build -t the-shelf -f container/Dockerfile .
# Run (or just use docker-compose.yml for Unraid).

WORKDIR /app
# server.py (at /app) serves /app/dist; the pipeline must write there too.
# Docker COPY flattens the repo's container/dist symlink, so the bake and
# every runtime build use DIST_DIR to target the SAME dir as the server.
ENV DIST_DIR=/app/dist
COPY pipeline/ ./pipeline/
COPY container/server.py ./server.py
COPY data/sequels.json ./data/sequels.json
COPY seed-reads.json ./seed-reads.json
COPY .lavish/assets ./assets

# Bake the default shelf at image build: the newest baseline month becomes the
# current issue (The August 2026 Shelf) so the very first boot shows a real
# shelf — never the September design demo. The mounted data volume shadows data/
# at runtime, but dist/ is baked and served until the first real run.
RUN mkdir -p /app/dist/assets /app/pipeline/data && \
    cp -r /app/assets/. /app/dist/assets/ 2>/dev/null || true && \
    cp /app/pipeline/baseline/month-*.json /app/pipeline/data/ && \
    python3 /app/pipeline/build.py && \
    python3 -m py_compile /app/server.py /app/pipeline/*.py && \
    echo "BUILD OK"

ENV PORT=8787
EXPOSE 8787
VOLUME ["/config"]

# drop the pipeline's runtime data into the mounted volume via symlink-free layout:
# /app/pipeline/data is bind-mounted by the compose file (Unraid appdata).
CMD ["python3", "/app/server.py"]
