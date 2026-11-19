# Changelog

## 0.17.0 - 2026-11-19

- EPIC-02: inform and devices in `mfi_server_next` — `firmware.py` (firmware_for_model, build_upgrade), `devices.py` (DeviceRegistry, SSH set-adopt with administrator-then-factory retry, devices.json at 0600), `tasks.py` (TaskQueue, mfi-output command, 20-byte wake-up on UDP 3478) and `inform.py` (TNBU decrypt with key trial, handle_inform reply noop/setparam/upgrade/cmd, inform HTTP server on port 6080). The EPIC-01b compatibility fixtures owned by EPIC-02 are now checked instead of pending.
- EPIC-02 hardening: `build_inform_response` returns a clean 500 instead of a traceback on an unexpected error and no longer mutates the reply dict in place; the per-device command queue is bounded (`MAX_QUEUE_PER_MAC`, oldest dropped).

## 0.16.0 - 2026-11-19

- EPIC-01b: synthetic compatibility replay bench in `mfi-server/tests_next` (fixtures in `fixtures/compat/`, helper `compat_replay.py`, test `test_compat_replay.py`); every exchange is PENDING until its owner epic implements the handler; real recordings are added later as more fixtures.

## 0.15.0 - 2026-11-19

- EPIC-01: shared modules of the new server (`mfi_server_next`): `config.load_settings`, `store.Store`, `crypto` (AES-128-CBC and PBKDF2) and `bson.read_bson_stream`, each with tests in `mfi-server/tests_next`. The new package is still not wired in and the Dockerfile keeps copying only `mfi_server`.

## 0.14.0 - 2026-11-19

- EPIC-00: skeleton of the new server package `mfi_server_next` with one stub module per planned module; every public name raises NotImplementedError and no stub imports the old `mfi_server` package. New tests in `mfi-server/tests_next`. The new package is not wired in and the Dockerfile still copies only `mfi_server`, so the running add-on is unchanged.

## 0.13.1 - 2026-11-17

- SSH adoption and re-pointing work with OpenSSH 10 (the base image is Debian 13): the default `ssh_extra_options` no longer lists `ssh-dss`, because OpenSSH 10 has no DSA. `HostKeyAlgorithms` keeps `ssh-rsa`, and `KexAlgorithms` and `Ciphers` keep the old algorithms the devices need.
- Installations that already have `ssh-dss` in their saved options are corrected by a filter: before each ssh call, names in a `+` list that the local ssh does not know are removed. The saved options are not changed.
- When ssh refuses the options (`Bad key types`, `Bad SSH2`, `Unable to negotiate`) the error is `ssh_options_rejected`, and the add-on log shows the first line of the ssh error at WARNING. At start the add-on runs `ssh -G` with the options and logs a WARNING if it refuses them.

## 0.13.0 - 2026-11-17

- Web page restyled in the Home Assistant style (ticket G1): a tab bar (Overview, Devices, Search, Automations) that shows one section at a time via location.hash without reloading; an Overview tab with four tiles (total power, connected, disconnected, outlets on) computed from GET api/v1/devices with no new route; device cards with a model SVG icon, a coloured state label and a pill switch per outlet; an automatic dark theme via @media (prefers-color-scheme: dark). New i18n keys nav_overview, nav_search, tile_power, tile_connected, tile_disconnected, tile_outlets, tile_outlets_value in English and Italian.

## 0.12.1 - 2026-11-17

- Tests: `tests/test_version.py` now derives the expected version from `mfi_server/__init__.py` and compares it with `config.yaml`, `CHANGELOG.md` and the Dockerfile `ARG BUILD_VERSION`, instead of asserting a hard-coded string. Version raised to 0.12.1 with the new `tools/bump_version.py`.

## 0.12.0 - 2026-11-17

- Web page: a new "New Wi-Fi device?" box after the discovery panel links to the latest GitHub release to download the Windows program mFi Wi-Fi Setup. The link opens in a new tab and the page loads nothing from it. New i18n keys `wifi_setup_heading`, `wifi_setup_text`, `wifi_setup_download` in English and Italian.

## 0.11.1 - 2026-11-17

