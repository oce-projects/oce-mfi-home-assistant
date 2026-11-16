# AGENTS.md - rules for autonomous agents (DevAgentAi) and humans

This repository is a **Home Assistant add-on repository** for Ubiquiti mFi devices
(mPower power strips, mPort sensor hubs, mFi sensors, in-wall outlets and switches).
The mFi product line is end-of-life; the last stable mFi Controller is 2.1.11
(April 2015). Goal: run the devices from Home Assistant OS without the vendor cloud.

Read `docs/ARCHITECTURE.md` before changing structure. Read `docs/PROTOCOL.md`
before touching anything that talks to devices.

## Hard rules

1. **Never commit Ubiquiti files.** No `.jar`, `.zip`, `.deb`, `.bin`, `.unf`,
   `.exe`, `.dmg`, firmware or controller binaries. The mFi Controller is
   proprietary. Add-ons download it at build time from `dl.ubnt.com` and check a
   pinned sha256. `tests/test_repository.py` fails if such a file is tracked.
2. **Never commit secrets or site data.** No passwords, `authkey` values, SSH keys,
   real MAC addresses, home IP addresses, host names or local drive paths.
   Controller backups (`.unf`) contain device keys: they never enter the repo.
   The publishability test checks for known private patterns.
3. **Version and changelog on every change.** The repository version is in
   `VERSION` and must equal the newest entry of `CHANGELOG.md`. Each add-on has
   its own `version` in `<addon>/config.yaml`, equal to the newest entry of
   `<addon>/CHANGELOG.md`. Bump them in the same commit as the change
   (semantic versioning: fix = patch, feature = minor).
4. **Tests run offline.** The test command runs in a container without network.
   Tests use the Python standard library only. Do not add tests that need the
   internet, Docker, a device or Home Assistant.
5. **Do not weaken tests to make them pass.** If a test is wrong, fix the test in
   its own commit and say why in the changelog.
6. **Measure, don't guess.** Every number in docs (sizes, ports, versions) comes
   from a file, a command output or a cited source. Unverified facts are marked
   `UNVERIFIED`.
7. **English** for all files in this repository.
8. **Security.** mFi firmware and the 2015 controller have known weaknesses
   (old SSH ciphers, an unpatched authentication bypass reported in 2015).
   Never expose ports 6080/6443 to the internet. Document that the devices belong
   on an isolated network.

## Layout

| Path | What |
|---|---|
| `repository.yaml` | Home Assistant add-on repository manifest |
| `mfi-controller/` | Phase 1 add-on: original mFi Controller 2.1.11 in a container (tested with Docker, not yet on HAOS) |
| `tools/` | scripts run by a human (Docker test bench), and `make_icons.py` run by DevAgentAi and loaded by `mfi-server/tests/test_icons.py`; the Docker bench scripts are never part of the offline tests |
| `mfi-server/` | Phase 2 add-on: our own server speaking the inform protocol (in progress, standard library only) |
| `docs/ARCHITECTURE.md` | phases, components, decisions |
| `docs/PROTOCOL.md` | what is known about the devices and the inform protocol |
| `docs/DEVAGENTAI.md` | project settings proposed for DevAgentAi |
| `tests/` | offline structure tests (`python3 -m unittest discover -s tests -v`) |
| `.tickets/` | written by DevAgentAi, ignored by git |

An add-on folder is any top-level folder that contains `config.yaml`. It must
contain `config.yaml`, `Dockerfile`, `README.md` and `CHANGELOG.md`.

## Facts you can rely on (verified 2026-11-15)

| Fact | Source |
|---|---|
| Controller ports: 6080 inform (HTTP), 6443 web UI (HTTPS) since 1.1.0; 9080/9443 up to 1.0.8; configurable in `<mFi>/data/system.properties` | official Ubiquiti FAQ, 2013 |
| Controller 2.1.11 Linux package: `https://dl.ubnt.com/mfi/2.1.11/mFi.unix.zip`, 26,896,961 bytes, sha256 `20f17a752b314ddd997a814851de319dea8ca2f2acb286f0973fb95f0430382d` | downloaded and hashed |
| The package contains `mFi/lib/ace.jar` (controller code, built on the UniFi code base, class `com.ubnt.ace.Launcher`), `mongo-java-driver-2.11.3.jar`, and `mFi/bin/mongod`, a symlink to `/usr/bin/mongod` (15 bytes = the path): MongoDB must be installed separately and the controller starts it | archive listing, Unix mode `0o120755` |
| The controller runs on OpenJDK 7u261 + MongoDB 2.4.10 (Debian 8 jessie); MongoDB listens on `127.0.0.1:37017` | `ps` in the `mfi-controller` container, see its README |
| Java 7 is required; Java 8 broke the web UI of 2.1.4 | user reports on the Ubiquiti forum |
| One "M2M" firmware for all mFi products; official versions 2.1.1 to 2.1.11; files start with `UBNT` | dl.ubnt.com listing, file headers |
| A device without controller polls `http://mfi:6080/inform` every 15 s | device log posted on the Ubiquiti forum |
| Home Assistant core has an `mfi` integration (YAML only, library `mficlient`) that needs a running controller | home-assistant/core source |

Not verified on a device: UDP discovery port 10001 (from the controller code, see `docs/PROTOCOL.md`). Not verified: exact MongoDB version range (only 2.4.10 tested).

## How to work

- One ticket = one focused change. Keep commits small.
- Run `python3 -m unittest discover -s tests -v` before finishing. It must exit 0.
- mfi-server tests: `python3 -m unittest discover -s mfi-server/tests -t mfi-server -v`.
- Update `docs/` when you learn a new fact; cite where it came from.
- If a task needs a real device, Docker or Home Assistant, stop and write in the
  ticket exactly what must be run by a human and what output is expected.
