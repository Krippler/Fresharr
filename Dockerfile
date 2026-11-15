FROM python:3.12-slim

LABEL org.opencontainers.image.title="Fresharr" \
      org.opencontainers.image.description="Discovers new and highly rated movies & TV shows and adds them to Radarr/Sonarr" \
      org.opencontainers.image.source="https://github.com/krippler/fresharr" \
      org.opencontainers.image.licenses="GPL-3.0"

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    CONFIG_DIR=/config \
    PUID=99 \
    PGID=100

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY fresharr ./fresharr
RUN pip install --no-cache-dir .

# Set by the publish workflow: the version on a release, the commit
# (git describe) otherwise. Shown in the web interface and startup log.
ARG FRESHARR_BUILD=
ENV FRESHARR_BUILD=${FRESHARR_BUILD}

# Starts as root only to give /config to PUID:PGID (Unraid's nobody:users by
# default; Docker creates a missing appdata folder owned by root), then drops
# to that user before doing anything else. See fresharr/privileges.py.
RUN mkdir -p /config && chown 99:100 /config
VOLUME /config
EXPOSE 8383

ENTRYPOINT ["fresharr"]