- Adoption with the real mFi 2.1.11 firmware: its UDP discovery reply has no fields 21/22/23, so `ubnt_discovery.parse_reply` now reads field 13 (ESSID), field 14 (wmode byte) and field 3 (version string); the model falls back to the platform (field 12) and the firmware is extracted from the version string. The Adopt button appears for a factory mFi even without the "default" flag.
- `adoption.adopt` accepts a device with an unknown "default" flag when its model/platform is a known mFi model and its MAC is not already stored; otherwise it refuses with `not_factory_default`.
- `ssh_adopt.run_ssh` returns `auth_failed` when the SSH stderr contains "Permission denied" (return code 255), keeping `connection_failed` for other 255 failures.

## 0.11.0 - 2026-11-17

- Firmware archive: the image downloads the mFi firmware 2.1.11.1309 (`M2M/2.1.11.1309/firmware.bin`) at build time from `dl.ubnt.com`, checks its sha256 and serves it read-only from `/opt/mfi-server/firmware`. The firmware file is not in the repository (`Dockerfile`).
- New route `GET /dl/firmware/<path>` on the inform server: it serves only the files of the archive, and answers 404 for anything else.
- Update button in the device page: it always asks for confirmation, is never automatic, and runs one device at a time (409 while another update is running). The result is confirmed when the device reports the new version; otherwise it is marked not confirmed after 180 seconds. The button is not shown when the device firmware is already current.
- New setting `firmware_dir` (`MFI_FIRMWARE_DIR`, default `/opt/mfi-server/firmware`).

## 0.10.2 - 2026-11-16

- Password of `set-password` follows a new rule: any character is allowed (accents, spaces and symbols included), and the password must have at least 12 characters, one upper-case letter, one lower-case letter, one digit and one special character. The rule is checked in `auth.password_problems`; the error names the missing parts and never shows the password. Behaviour change, patch release. `device_ssh_password` has no such rules.
- Versions aligned: `mfi-server` 0.10.2 in `config.yaml`, `CHANGELOG.md`, `Dockerfile` and `__version__`; the version test is renamed to `test_version_is_0_10_2`.

## 0.10.1 - 2026-11-16

- Store name changed to «mFi Server (new)» in `config.yaml` and `Dockerfile` labels (`io.hass.name`, `org.opencontainers.image.title`), with a short store description recommended for new installs.
- Add-on icon and logo generated by `tools/make_icons.py` (standard library only, deterministic).
- Versions aligned: `mfi-server` 0.10.1 in `config.yaml`, `CHANGELOG.md`, `Dockerfile` and `__version__`; the version test is renamed to `test_version_is_0_10_1`.

## 0.10.0 - 2026-11-16

- Web page: Devices and Discovery in panels, styled discovery table, Search
  button styled as a primary button.
- Discovery lists only mFi devices (known / factory default / model / platform);
  other Ubiquiti devices collapse under a details panel; MAC addresses are
  formatted; Adopt only for factory-default devices, Re-point for known ones.
- New GET api/v1/status route and a page message when the backup is missing,
  empty or failed to import; backup_file is resolved against /share.

## 0.9.2 - 2026-11-16

- English and Italian translations of the add-on options in `translations/en.yaml` and `translations/it.yaml`, one name and one description for each option; checked by the new test `tests/test_translations.py`.
- Versions aligned: `mfi-server` 0.9.2 in `config.yaml`, `CHANGELOG.md`, `Dockerfile` and `__version__`.

## 0.9.1 - 2026-11-16

- Apache License 2.0: the license text is in the repository `LICENSE` file, and the `License` section of `README.md` points to it. The image label `org.opencontainers.image.licenses` changes from `NOASSERTION` to `Apache-2.0` (`Dockerfile`); the stale comment about the missing LICENSE file is removed.
- New test `tests/test_license.py` checks the key phrases of the license and the image label.
- Versions aligned: `mfi-server` 0.9.1 in `config.yaml`, `CHANGELOG.md`, `Dockerfile` and `__version__`.

## 0.9.0 - 2026-11-16

