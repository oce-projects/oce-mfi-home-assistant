# =============================================================================
# Home Assistant app (add-on) "Ubiquiti mFi Controller" - Dockerfile
# Full history in CHANGELOG.md
#
# License: no Ubiquiti file is stored in this repository. The package
# mFi.unix.zip is downloaded from dl.ubnt.com at build time, on the machine of
# the person who installs the app, and checked against a pinned sha256.
#
# File changelog:
#   0.1.0 - 2026-11-15 - first version: two stages (download + run),
#           Debian 8 jessie with OpenJDK 7 and MongoDB 2.4, data in /data.
#   0.1.2 - 2026-11-15 - BUILD_VERSION default aligned with config.yaml; version line removed from the header.
#   0.1.3 - 2026-11-15 - BUILD_VERSION 0.1.3 (security notes in DOCS.md).
#   0.1.4 - 2026-11-16 - store presentation: name "(original)", short description; version 0.1.4. Image content unchanged.
#   0.2.0 - 2026-11-19 - compatibility recorder: python3 and openssl in the image, recorder.py copied; BUILD_VERSION 0.2.0.
#   0.3.0 - 2026-11-19 - passive UDP capture in the recorder; BUILD_VERSION 0.3.0.
#   0.3.1 - 2026-11-20 - recorder opens the raw socket as root and drops to mfi; BUILD_VERSION 0.3.1.
#   0.3.2 - 2026-11-20 - recorder forwards the Host header; java starts without the Supervisor tokens; BUILD_VERSION 0.3.2.
#   0.3.3 - 2026-11-20 - recorder records the exchange when the client closes the connection; BUILD_VERSION 0.3.3.
#   0.4.0 - 2026-11-21 - passive TCP capture of the inform port in the recorder (off by default); BUILD_VERSION 0.4.0.
# =============================================================================

# -----------------------------------------------------------------------------
# Stage 1: download and verify the Ubiquiti package.
# A current Debian is used because the TLS stack of jessie (2015) is too old
# for today's servers. Base images are pinned by digest.
# -----------------------------------------------------------------------------
FROM debian:bookworm-slim@sha256:734a72b3d6142a71993b4bc580ca01d8ca687f77a2c422d96a961d3376b179bc AS download

ARG MFI_URL="https://dl.ubnt.com/mfi/2.1.11/mFi.unix.zip"
# sha256 of mFi.unix.zip 2.1.11 (26,896,961 bytes), measured 2026-11-15
ARG MFI_SHA256="20f17a752b314ddd997a814851de319dea8ca2f2acb286f0973fb95f0430382d"

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl unzip \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL --retry 3 -o /tmp/mFi.unix.zip "${MFI_URL}" \
    && echo "${MFI_SHA256}  /tmp/mFi.unix.zip" | sha256sum -c - \
    && unzip -q /tmp/mFi.unix.zip -d /opt \
    && test -L /opt/mFi/bin/mongod \
    && rm -f /tmp/mFi.unix.zip

# -----------------------------------------------------------------------------
# Stage 2: the system the controller runs on.
# Debian 8 jessie (archive.debian.org) provides the last packages of that era:
# OpenJDK 7u261 and MongoDB 2.4.10, compatible with the controller's
# mongo-java-driver-2.11.3. Java 8 breaks the mFi web UI.
# -----------------------------------------------------------------------------
FROM debian/eol:jessie@sha256:81cc60273fcd009665b917085e8edb4a44af01130e42a9349545bcaaf05236a2

ARG BUILD_VERSION="0.4.0"
ARG BUILD_ARCH="amd64"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        openjdk-7-jre-headless \
        mongodb-server \
        jq \
        procps \
        curl \
        ca-certificates \
        python3 \
        openssl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY --from=download /opt/mFi /usr/lib/mfi

# Unprivileged user for Java and MongoDB.
# The controller's data/ and logs/ point to the persistent /data volume.
# bin/mongod in the package is a symlink to /usr/bin/mongod.
RUN groupadd -r -g 500 mfi \
    && useradd -r -u 500 -g mfi -d /usr/lib/mfi -s /usr/sbin/nologin mfi \
    && test -x "$(readlink -f /usr/lib/mfi/bin/mongod)" \
    && mv /usr/lib/mfi/data /usr/lib/mfi/data-orig \
    && ln -s /data/mfi /usr/lib/mfi/data \
    && ln -s /data/logs /usr/lib/mfi/logs \
    && chown -R mfi:mfi /usr/lib/mfi

COPY run.sh /run.sh
RUN chmod 0755 /run.sh
COPY recorder.py /recorder.py

LABEL \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="amd64" \
    io.hass.name="Ubiquiti mFi Controller (original)" \
    org.opencontainers.image.title="Ubiquiti mFi Controller (original)" \
    org.opencontainers.image.description="Original Ubiquiti mFi Controller 2.1.11 for Home Assistant" \
    org.opencontainers.image.source="https://github.com/oce-projects/oce-mfi-home-assistant"

# 6080 = inform (devices report to the controller), 6443 = web UI and API
EXPOSE 6080 6443

WORKDIR /usr/lib/mfi
CMD [ "/run.sh" ]
