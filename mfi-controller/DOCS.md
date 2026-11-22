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

Until the setup wizard is finished, the controller writes `*** Factory Default *** Database exists. Drop it` at each start, and a device stays `waiting for adoption` with `cannot be auto-adopted: no account info in inform message`. Press **Adopt** only after the wizard is finished (observed in the add-on log on Home Assistant OS, 2026-11-20).

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
| `record_traffic` | false | turns the compatibility recorder on (records inform 6080 and web 6443, and passively the UDP traffic of ports 10001 and 3478, see Passive UDP capture) |
| `record_max_mb` | 200 | daily recording size limit, 10 to 2000 MB |

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
- MongoDB 2.4 listens on `127.0.0.1:37017`. Without the host network it is only inside the container. With the host network (passive UDP capture, see below) it is in the host's network namespace: it is not reachable from the local network through this address, but it shares the host's ports (UNVERIFIED on Home Assistant OS).
- The controller checks for updates at `http://www.ubnt.com/downloads/mfi/updates/`. There are none any more.
- Stopping takes 1.5 to 26 seconds (measured): the app allows up to 120 seconds.
- Space used in `/data` right after the first start: 289 MB.

## Security

The controller is from 2015 and gets no updates: Java 7 and MongoDB 2.4 are out of support. Use the app **only on the local network**, ideally with the devices on an isolated network. Never open ports 6080 and 6443 to the internet.