- Adoption of new devices through the system `ssh` program: `adoption.py` sends `set-adopt` to a factory-default device found by discovery, with a new authkey (16 random bytes, hex). The record is saved as `adopting` before ssh runs, and becomes `adopt_failed` on failure.
- Re-pointing of adopted devices: `repoint` sends `set-adopt` with the authkey already stored, so the device informs this server again. It needs the device SSH credentials.
- New module `ssh_adopt.py`: ssh runs with an argument list, never through a shell. The password reaches ssh only through an SSH_ASKPASS helper in a temporary folder that is removed afterwards. Only the allowed `ssh -o` keys are accepted. The device host key is not checked (`StrictHostKeyChecking=no`), so run it on the isolated device network only.
- The image installs `openssh-client` (`Dockerfile`).
- New routes `api/v1/discovery/<mac>/adopt` and `api/v1/devices/<mac>/repoint`. The web page has «Adopt» and «Re-point» buttons, each with a confirmation first.
- New options `server_address` (IPv4; empty means the local address toward the device), `device_ssh_username`, `device_ssh_password` and `ssh_extra_options` (allowed `ssh -o` keys only). The default of `ssh_extra_options` is UNVERIFIED (question 12 in `docs/PROTOCOL.md`: whether a modern ssh accepts the legacy algorithms of the devices).
- Versions aligned: `mfi-server` 0.9.0 in `config.yaml`, `CHANGELOG.md`, `Dockerfile` and `__version__`.

## 0.8.0 - 2026-11-16

- UDP discovery on port 10001: new module `ubnt_discovery` (`parse_reply` and `Scanner`), a scan at startup, and the routes `api/v1/discovery` (list) and `api/v1/discovery/scan` (scan now).
- Host network: `host_network: true` in `config.yaml`; the `ports` and `ports_description` blocks are removed, because with the host network the ports open directly.
- New setting and add-on option `ingress_peer` (default empty in the add-on options, `172.30.32.2` in the settings): the add-on mode check uses `settings.ingress_peer` and logs a WARNING with the refused IP address.
- «Discovered devices» section in the web page; «Network» section in `DOCS.md`.
- Versions aligned: `mfi-server` 0.8.0 in `config.yaml`, `CHANGELOG.md`, `Dockerfile` and `__version__`.

## 0.7.0 - 2026-11-16

- Standalone examples in `examples/`: `settings.example.json` (all 13 keys of `FILE_KEYS`, default values, no secrets), `mfi-server.env.example` (one line per `MFI_*` variable), `docker-compose.yml` (ports only on the isolated device network) and `mfi-server.service` (systemd unit with `DynamicUser` and a read-only system).
- New section «Run without Home Assistant» in `README.md` with the table of environment variables, and a pointer to it from `DOCS.md`.
- New test `tests/test_examples.py` keeps the examples aligned with `FILE_KEYS` and `ENV_NAMES`, checks the ports and data paths, and scans the examples for private data.
- Versions aligned: `mfi-server` 0.7.0 in `config.yaml`, `CHANGELOG.md`, `Dockerfile` and `__version__`; the version test is renamed to `test_version_is_0_7_0`.

## 0.6.0 - 2026-11-16

- Automations page in the web UI: list with enable/disable, run and delete; YAML editor with validation errors shown one per line with their path; run history (last 5 runs). Shared i18n and DOM helpers moved to `web/common.js`, loaded by both pages. New `web/automations.html` and `web/automations.js`, served from `STATIC_FILES`.

## 0.5.0 - 2026-11-15

- Automation engine in the Home Assistant format (level 1), in pure Python, standard library only:
  - `yaml_lite.py`: reduced YAML reader for automation files (block mappings and lists, simple scalars, quoted strings, inline lists, comments). Anchors, tags, block scalars, inline maps and duplicate keys are rejected with the line number.
  - `automation_model.py`: normalizes the old Home Assistant keys (`trigger`, `condition`, `action`, `platform`, `service`), validates each automation with the path in every error message, and parses durations.
  - `automation_engine.py`: triggers `state`, `numeric_state`, `time` and `time_pattern`, with `for`; conditions `state`, `numeric_state`, `time`, `and`, `or` and `not`; actions `switch.turn_on`, `switch.turn_off`, `switch.toggle`, `delay`, `if` and `choose`; modes `single`, `restart`, `queued` and `parallel`; traces of the last 5 runs. The engine has no thread of its own: the caller ticks it once a second.
  - `automation_store.py`: `automations.json` in the data folder, written atomically with mode 0600; a damaged file is never overwritten.
