# mFi Server

Our own controller for Ubiquiti mFi devices: the devices report to this server
directly, without the 2015 mFi Controller.

## Status

In progress. Standard library only. Not yet tested with a real device or on
Home Assistant OS.

## Features

- Encrypted inform packets (AES-128-CBC).
- Keys read from `.unf` controller backups.
- Device states and outlet commands.
- Measurements.
- Never sends a factory reset to a device.
- MQTT discovery for Home Assistant (optional in standalone mode).
- JSON web API on port 8099, and measurement history in `history.sqlite3` (30 days by default).
- Web page on port 8099, served by the same server: hand-written HTML, CSS and JavaScript, English and Italian, no build tools.
- Automations in the Home Assistant format, run by our own engine (optional, see DOCS.md).

### Home Assistant entities

With MQTT, each outlet gets:

- a switch for its output (ON and OFF);
- sensors for power (W), voltage (V), current (A), power factor and energy (Wh).

Entity names use the port label, for example `Port 1 Power`.

## Requirements

Python 3.11 or later. No extra packages.

## Run without Home Assistant

mFi Server also runs as a standalone program, without Home Assistant. Choose one of the three ways below. The Python way needs Python 3.11 or later. Docker and systemd run the same code.

### Python

```
git clone <repository URL>
cd oce-mfi-home-assistant/mfi-server
python3 -m mfi_server --data ./data
```

The `--data` folder keeps all the state (see [Data folder](#data-folder)). Set the password before using the web page (see [Set the password](#set-the-password)).

### Docker Compose

```
cd oce-mfi-home-assistant/mfi-server/examples
docker compose up -d
```

`docker-compose.yml` builds the image from the parent folder and keeps the data in `./data`, next to the file. To set options, copy `mfi-server.env.example` to `mfi-server.env`, fill in the variables, and uncomment the `env_file` block in the compose file.

Set the password inside the container:

```
docker compose run --rm mfi-server python3 -m mfi_server set-password --data /data
```

### systemd

```
sudo mkdir -p /opt/mfi-server
sudo cp -r mfi-server/mfi_server /opt/mfi-server/
sudo cp mfi-server/examples/mfi-server.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mfi-server
```

The unit runs `/usr/bin/python3 -m mfi_server --data /var/lib/mfi-server`. It uses `DynamicUser=yes`, so there is no fixed user. Read the logs with `journalctl -u mfi-server`.

UNVERIFIED: the service user is dynamic. Run `set-password` and `import-backup` as that user, not as root, and check the ownership of the files in `/var/lib/mfi-server` afterwards.

### Set the password

```
python3 -m mfi_server set-password --data ./data
```

The password is asked twice. It must be at least 12 characters and is never given on the command line. Until it is set, every route except `api/v1/health` answers 503 `password_not_set`.

### Import a controller backup

```
python3 -m mfi_server import-backup FILE --data ./data
```

The command prints only how many devices and ports were imported. It can be run again.

### MQTT (optional)

Without a broker nothing is required: when `MFI_MQTT_HOST` is empty the MQTT bridge does not start. To create Home Assistant entities, set `MFI_MQTT_HOST` and the other `MFI_MQTT_*` variables. Home Assistant MQTT discovery then creates the entities. The broker user and password travel without TLS, so keep the broker on the isolated network too.

### Settings

Each setting can come from an environment variable, from `settings.json` in the data folder (same keys, see `examples/settings.example.json`), or from its default. Precedence: variable, then file, then default.

| Variable | Default | Meaning |
|---|---|---|
| `MFI_INFORM_PORT` | 6080 | TCP port where the devices send inform packets (HTTP) |
| `MFI_WAKEUP_PORT` | 3478 | UDP port used for wake-up packets to the devices |
| `MFI_BIND_ADDRESS` | 0.0.0.0 | Address the server listens on |
| `MFI_BACKUP_FILE` | empty (not set) | Path of a controller `.unf` backup, imported at every start |
| `MFI_LOG_LEVEL` | info | `debug`, `info`, `warning` or `error` |
| `MFI_MQTT_HOST` | empty (no broker, the MQTT bridge does not start) | MQTT broker host |
| `MFI_MQTT_PORT` | 1883 | MQTT broker port |
| `MFI_MQTT_USERNAME` | empty | MQTT user name |
| `MFI_MQTT_PASSWORD` | empty | MQTT password, never logged |
| `MFI_MQTT_TOPIC_PREFIX` | mfi | Prefix of the MQTT topics |
| `MFI_MQTT_DISCOVERY_PREFIX` | homeassistant | Prefix of the Home Assistant discovery topics |
| `MFI_WEB_PORT` | 8099 | TCP port of the web page and the JSON API |
| `MFI_HISTORY_DAYS` | 30 | Days of measurement history kept |
| `MFI_INGRESS_PEER` | 172.30.32.2 | Add-on mode: only requests from this address (Home Assistant ingress) are served; others get 403 |

### Data folder

The data folder is `./data` (Python), `./data` next to the compose file, mounted as `/data` in Docker, and `/var/lib/mfi-server` with systemd. It holds `devices.json`, `automations.json`, `auth.json` and `history.sqlite3`. `devices.json` contains the device keys and `auth.json` contains the password hash: protect the folder and never publish it.

To update, stop the server, replace the code, and start it again: the data folder is kept. To back up, stop the server, copy the whole folder to a private place, and start the server again.

## Documentation

- [DOCS.md](DOCS.md)
- [CHANGELOG.md](CHANGELOG.md)
- [../docs/PROTOCOL.md](../docs/PROTOCOL.md)

## Security

Keep the mFi devices on an isolated network. Never expose ports 6080, 3478 or
8099 to the internet.

## Credits

- Specification in `docs/PROTOCOL.md`, written from the decompiled mFi Controller
  2.1.11. No vendor code is copied.
- [mcrute/ubntmfi](https://github.com/mcrute/ubntmfi) (BSD-3-Clause), used as a
  reference model. No code is copied.

## License

To be decided.
