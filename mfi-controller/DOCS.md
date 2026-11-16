# Ubiquiti mFi Controller - guide

This page appears in the "Documentation" tab of the app in Home Assistant.

## What it does

The app runs the **original Ubiquiti mFi Controller 2.1.11** in a container. The controller talks to mPower power strips, mPort sensor hubs and mFi sensors. Home Assistant talks to the controller through the core `mfi` integration.

```
mFi devices  --6080 inform-->  mFi Controller app  <--6443 API--  Home Assistant "mfi" integration
                                      |
                       /data (MongoDB database, configuration, logs)
```

## Installation

The container is built on the Home Assistant machine: there is no prebuilt image. The first installation downloads about 26.9 MB from Ubiquiti plus the Debian packages of that era, so Home Assistant needs internet access to `dl.ubnt.com`, `archive.debian.org` and Docker Hub.

1. Open **Settings > Apps > App store**.
2. For a local copy: top-right menu, **Check for updates**. The app appears under **Local apps**.
3. Open **Ubiquiti mFi Controller (original)** and press **Install**. Wait until the build ends.
4. Press **Start**.
5. Open `https://HOME-ASSISTANT-IP:6443/`. The certificate is self-signed: the browser asks for confirmation.
6. Follow the controller setup wizard and create the administrator.

### Installing from the local apps folder (without a repository URL)

1. Install and start an app that gives file access: **Samba share** or **Advanced SSH & Web Terminal**.
2. Find the local apps folder. With Samba it is the share `local_apps`. With Advanced SSH & Web Terminal it is `/addons`. Both are the same Supervisor folder (`apps/local`).
3. Copy the whole `mfi-controller` folder there, so that `local_apps/mfi-controller/config.yaml` exists.
4. Continue with step 1 of the installation above.

If the app does not appear: **Settings > System > Logs**, choose **Supervisor** and look for the `config.yaml` validation error.

## Options

| Option | Default | Meaning |
|---|---|---|
| `java_max_memory_mb` | 1,024 | maximum Java heap, 256 to 4,096 MB |

## Connecting the mFi devices

Each device must know the controller address with port **6080**.

1. Open the web portal of the device (factory user and password `ubnt` / `ubnt`).
2. In the **Configuration** tab, field **mFi Controller**, enter `HOME-ASSISTANT-IP:6080`.
3. Enter **User** and **Password** of the controller administrator.
4. Adopt the device in the controller.

A device without a controller looks for `http://mfi:6080/inform` by itself. A DNS name `mfi` pointing to Home Assistant may therefore let devices find it without configuring them one by one. UNVERIFIED with this app: the behavior comes from device logs posted on the Ubiquiti forum.

## Connecting Home Assistant

The `mfi` integration is configured in `configuration.yaml`, not from the UI.

```yaml
sensor:
  - platform: mfi
    host: HOME-ASSISTANT-IP
    port: 6443
    ssl: true
    verify_ssl: false
    username: !secret mfi_username
    password: !secret mfi_password

switch:
  - platform: mfi
    host: HOME-ASSISTANT-IP
    port: 6443
    ssl: true
    verify_ssl: false
    username: !secret mfi_username
    password: !secret mfi_password
```

`verify_ssl: false` is needed because the controller certificate is self-signed.

## Backup and restore

- A Home Assistant backup stops the app, saves `/data` and starts it again (`backup: cold`), so the MongoDB database stays consistent.
- A `.unf` backup of an old controller is loaded from the bottom panel **Admin**, box **Restore**. The controller reloads the database by itself, without restarting the app.
- After a restore the administrators and passwords **of the backup** apply, not the one created in the wizard.
- A settings-only backup (52 KB in the test) restores in about 5 seconds. A backup with the measurement history (263.5 MB in the test) had not finished after 19 minutes and already used 6.9 GB: check the free space of Home Assistant before loading it.
- The **Admin** panel also has **Backup Database**, which downloads a controller `.unf`.

## Known limits

- The **Map** tab needs Adobe Flash Player, which browsers dropped in 2021: the map is not shown. The Data, Events, Rules, Scenes and Energy tabs and the Admin panel are HTML and open (tested with Chromium 140, 0 JavaScript errors, no devices).
- Charts in the Data tab with real devices have not been tested.
- MongoDB 2.4 listens only inside the container, on `127.0.0.1:37017`: it cannot be reached from the network.
- The controller checks for updates at `http://www.ubnt.com/downloads/mfi/updates/`. There are none any more.
- Stopping takes 1.5 to 26 seconds (measured): the app allows up to 120 seconds.
- Space used in `/data` right after the first start: 289 MB.

## Security

The controller is from 2015 and gets no updates: Java 7 and MongoDB 2.4 are out of support. Use the app **only on the local network**, ideally with the devices on an isolated network. Never open ports 6080 and 6443 to the internet.

- The controller 2.1.11 has a published authentication bypass (published 2015-09-03, UNVERIFIED: date not checked against the original advisory) that lets an attacker skip the login and read the administrator password. Ubiquiti never released a fix. An unofficial patch of the class `com/ubnt/ace/view/AuthFilter` exists (https://github.com/ikkisoft/mFiPatchMe); **this app does not apply it**. Anyone who can reach port 6443 can take over the controller and, through it, the devices.
- The controller stores the administrator password in clear text and gives the same user name and password to every adopted device for SSH and its web page (source: decompiled `ace.jar` 2.1.11, analysis done outside this repository; UNVERIFIED with this app). Use a dedicated password that is not used anywhere else.
- Devices are adopted over SSH with the factory user `ubnt` / `ubnt` and the controller does not check the SSH host key (same source, UNVERIFIED with this app).

## Data

| Path in the container | Content |
|---|---|
| `/data/mfi` | configuration `system.properties`, database `db/`, certificate `keystore` |
| `/data/logs` | `server.log` and `mongod.log` |

The controller log also appears in the **Log** tab of the app.

## Technical notes

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