- Web API routes `api/v1/automations*`: list, get, create, replace, delete, trigger, enable, traces, validate and import.
- Wiring in `__main__.py`: measurements become entity changes (`switch.mfi_<mac>_<port>`, `sensor.mfi_<mac>_<port>_<tag>`), and the engine ticks every second. Without automations the engine does nothing.
- Not supported yet (levels 2 and 3): `template` (`{{ }}`), `sun`, `mqtt`, `repeat`, `wait_*`, `variables` and `event`; they are rejected with `not supported yet`.

## 0.4.0 - 2026-11-15

- Web page of `mfi-server`, served by the same HTTP server as the API: `web/index.html`, `app.js`, `style.css` and the English and Italian texts in `web/i18n/`. It works inside the Home Assistant ingress (the "mFi" entry in the sidebar) and in standalone mode, with the login of 0.3.0.
- Language selector (English or Italian): the browser language is the default, and the choice is saved in `localStorage`.
- Device list refreshed every 10 seconds, outlet switches (ON/OFF), measurements, and a 24-hour history chart drawn in SVG.
- `api.py` serves the static files with `Content-Security-Policy` and `X-Content-Type-Options` headers. File names are matched against a fixed list, so no part of the request path reaches the file system.

## 0.3.0 - 2026-11-15

- HTTP JSON API (`api.py`): health, login and logout with a session cookie (`mfi_session`), devices with their ports and latest values, output commands, and measurement history. Routes are found by the `api/v1/` part of the path, so the Home Assistant ingress prefix is accepted.
- History of the measurements in sqlite3 (`history.py`), kept for 30 days by default and purged every hour; it is a listener of Measurements, so every new value is recorded.
- Login for the standalone mode (`auth.py`): password hashed with pbkdf2_sha256 and a random salt, set with the `set-password` subcommand (asked twice, at least 12 characters, never on the command line). The login is off by default: until a password is set the API answers 503 `password_not_set`. Failed logins are limited to 5 per minute per address (429).
- Add-on mode: the API accepts requests only from the Home Assistant ingress address (172.30.32.2) and needs no login.
- `OutputControl` (`control.py`) now sends the wake-up UDP packet when the device's connect_request address is known, so an output changes at once instead of at the next inform.
- New settings `web_port` (`MFI_WEB_PORT`, default 8099) and `history_days` (`MFI_HISTORY_DAYS`, default 30, from 1 to 3650).
- `config.yaml` with ingress: `ingress: true`, `ingress_port: 8099`, panel icon and title; port 8099 is not added to `ports`.

## 0.2.0 - 2026-11-15

- MQTT 3.1.1 client in pure Python (`mqtt.py`): QoS 0 and 1, retained last will, reconnect with a growing delay; standard library only.
- Home Assistant MQTT discovery: a switch for each outlet output, and sensors for power, voltage, current, power factor and energy of each outlet.
- MQTT bridge (`bridge.py`): retained states and availability, retained `online` status, periodic republishing of states every 15 s and a full re-subscribe and re-publish after each (re)connection, and output commands (`output/set` with ON or OFF) queued for the next regular inform of the device.
- MQTT settings (`mqtt_host`, `mqtt_port`, `mqtt_username`, `mqtt_password`, `mqtt_topic_prefix`, `mqtt_discovery_prefix`) and the Supervisor MQTT service in add-on mode (`services: mqtt:want`).
- MQTT is optional in standalone mode: without a broker host the bridge does not start.

## 0.1.0 - 2026-11-15

- First version of the phase 2 add-on.
- Pure Python AES-128 and BSON reader.
- Inform packets: decrypt, compressed payloads, same IV in the response.
- Device store `devices.json` with schema 1.
- Import of keys and ports from `.unf` backups.
- Device states (a device is lost after 120 s without an inform).
- `mfi-output` command queue.
- Wake-up packet builder.
- Measurements with energy counter compensation.
- HTTP inform server.
- Command line: `decode` and `import-backup`.
- Never sends a factory reset.
