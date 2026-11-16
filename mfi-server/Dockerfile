# =============================================================================
# mFi Server add-on: our own controller for Ubiquiti mFi devices, in pure
# Python with the standard library only. It contains no Ubiquiti file: the
# image holds only the mfi_server code.
# =============================================================================
# Digest not measured yet: pin it by hand after a real build
FROM python:3.12-slim

ARG BUILD_VERSION="0.6.0"
ARG BUILD_ARCH="amd64"

ENV PYTHONUNBUFFERED=1

WORKDIR /app
COPY mfi_server /app/mfi_server

# Until the repository has a LICENSE file
LABEL io.hass.version="${BUILD_VERSION}" \
      io.hass.type="app" \
      io.hass.arch="${BUILD_ARCH}" \
      io.hass.name="mFi Server" \
      org.opencontainers.image.title="mFi Server" \
      org.opencontainers.image.description="Our own controller for Ubiquiti mFi devices, in pure Python" \
      org.opencontainers.image.source="https://github.com/oce-projects/oce-mfi-home-assistant" \
      org.opencontainers.image.version="${BUILD_VERSION}" \
      org.opencontainers.image.licenses="NOASSERTION"

EXPOSE 6080/tcp 3478/udp

# Runs as root: the Supervisor /data volume belongs to root (see DOCS.md)
CMD ["python3", "-m", "mfi_server"]
