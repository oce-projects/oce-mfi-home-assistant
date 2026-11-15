# Changelog

## 0.1.1 - 2026-11-15

- Repository URL in `config.yaml` and in the image label
  `org.opencontainers.image.source` updated to the renamed repository
  `oce-projects/oce-mfi-home-assistant`. No change to the image content.

## 0.1.0 - 2026-11-15

First version (phase 1 of the project: original controller in a container).

- Ubiquiti mFi Controller **2.1.11**, downloaded from `dl.ubnt.com` at build time and checked against a pinned sha256. No Ubiquiti file in the repository.
- Period system: Debian 8 jessie, **OpenJDK 7u261** and **MongoDB 2.4.10**. The controller starts MongoDB itself through `bin/mongod`, a symlink to `/usr/bin/mongod`.
- Java and MongoDB run as user `mfi` (uid 500), not as root.
- Persistent data in `/data/mfi` (configuration and database) and `/data/logs` (logs).
- Ports 6080 (inform) and 6443 (web UI and API).
- Clean stop with `ace.jar stop`; automatic restart if the controller exits by itself.
- Option `java_max_memory_mb` (256 to 4,096 MB, default 1,024 MB).
- Home Assistant backups taken with the controller stopped (`backup: cold`).
- `amd64` only.
