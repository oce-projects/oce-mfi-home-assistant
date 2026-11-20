# =============================================================================
# mFi Server add-on: our own controller for Ubiquiti mFi devices, in pure
# Python with the standard library only. It contains no Ubiquiti file: the
# image holds only the mfi_server code.
# =============================================================================
# Digest not measured yet: pin it by hand after a real build
FROM python:3.12-slim

ARG BUILD_VERSION="0.32.0"
ARG BUILD_ARCH="amd64"
ARG FW_URL="https://dl.ubnt.com/mfi/2.1.11/firmware/M2M/firmware.bin"
ARG FW_SHA256="7dc6fb4bd67c6352b940d8b65dd0d99325199e8dc4052c20139aaf861fec2a79"

ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends openssh-client curl ca-certificates && rm -rf /var/lib/apt/lists/*

# Firmware archive: downloaded at build time, checked by sha256, read-only.
# The firmware file is never part of the repository.
RUN mkdir -p /opt/mfi-server/firmware/M2M/2.1.11.1309 \
 && curl -fsSL --retry 3 --connect-timeout 30 --max-time 600 -o /opt/mfi-server/firmware/M2M/2.1.11.1309/firmware.bin "${FW_URL}" \
 && echo "${FW_SHA256}  /opt/mfi-server/firmware/M2M/2.1.11.1309/firmware.bin" | sha256sum -c - \
 && chmod -R a-w /opt/mfi-server/firmware

WORKDIR /app
COPY mfi_server /app/mfi_server

LABEL io.hass.version="${BUILD_VERSION}" \
      io.hass.type="app" \
      io.hass.arch="${BUILD_ARCH}" \
      io.hass.name="mFi Server (new)" \
      org.opencontainers.image.title="mFi Server (new)" \
      org.opencontainers.image.description="Our own controller for Ubiquiti mFi devices, in pure Python" \
      org.opencontainers.image.source="https://github.com/oce-projects/oce-mfi-home-assistant" \
      org.opencontainers.image.version="${BUILD_VERSION}" \
      org.opencontainers.image.licenses="Apache-2.0"

EXPOSE 6080/tcp 3478/udp

# Runs as root: the Supervisor /data volume belongs to root (see DOCS.md)
CMD ["python3", "-m", "mfi_server"]
