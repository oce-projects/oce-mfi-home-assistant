# Changelog

All notable changes to this repository. Each add-on has its own CHANGELOG.md.

## 0.21.1 - 2026-11-17

- docs: placeholder section "mPort and sensors (from ace.jar 2.1.11)" in docs/PROTOCOL.md; every item is UNVERIFIED because the ace.jar REA report verified no fact (ticket T-MWKWKNJW).

## 0.21.0 - 2026-11-17

- The Windows program of `mfi-wifi-setup` is built by GitHub Actions on `windows-latest` and attached to each published release, with its sha256 file (ticket T-MWKUB27O): `.github/workflows/windows-exe.yml`, offline checks in `tests/test_windows_workflow.py`. The `.exe` is never committed.
- `mfi-wifi-setup/README.md` has a "Download" section with the hash check.
- Versions: repository 0.21.0 in `VERSION` and `CHANGELOG.md`; `mfi-wifi-setup` 0.4.2.

## 0.20.0 - 2026-11-17

- New `tools/bump_version.py`: one command raises the version in every file of a component (`repo`, `mfi-server`, `mfi-controller`, `mfi-wifi-setup`) and adds the dated CHANGELOG entry; `--check` verifies all components are consistent, `--dry-run` previews. Standard library only (ticket T-MWKUB25T).
- `tests/test_bump_version.py`: offline tests on temporary copies.
- `AGENTS.md` rule 3 lists every version file of each component and points to `tools/bump_version.py`.
- `mfi-server/tests/test_version.py` and `mfi-wifi-setup/tests/test_version.py` no longer hard-code the version.
- Versions: repository 0.20.0; `mfi-server` 0.12.1; `mfi-wifi-setup` 0.4.1.

## 0.19.0 - 2026-11-17

