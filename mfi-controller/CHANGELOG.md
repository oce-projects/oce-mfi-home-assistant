# Changelog

## 0.5.0 - 2026-11-21

- Change: the controller keeps the inform port on 6080 also while recording. With `record_traffic` on, the controller moves only its web UI to 16443; the `unifi.http.port=16080` line is removed from the recorder block of `system.properties`. The recorder captures port 6080 passively (`--tcp-capture 6080`) and listens on 16080, forwarding to 6080 (`--inform-listen 16080 --inform-target 6080`), so devices already pointed at 16080 are still recorded. Forwarded exchanges are not recorded twice: the TCP capture ignores connections from 127.x.
- `run.sh`: `start_recorder` waits for `port_open 6080 && port_open 16443`; the log line for a missing inform port says `recording of port 6080 unavailable: the controller did not open 6080`. The message `https recording unavailable: the controller did not move to 16443` is unchanged.
- `test_run_sh.py`: `test_recorder_markers_and_ports_are_written` and `test_old_block_is_removed_before_the_block_is_written` are adapted to the new behaviour (`unifi.http.port` is no longer written; the port the old-block test looks for is `unifi.https.port=16443`). Three new tests in `TestUdpCapture` cover the forward 16080 to 6080, the TCP capture of 6080 and the wait on 6080.
- `DOCS.md` and `README.md`: the inform stays on 6080; the internal controller port while recording is 16443. UNVERIFIED on a device: that adopted devices return to 6080 by themselves.
- Version 0.5.0 in `config.yaml`, `CHANGELOG.md` and `Dockerfile`.

## 0.4.0 - 2026-11-21

- Feature: passive capture of the inform port in the recorder (`--tcp-capture PORT`, off by default). The raw socket reads the TCP segments of port 6080 and the recorder rebuilds each HTTP request and answer into one line of the day file, in the same format as the proxy lines. Chunked answers are decoded; an answer without length ends with the FIN of the server. It only listens: it never answers, resets or injects packets. Connections from 127.x (the proxy's own forwarding) are not recorded twice. Memory per connection is capped (1 MB), at most 256 connections are kept, idle ones are dropped after 120 seconds. UNVERIFIED on a device: no device test of the TCP capture yet.
- `run.sh` does not change: the controller stays on 16080 and the TCP capture is not switched on (next ticket).
- Version 0.4.0 in `config.yaml`, `CHANGELOG.md` and `Dockerfile`.

## 0.3.3 - 2026-11-20

- Fix: the recorder sent the answer to the client before recording the exchange, so a client that closed the connection first (for example the browser on port 6443, `ssl.SSLEOFError`) stopped the exchange from being recorded and the log showed a traceback. The exchange is now recorded in every case; the log has one WARNING line (`closed the connection before the answer was sent`) instead of the traceback.
- `DOCS.md`: the evidence for the move to 16443 is corrected; new UNVERIFIED note on device informs that may bypass the recorder on 16080.
- Dates of the 0.3.2 entry and of the 0.3.2 headers of `run.sh` and `Dockerfile` corrected from 2026-11-21 to 2026-11-20.
- Version 0.3.3 in `config.yaml`, `CHANGELOG.md` and `Dockerfile`.

## 0.3.2 - 2026-11-20

- Fix: the recorder forwarded the request with its own address as Host (`127.0.0.1:16443`), so the controller built its redirect to `https://127.0.0.1:16443/manage` and the browser could not open the web UI. The Host of the client is now forwarded unchanged; the `Location` header of responses is passed unchanged.
- Security: `run.sh` starts java and the recorder without `SUPERVISOR_TOKEN` and `HASSIO_TOKEN`, so the controller log no longer contains them. Versions up to 0.3.1 wrote them in the log. The token changes at each start: restart the app after the update.
- `DOCS.md`: the web UI is opened on port 6443 with the recorder on; setup wizard before Adopt; note on the Supervisor tokens in the log.
- Version 0.3.2 in `config.yaml`, `CHANGELOG.md` and `Dockerfile`.

## 0.3.1 - 2026-11-20

- Fix: passive UDP capture never started in 0.3.0. `run.sh` started the recorder with `--chuid mfi:mfi`, which drops the NET_RAW capability, so the raw socket could not be opened and the log said `udp capture unavailable`. Now the recorder starts as root, opens the raw socket, and drops to user `mfi` itself (`--user mfi`). The controller still runs as `mfi`.
- The recorder skips copies of its own outgoing packets on `lo` and frames that are neither Ethernet nor loopback (filter UNVERIFIED on a device).
- `DOCS.md`: host network notes for MongoDB and the internal ports, and the start as root for the socket only.
- Version 0.3.1 in `config.yaml`, `CHANGELOG.md` and `Dockerfile`.

## 0.3.0 - 2026-11-19

- Passive UDP capture of the discovery port 10001 and the wake-up port 3478 in the recorder, when `record_traffic` is on. The recorder only listens: it never answers or injects packets. Captured packets go to the same daily file as the TCP lines, under the same size limit.
- `config.yaml` now uses `host_network: true` and the `NET_RAW` capability under `privileged`, needed to listen on the link layer. Security change: the add-on sees the host network.
- Decoding of the discovery and wake-up packets in `tools/decode_recording.py`.
- Version 0.3.0 in `config.yaml`, `CHANGELOG.md` and `Dockerfile`.

## 0.2.0 - 2026-11-19

- Optional compatibility recorder: options `record_traffic` (off by default) and `record_max_mb` (10 to 2,000 MB, default 200). Recordings go to `/share/mfi-recordings`; the add-on maps `share:rw`.
- Image: `python3` and `openssl` added; `recorder.py` copied to `/recorder.py`.
- With the recorder off (default) the add-on behaves exactly as 0.1.4.
- Version 0.2.0 in `config.yaml`, `CHANGELOG.md` and `Dockerfile`.

## 0.1.4 - 2026-11-16

- Store presentation: the add-on name is now «Ubiquiti mFi Controller (original)», with a short legacy description that points to mFi Server (new).
- Add-on icon and logo generated by `tools/make_icons.py`.
- Image content unchanged; version 0.1.4 in `config.yaml`, `CHANGELOG.md` and `Dockerfile`.

## 0.1.3 - 2026-11-15

- Security section of `DOCS.md` now describes the unpatched 2015 authentication bypass, the clear-text administrator password and the SSH adoption with factory credentials; image content unchanged.

## 0.1.2 - 2026-11-15

- `BUILD_VERSION` default in `Dockerfile` aligned with `config.yaml`: it was
  0.1.0, so an image built without the argument was labelled `io.hass.version`
  0.1.0. Version lines removed from the headers of `config.yaml`, `Dockerfile`,
  `run.sh`, `README.md` and `DOCS.md`; the version now lives only in
  `config.yaml`, this changelog and `ARG BUILD_VERSION`. Image content unchanged.

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