- The controller 2.1.11 has a published authentication bypass (published 2015-09-03, UNVERIFIED: date not checked against the original advisory) that lets an attacker skip the login and read the administrator password. Ubiquiti never released a fix. An unofficial patch of the class `com/ubnt/ace/view/AuthFilter` exists (https://github.com/ikkisoft/mFiPatchMe); **this app does not apply it**. Anyone who can reach port 6443 can take over the controller and, through it, the devices.
- The controller stores the administrator password in clear text and gives the same user name and password to every adopted device for SSH and its web page (source: decompiled `ace.jar` 2.1.11, analysis done outside this repository; UNVERIFIED with this app). Use a dedicated password that is not used anywhere else.
- Devices are adopted over SSH with the factory user `ubnt` / `ubnt` and the controller does not check the SSH host key (same source, UNVERIFIED with this app).
- Up to 0.3.1 the log of the controller (`/data/logs/server.log`) contained `SUPERVISOR_TOKEN` and `HASSIO_TOKEN` in clear text. From 0.3.2 java no longer receives them. The token changes at each start, so restart the app after the update. `/data/logs/server.log` may still contain old tokens: do not share that file.

## Compatibility recorder

The compatibility recorder is optional and off by default. It records the exchanges with the original controller, so that the new mFi Server can be tested against real traffic. It is a test bench for the compatibility checks of the new server, not a feature for daily use.

### Turning it on

1. Set the option `record_traffic` to `true`.
2. Set `record_max_mb` to the daily size limit (10 to 2000 MB, default 200).
3. Restart the app.

With `record_traffic` off, nothing is recorded and the controller listens on 6080 and 6443 as usual. The add-on still runs with the host network and the NET_RAW permission, because they are set in the add-on configuration, not by the option (see Passive UDP capture).

### How it works

With `record_traffic` on, the controller moves only its web UI to the internal port 16443; the inform port stays 6080. The move of the web port is set through the property `unifi.https.port`: OBSERVED on Home Assistant OS on 2026-11-20: the browser on port 6443 got a redirect from the controller through the recorder, and the log did not say `https recording unavailable`. (The line `recording inform ...` is printed by the recorder with its own arguments: it does not prove that the controller moved.). The inform port `unifi.http.port` is OBSERVED in `docs/controller/system.md`. The recorder listens on 6443 (web) and on 16080, forwards each request unchanged to the controller (6443 goes to 16443, 16080 goes to 6080) and returns the answer unchanged. Devices and browsers keep using 6080 and 6443; devices already pointed at 16080 keep working through the forward. With `--tcp-capture 6080` the recorder also captures port 6080 passively (raw socket, see Passive UDP capture). The exchanges it forwards from 16080 come from 127.x and are not recorded twice. The log lines to look for are `passive tcp capture of port 6080` and `recording inform 16080 -> 6080`. After each exchange the recorder writes one line.

With the recorder on, open the web UI at `https://HOME-ASSISTANT-IP:6443/`. The recorder forwards the Host header of the browser, so the controller builds its redirects with the same address. Version 0.3.1 and earlier sent the recorder's own address (`127.0.0.1:16443`) and the browser could not open the web UI; fixed in 0.3.2.

If the controller does not move to 16443 within 120 seconds, the log says `https recording unavailable: the controller did not move to 16443` and only the inform port 6080 is recorded.

With versions 0.2.0 to 0.4.0, devices adopted while the recorder was on may have been pointed at port 16080. From 0.5.0 the recorder forwards those informs to 6080. **UNVERIFIED:** that the controller points such devices back to 6080 by itself (`docs/controller/device-lifecycle.md`). Before you turn `record_traffic` off, check in the controller that the devices use port 6080, or adopt them again: with the recorder off, port 16080 does not answer. On Home Assistant OS, after the start, the day file should contain lines with `"port": 6080`.

Release 0.5.0 left the controller on 16080 when `system.properties` contained the line outside the markers (OBSERVED on Home Assistant OS on 2026-11-21: log `unifi.http.port = 16080` after the 0.5.0 start; the cause is UNVERIFIED); from 0.5.1 the add-on removes the 16080/16443 lines wherever they are and logs `ports in system.properties:`.

When the browser closes a connection before the answer is sent, the log says `client ... closed the connection before the answer was sent` and the exchange is still recorded (from 0.3.3).

### Passive UDP capture

With `record_traffic` on, the recorder also captures the UDP traffic of the original controller, on two ports:

- port **10001** (discovery): the discovery requests of the controller and the replies of the devices;
- port **3478** (wake-up): the wake-up traffic that makes devices connect to the controller.

The capture is passive: the recorder only listens. It never answers, sends or injects packets. Each captured packet is one JSON line in the same daily file as the TCP exchanges, with `port` set to `udp10001` or `udp3478`, the `src` and `dst` addresses and ports, and the UDP payload in base64.

To receive packets that are not addressed to the add-on, the add-on uses the host network, and it needs the NET_RAW permission to open a raw AF_PACKET socket. Both settings are in the add-on configuration, not in the option: they apply also when `record_traffic` is off, although then nothing is captured. The same socket also captures the TCP traffic of port 6080, passively. If the socket cannot be opened, the log writes `udp capture unavailable:` once, with the reason, and port 6080 is not recorded: only the exchanges of 16080 are. Whether AF_PACKET works inside Home Assistant OS is UNVERIFIED.

The recorder starts as root only to open this socket. Right after that it drops to user `mfi` and runs the proxies and the UDP parsing as that user. The change of user takes away the capability to open a raw socket, which is why the socket is opened first.

Frames that the recorder cannot parse as Ethernet II are skipped: copies of its own outgoing packets on `lo` (packet type PACKET_OUTGOING) and frames whose link type is neither Ethernet nor loopback. The address fields used for this filter are UNVERIFIED on a device (see the comment on `frame_usable` in `recorder.py`).

**Risk of the host network.** With the host network, the internal port 16443 that the controller uses while recording becomes reachable from the local network, and so does the port 16080 of the recorder. A client that connects to 16443 reaches the controller without passing through the recorder, so that exchange is not recorded. The 2.1.11 controller has no documented bind-address property that would limit these ports, so the add-on sets none. Whether the controller listens on all interfaces is UNVERIFIED with this add-on.

With the host network, MongoDB (`127.0.0.1:37017`) and the internal port 16443 and the recorder's port 16080 are in the host's network namespace too. They may clash with other services of the host that use the same port (UNVERIFIED: not tested on Home Assistant OS). If the controller fails to start, check the host's listening ports first.

Rules for this option:

- Do not start this add-on at the same time as mFi Server: both use port 6080.
- Keep the devices and the controller on an isolated network. Never expose ports 6080 and 6443 to the internet (AGENTS.md, rule 8).
- The UDP lines hold MAC addresses, IP addresses, host names and the ESSID of your devices: treat them as private, like the TCP recordings.

### Where the files are

One file per day: `/share/mfi-recordings/YYYY-MM-DD.jsonl`, with one JSON object per exchange, on one line. Captured UDP packets (see Passive UDP capture) go to the same file, one JSON object per packet. When the file of the day reaches `record_max_mb`, no more lines are written until the next day; the log says so once per day.

### Browser certificate

On port 6443 the recorder presents a self-signed certificate, generated at the first start under `/data/recorder/`. The browser asks for confirmation, as it does for the controller itself.

### Risk

The recordings contain MAC addresses and site data. Port 6443 is masked for passwords, cookies and tokens, but its responses still contain site data: treat the recordings as private. The files stay in `/share` and never enter the repository. Do not publish them and do not attach them to issues.

### Decoding

On your PC, with a checkout of this repository and the `.unf` backup of the same site:

```
python3 tools/decode_recording.py --recording FILE.jsonl --backup FILE.unf --out DIR [--anonymize]
```

The device keys come from the backup and never leave your PC. Only the anonymized output (`--anonymize`) may go into the repository.

The decoder also reads the UDP lines. For port 10001 it lists the discovery fields of the packet (MAC, IPv4 address, version, uptime, host name, platform, ESSID, model, firmware and the default flag, when present). For port 3478 it gives the packet length and whether the packet is a connection request. The discovery field layout comes from the controller code and is UNVERIFIED on a device (`docs/PROTOCOL.md`, section Discovery). With `--anonymize` the MAC addresses, IP addresses, host names and ESSID are replaced by stable placeholders.

### Security rule

Ports 6080 and 6443 must never be exposed to the internet (AGENTS.md, rule 8). Keep the devices and the controller on an isolated network. The recorder adds no protection of its own.

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
- Passive UDP capture (ports 10001 and 3478) with the host network and NET_RAW on Home Assistant OS: not tested.