- `mfi-wifi-setup` 0.4.0 (ticket W2 bis): Windows build script
  `mfi-wifi-setup/build_windows.cmd` that turns the program into one `.exe`
  (PyInstaller one-file, pinned to `pyinstaller==6.22.3`, source
  https://pypi.org/project/pyinstaller/) with its sha256 file. A person builds it
  on Windows; the `.exe` is never committed.
- `.gitignore`: build output of `mfi-wifi-setup` (`dist/`, `build/`, `*.spec`) is ignored.
- Versions: repository 0.19.0 in `VERSION` and `CHANGELOG.md`; `mfi-wifi-setup` 0.4.0.

## 0.18.0 - 2026-11-17

- `mfi-server` 0.12.0: the web page shows a "New Wi-Fi device?" box after the discovery panel, with a link to the latest GitHub release where the Windows program mFi Wi-Fi Setup can be downloaded. Wi-Fi devices after a reset must be joined to the home network with it before they appear in discovery.

## 0.17.1 - 2026-11-17

- `mfi-server` 0.11.1: adoption works with the real mFi 2.1.11 firmware, whose discovery reply omits fields 21/22/23. The server now reads the model from the platform field (12) and the firmware from the version string (13/14 and 3 are parsed), so the Adopt button appears for a factory-reset mFi even when the "default" flag is absent.
- SSH adoption tells a refused factory password (`auth_failed`) apart from an unreachable device (`connection_failed`); the device page shows a specific message for each.

## 0.17.0 - 2026-11-17

- `mfi-server` 0.11.0: firmware archive and device upgrade. The `mfi-server` image downloads the mFi firmware 2.1.11.1309 at build time from `dl.ubnt.com`, checks its sha256 and serves it read-only to the devices; no firmware file enters the repository.
- Update button for devices with older firmware: confirmation first, one device at a time, result confirmed within 180 seconds. The button stays hidden when the device firmware is current.
- Versions aligned: repository 0.17.0 in `VERSION` and `CHANGELOG.md`; `mfi-server` 0.11.0 in `config.yaml`, `CHANGELOG.md` and `Dockerfile`.

## 0.16.0 - 2026-11-17

- W4 of the Wi-Fi setup epic: `mfi-wifi-setup` 0.3.0, guided setup window
  (version 2). The Wi-Fi network and its password are chosen in the program,
  not on the device page. New core modules `wifi_survey.py` and
  `wifi_configure.py` (no `tkinter`). Version 1 stays as the alternative. The
  controller fields of the device are not sent.
- `mfi-wifi-setup/tests/test_no_tkinter.py` checks the two new core modules too.
- `docs/WIFI-SETUP.md` describes version 2; the encryption and auth suite
  mapping and the device behaviour after `leaveap.cgi` stay UNVERIFIED until the
  device test.
- `mfi-wifi-setup` 0.3.0 (package and changelog).

## 0.15.0 - 2026-11-17

- New program `mfi-wifi-setup/mfi_wifi_setup` (version 1 of the Windows helper for the first Wi-Fi setup of mFi devices): core bridge to the device setup page, device check, messages in Italian and English, controller address memory, and a `tkinter` window started with `python -m mfi_wifi_setup`. The core does not import `tkinter`.
- Offline tests in `mfi-wifi-setup/tests/` (standard library), run by the CI workflow in a new step.
- `mfi-wifi-setup` 0.2.0 (package, changelog, README).

## 0.14.1 - 2026-11-17

- `docs/WIFI-SETUP.md` 0.2.0: the Wi-Fi setup program is a graphical window (`tkinter`, no console) with numbered steps, a device check every 2 s and the controller address to copy; tests stay on a core module that does not import `tkinter`. Tickets W1 and W4 updated.
- `docs/PROTOCOL.md`: the device access point is an open network named `mFi` plus the last 6 hex digits of the MAC, channel 1 (measured).
- `mfi-wifi-setup` 0.1.1 (README and changelog only).

## 0.14.0 - 2026-11-17

- New folder `mfi-wifi-setup/` (0.1.0, not an add-on): Windows helper for the first setup of Wi-Fi devices. Wi-Fi devices without a Wi-Fi configuration serve their setup page only at `https://192.168.2.20` over TLS 1.0, which current browsers refuse. The prototype `prototype/legacy_tls_proxy.py` bridges the browser to that page; verified on an mPower mini (firmware v2.1.11).
- Specification of the program, tests and proposed tickets W1 to W5 in `docs/WIFI-SETUP.md`.
- `docs/PROTOCOL.md`: new section "Wi-Fi setup mode" with measured TLS facts, endpoints, form fields and states; factory state of Wi-Fi models and of the mPort from the Quick Start Guides; new label MEASURED; open questions 15 to 17.
- `docs/ARCHITECTURE.md` and `AGENTS.md`: the new component, and the decision for a Windows program instead of a browser extension.

## 0.13.2 - 2026-11-17

- Test fix (`tests/test_repository.py` 1.5.0): the private data scan now allows `192.168.2.20`, the fixed address where every mFi Wi-Fi device in setup mode serves its setup page. It is a vendor default, the same on every device in the world, not a site address. The exception is exact: other addresses of the same network are still reported (new check in the planted-sample test).

## 0.13.1 - 2026-11-16

- Password of `mfi-server set-password` (standalone mode) follows a new rule: any character is allowed (accents, spaces and symbols included), and the password must have at least 12 characters, one upper-case letter, one lower-case letter, one digit and one special character. The rule is checked in `auth.password_problems`; the error message names the missing parts and never shows the password. Behaviour change, patch release.

## 0.13.0 - 2026-11-16

- Store presentation (epic R2): the two add-ons have distinct names in the store, "mFi Server (new)" and "Ubiquiti mFi Controller (original)", with short descriptions.
- Icons and logos of both add-ons are generated by `tools/make_icons.py` (standard library only, deterministic PNG files).
- User README with a quick start; the technical sections moved to the DOCS.md files.
- English and Italian translations of the Controller option `java_max_memory_mb`.
- Versions aligned: repository 0.13.0 in `VERSION` and `CHANGELOG.md`; `mfi-server` 0.10.1; `mfi-controller` 0.1.4.

## 0.12.0 - 2026-11-16

- mfi-server web page fixed: styled discovery table and panels, discovery lists
  only mFi devices with the right Adopt/Re-point buttons, backup resolved in
  /share and the import error shown on the page.

## 0.11.2 - 2026-11-16

- Repository ready for public release: `SECURITY.md`, `CONTRIBUTING.md` and the CI workflow `.github/workflows/tests.yml`.
- Personal name stored base64-encoded in `tests/test_repository.py` (version 1.4.0), so the public test file does not contain it; new publication checks in the same file.
- English and Italian translations of the `mfi-server` options in `mfi-server/translations/`, checked by `mfi-server/tests/test_translations.py`.
- `README.md` with the CI badge and the installation steps from the add-on store; decision line in `docs/ARCHITECTURE.md`.
- Versions aligned: `mfi-server` 0.9.2 in `config.yaml`, `CHANGELOG.md`, `Dockerfile` and `__version__`; repository 0.11.2 in `VERSION` and `CHANGELOG.md`.

## 0.11.1 - 2026-11-16

- Apache License 2.0 for the repository: full text in `LICENSE`, a `License` section in `README.md` and `mfi-server/README.md`, and a badge in `README.md`. The mFi Controller stays proprietary Ubiquiti software and is not covered by the license.
- `mfi-server` image label `org.opencontainers.image.licenses` set to `Apache-2.0` (it was `NOASSERTION`); new test `mfi-server/tests/test_license.py`.
- Versions aligned: `mfi-server` 0.9.1 in `config.yaml`, `CHANGELOG.md`, `Dockerfile` and `__version__`; repository 0.11.1 in `VERSION` and `CHANGELOG.md`.

## 0.11.0 - 2026-11-16

- Epic D2 of `mfi-server` 0.9.0 (phase 2): adoption of factory-default devices and re-pointing of adopted ones, through the system `ssh` program (`openssh-client` in the add-on image). The device password reaches ssh only through an askpass helper, never on the command line and never in the logs.
- New routes `api/v1/discovery/<mac>/adopt` and `api/v1/devices/<mac>/repoint`, and «Adopt» and «Re-point» buttons in the web page.
- Versions aligned: `mfi-server` 0.9.0 in `config.yaml`, `CHANGELOG.md`, `Dockerfile` and `__version__`; repository 0.11.0 in `VERSION` and `CHANGELOG.md`.

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
