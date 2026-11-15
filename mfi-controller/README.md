# Ubiquiti mFi Controller (Home Assistant app)

Version 0.1.0 - history in `CHANGELOG.md`. Usage guide in `DOCS.md`.

This app (add-on) runs the **original Ubiquiti mFi Controller 2.1.11** in a container on Home Assistant OS. It serves mPower power strips, mPort sensor hubs and mFi sensors, a product line discontinued in 2015.

Home Assistant talks to the controller through the `mfi` integration, which is still in Home Assistant core (library `mficlient` 0.5.0, YAML configuration only).

- **Architecture:** `amd64` only.
- **Ports:** 6080 (inform, used by the devices) and 6443 (web UI and API, HTTPS).
- **License:** the Ubiquiti software is not in this repository. The `Dockerfile` downloads it from `dl.ubnt.com` at build time and checks the sha256.
- **Status:** experimental. Built and tested with Docker on an amd64 Linux host; **not yet installed on Home Assistant OS**. The software is from 2015 and gets no security updates: keep it on the local network, never expose it to the internet.

## How it is built

```
build (Supervisor)                       runtime
------------------                       -------
stage 1: debian:bookworm-slim            debian/eol:jessie
  curl dl.ubnt.com/mFi.unix.zip            OpenJDK 7u261 + MongoDB 2.4.10
  sha256sum -c                             user mfi (uid 500)
  unzip  -------- /opt/mFi ---------->     /usr/lib/mfi
                                           data -> /data/mfi, logs -> /data/logs
```

- Download and checksum run in a current Debian, because the TLS stack of jessie (2015) is too old for today's servers.
- Both base images are pinned by digest. `apt` on `archive.debian.org` works without signature errors: `openjdk-7-jre-headless 7u261-2.6.22-1~deb8u1`, `mongodb-server 1:2.4.10-5+deb8u1`.
- No `build.yaml`: since 2026 the Supervisor no longer needs it and no longer passes `BUILD_FROM` (Supervisor 2026.04.0). The base image is in the `FROM` line and the `io.hass.*` labels are set in the `Dockerfile`. Source: https://developers.home-assistant.io/blog/2026/04/02/builder-migration
- `bin/mongod` in the Ubiquiti package is a symlink to `/usr/bin/mongod`: the controller starts MongoDB itself, listening only on `127.0.0.1:37017` inside the container.

## Measurements (2026-11-15)

Host: amd64 Linux, Docker 29.6.1. Method: `tools/bench_mfi_controller.sh` in this repository (each command logs what it measures).

| What | Result | Method |
|---|---|---|
| Image build, empty cache | 70.6 s | `bench_mfi_controller.sh build` |
| Image size | 229,891,984 bytes | `docker image inspect` |
| Package checksum during build | `mFi.unix.zip: OK` | `sha256sum -c` in stage 1 |
| Port 6443 answers after start | 10.1 s, 12.1 s and 12.5 s (three runs), HTTP 302 | `curl` once per second |
| Port 6080 (inform) | HTTP 400 to an empty GET: the port answers | `curl` |
| Container memory 20 s after start | 430.5 to 468.8 MiB | `docker stats` |
| `/data` after first start | 289 MB (preallocated MongoDB files) | `du -sh` |
| Stop | 1.5 s, 26.0 s and 18.7 s (three runs), exit code 0 | `docker stop -t 120` |
| Back up after `docker start` | 6.4 s, 6.6 s and 6.4 s; data and admin kept | `curl`, login |
| TLS | TLSv1.2, `ECDHE-RSA-AES256-SHA384`, RSA 2,048 bit | OpenSSL 3.0.2 `s_client` |
| Home Assistant library | **`mficlient` 0.5.0 logs in**, `get_devices()` returns 0 devices (empty controller) | Python 3.13 with OpenSSL 3.5.7 |
| Web UI in a modern browser | login works, 0 JavaScript errors; the **Map** tab needs Adobe Flash | Chromium 140 headless (Playwright) |

The certificate is self-signed (`CN=mFi, O=ubnt.com`, `sha1WithRSAEncryption`), generated on first start and valid for 10 years: each installation has its own key. The `mfi` integration needs `verify_ssl: false`.

## Restore of real controller backups

Tested in a throwaway container with `--network none`; data deleted afterwards; only the number of documents per collection was read.

| Backup | Size | Result |
|---|---|---|
| settings only | 52,112 bytes | upload 0.2 s; controller back up **4.6 s** after the restore command; 16 devices, 20 sensors, 14 rules |
| full database with history | 263,505,408 bytes | upload 7.4 s; **not finished after 19 minutes**, database already 6.9 GB (9,793,623 statistics documents) |

The `readme_mFi.txt` in the Ubiquiti package says backup and restore do not work in the Unix build: the restore from the web UI does work.

## Not tested

- Installation and build on Home Assistant OS.
- Adoption of a real device, charts in the Data tab, entities in Home Assistant.
- Final time and disk space of a full-history restore.
