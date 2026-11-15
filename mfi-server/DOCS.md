# mFi Server

## Status

In progress. Not yet tested with a real device. Home Assistant entities come
through MQTT discovery (a broker is needed). No adoption of new devices, and no
wake-up packet is sent yet.

## Install on Home Assistant OS

Copy the `mfi-server` folder into the local apps folder, as for `mfi-controller`:
the `local_apps` share of the Samba app, or `/addons` in the Advanced SSH & Web
Terminal app. Reload the store, then install the app.

## Options

| Option | Meaning |
|---|---|
| `backup_file` | Path of an old controller backup, for example `/share/mfi/backup.unf`. Imported at every start; the import is idempotent. |
| `log_level` | `debug`, `info`, `warning` or `error`. |
| `mqtt_topic_prefix` | Prefix of the MQTT topics. Default `mfi`. |
| `mqtt_discovery_prefix` | Prefix of the Home Assistant discovery topics. Default `homeassistant`. |

## Import the keys from a controller backup

Copy the `.unf` file into `/share/mfi/`, set `backup_file` and restart the app.

Or run, from the folder that contains `mfi_server`:

```
python3 -m mfi_server import-backup FILE --data DIR
```

The command prints only how many devices and ports were imported. The keys end up
in `devices.json` inside the data folder: protect that folder and never publish it.

## Run as a standalone program

```
cd mfi-server
python3 -m mfi_server --data ./data
```

An optional file `data/settings.json` may hold the same keys as the options.

| Variable | Default |
|---|---|
| `MFI_INFORM_PORT` | 6080 |
| `MFI_WAKEUP_PORT` | 3478 |
| `MFI_BIND_ADDRESS` | 0.0.0.0 |
| `MFI_BACKUP_FILE` | empty (not set) |
| `MFI_LOG_LEVEL` | info |
| `MFI_MQTT_HOST` | empty (no broker, the MQTT bridge does not start) |
| `MFI_MQTT_PORT` | 1883 |
| `MFI_MQTT_USERNAME` | empty |
| `MFI_MQTT_PASSWORD` | empty |
| `MFI_MQTT_TOPIC_PREFIX` | mfi |
| `MFI_MQTT_DISCOVERY_PREFIX` | homeassistant |

Precedence: variable, then file, then default.

## Decode a captured packet

```
python3 -m mfi_server decode FILE --key-file KEYFILE
```

The key is read from a file. It is never given on the command line.

## MQTT and Home Assistant

The server publishes the devices and their measurements to an MQTT broker, and
Home Assistant creates the entities with MQTT discovery. MQTT is optional:
without a broker the bridge does not start and the server works as before.

### Add-on mode

The add-on asks the Supervisor for the MQTT service (`services: mqtt:want`).
Install an MQTT broker app, for example Mosquitto: Home Assistant passes the
host, port, user and password to mfi-server, so nothing has to be typed. The
options change only the topic names:

- `mqtt_topic_prefix` (default `mfi`): prefix of the state, command and availability topics.
- `mqtt_discovery_prefix` (default `homeassistant`): keep the default unless you changed it in the MQTT integration.

### Standalone mode

Set the `MFI_MQTT_*` variables of the table above. `MFI_MQTT_HOST` is the switch:
when it is empty there is no broker and the bridge does not start.

### Topics

| Topic | Payload |
|---|---|
| `mfi/status` | `online` (retained); `offline` is the last will |
| `mfi/<mac>/availability` | `online` or `offline` (retained) |
| `mfi/<mac>/<port>/<tag>` | last measurement (retained); `ON` or `OFF` for `output` |
| `mfi/<mac>/<port>/output/set` | send `ON` or `OFF` to switch an outlet |

A command is not sent to the device at once: the bridge does not wake the device
up. It waits in the queue for the next regular inform of the device, so the
switch changes with a delay. The delay is UNVERIFIED on a real device.

### Security

The broker user and password travel without TLS (TLS is out of scope). Keep the
broker on the isolated network too, next to the devices.

## Security

- Keep the devices on an isolated network without internet access.
- Never expose 6080/tcp or 3478/udp to the internet.
- Inform packets without encryption are refused with HTTP 400.
- The server never sends a factory reset to a device.
- The add-on runs as root because the Supervisor `/data` volume belongs to root.

## Ports

| Port | Protocol | Use |
|---|---|---|
| 6080 | tcp | Inform: mFi devices report to the server (HTTP) |
| 3478 | udp | Wake-up packets to the devices |
