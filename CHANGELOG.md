# Changelog

All notable changes to this repository. Each add-on has its own CHANGELOG.md.

## 0.10.0 - 2026-11-16

- Epic D1 of `mfi-server` 0.8.0 (phase 2): UDP discovery on port 10001 (`ubnt_discovery.py`), with the routes `api/v1/discovery` and `api/v1/discovery/scan`, a scan at startup, and a table of the discovered devices in the web page. The add-on runs with the host network (`host_network: true`, no `ports` block), and the new `ingress_peer` option sets the address allowed in add-on mode.
- Versions aligned: `mfi-server` 0.8.0 in `config.yaml`, `CHANGELOG.md`, `Dockerfile` and `__version__`; repository 0.10.0 in `VERSION` and `CHANGELOG.md`.

## 0.9.0 - 2026-11-16

- Epic T-MWIEDB3M: `mfi-server` runs as a standalone program, outside Home Assistant. Added systemd and Docker Compose examples, a settings example (`settings.example.json`), an environment example (`mfi-server.env.example`), a «Run without Home Assistant» guide in the `mfi-server` README, and the test `tests/test_examples.py` that keeps the examples aligned with the real settings.
- Versions aligned: `mfi-server` 0.7.0 in `config.yaml`, `CHANGELOG.md`, `Dockerfile` and `__version__`; repository 0.9.0 in `VERSION` and `CHANGELOG.md`.

## 0.8.0 - 2026-11-16

- Epic F-UI of `mfi-server` 0.6.0 (phase 2): automations web page (list, enable/disable, run, delete, YAML editor with errors, run history) and the shared `web/common.js` loaded by both pages.
- Versions aligned: `mfi-server` 0.6.0 in `config.yaml`, `CHANGELOG.md`, `Dockerfile` and `__version__`; repository 0.8.0 in `VERSION` and `CHANGELOG.md`.

## 0.7.0 - 2026-11-15

- Epic F of `mfi-server` 0.5.0 (phase 2): automation engine in the Home Assistant format (level 1), with a reduced YAML reader (`yaml_lite`), the automation model with validation, the engine (triggers, conditions, actions, modes and traces), the `automations.json` store, the `api/v1/automations*` routes, and the wiring in `__main__`. Automations are optional.
- Versions aligned: `mfi-server` 0.5.0 in `config.yaml`, `CHANGELOG.md`, `Dockerfile` and `__version__`; repository 0.7.0 in `VERSION` and `CHANGELOG.md`.

## 0.6.0 - 2026-11-15

- Epic E2 of `mfi-server` 0.4.0 (phase 2): web page with devices, outlets, measurements and history, in English and Italian, inside the Home Assistant ingress and in standalone mode.
- Versions aligned: `mfi-server` 0.4.0 in `config.yaml`, `CHANGELOG.md`, `Dockerfile` and `__version__`; repository 0.6.0 in `VERSION` and `CHANGELOG.md`.

## 0.5.0 - 2026-11-15

- `mfi-server` 0.3.0 (phase 2): HTTP JSON API (health, login and logout with a session cookie, devices, output commands, history) with a route prefix that accepts the Home Assistant ingress path; measurement history in sqlite3, kept 30 days; login for the standalone mode with a password set by `set-password` (off until it is set); add-on mode reached through ingress from 172.30.32.2 only; output commands send the wake-up packet when the device address is known, so the output changes at once; `web_port` and `history_days` settings; `config.yaml` with ingress.
- The exception for 172.30.32.2 (Home Assistant ingress address) is documented in `tests/test_repository.py`.

## 0.4.0 - 2026-11-15

- `mfi-server` 0.2.0 (phase 2): MQTT client in pure Python, Home Assistant MQTT discovery for the outlets and their measurements, and an MQTT bridge for states and output commands. The broker comes from the Supervisor in add-on mode or from the `MFI_MQTT_*` settings.
- Versions aligned: `mfi-server` 0.2.0 in `config.yaml`, `CHANGELOG.md`, `Dockerfile` and `__version__`.

## 0.3.0 - 2026-11-15

- New add-on `mfi-server` 0.1.0 (phase 2): pure Python inform core (AES-128, inform packets, `.unf` key import, device store, states, `mfi-output` commands, measurements, HTTP server, command line), standard library only, tested offline in `mfi-server/tests/`; never sends a factory reset.
- `README.md`, `AGENTS.md` and `docs/ARCHITECTURE.md` updated.

## 0.2.5 - 2026-11-15

- `docs/PROTOCOL.md` rewritten with the inform protocol specification taken from the decompiled
  controller 2.1.11 (packet format, keys, adoption, responses, commands, measurements, discovery,
  states, open questions); one line updated in `docs/ARCHITECTURE.md` and `AGENTS.md`.

## 0.2.4 - 2026-11-15

- `docs/DEVAGENTAI.md` now lists the settings actually used in DevAgentAi; `mfi-controller` 0.1.3 (security notes in `DOCS.md`).

## 0.2.3 - 2026-11-15

- private data scan covers every private IPv4 range (10/8, 172.16/12, 192.168/16) instead of three home addresses; documented exceptions in ALLOWED_MATCHES.

## 0.2.2 - 2026-11-15

- Add-on `mfi-controller` 0.1.2: versions aligned (`ARG BUILD_VERSION` in
  `Dockerfile` equals `config.yaml`; version headers removed from add-on files).
- New test: `ARG BUILD_VERSION` must equal the add-on version, and stale
  version headers left in add-on files are reported.

## 0.2.1 - 2026-11-15

- Repository renamed from `mfi-home-assistant` to `oce-mfi-home-assistant`
  (`oce-projects/oce-mfi-home-assistant` on GitHub): README title, `repository.yaml`
  URL and the test module docstring updated.

## 0.2.0 - 2026-11-15

- New add-on `mfi-controller` 0.1.0 (phase 1): original mFi Controller 2.1.11 on
  Debian 8 jessie with OpenJDK 7u261 and MongoDB 2.4.10, built and tested with
  Docker on an amd64 host (not yet on Home Assistant OS). Measurements in
  `mfi-controller/README.md`.
- New `tools/bench_mfi_controller.sh`: Docker test bench for the add-on (build,
  start, wizard, mficlient login, restart, restore of a `.unf` backup in a
  throwaway container without network). Run by a human, not by the test suite.
- AGENTS.md facts corrected: `mFi/bin/mongod` is a symlink to `/usr/bin/mongod`,
  not a placeholder; the internal MongoDB port 37017 is now measured.
- README: local add-ons folder is now `local_apps` (`/addons` in the
  Advanced SSH & Web Terminal app); install steps use the current "Apps" names.

## 0.1.0 - 2026-11-15

- Repository skeleton: README, AGENTS.md (rules for DevAgentAi), repository.yaml,
  docs (architecture, protocol notes, DevAgentAi settings), offline structure tests.
