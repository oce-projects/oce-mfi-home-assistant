# Changelog

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
