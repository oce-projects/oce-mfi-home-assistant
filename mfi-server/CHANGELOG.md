# Changelog

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
