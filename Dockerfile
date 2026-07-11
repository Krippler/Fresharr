FROM python:3.12-slim

LABEL org.opencontainers.image.title="Fresharr" \
      org.opencontainers.image.description="Discovers new and highly rated movies & TV shows and adds them to Radarr/Sonarr" \
      org.opencontainers.image.source="https://github.com/krippler/fresharr" \
      org.opencontainers.image.licenses="GPL-3.0"

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    CONFIG_DIR=/config

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY fresharr ./fresharr
RUN pip install --no-cache-dir .

# Unraid convention: run as nobody:users (99:100) so files in /config
# stay manageable from the array.
RUN mkdir -p /config && chown 99:100 /config
VOLUME /config
EXPOSE 8383
USER 99:100

ENTRYPOINT ["fresharr"]
