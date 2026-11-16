# mFi Server

## Status

In progress. Not yet tested with a real device. Home Assistant entities come
through MQTT discovery (a broker is needed). No adoption of new devices. A
wake-up packet is sent to a device when its address is known (from its inform
connect_request), UNVERIFIED on a real device.

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

The ways to start it, the password, backups, MQTT and the data folder are in the [Run without Home Assistant](README.md#run-without-home-assistant) section of the README.

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
| `MFI_WEB_PORT` | 8099 |
| `MFI_HISTORY_DAYS` | 30 |

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

A command is queued for the next regular inform of the device. When the device's
wake-up address is known, a wake-up packet is also sent at once, so the switch
changes at once. Not verified on a real device.

### Security

The broker user and password travel without TLS (TLS is out of scope). Keep the
broker on the isolated network too, next to the devices.

## Web API

The JSON API listens on port 8099 (`web_port`, variable `MFI_WEB_PORT`). Routes are
found by the `api/v1/` part of the path, so the Home Assistant ingress prefix is accepted.

- Add-on mode: open the mFi panel from the Home Assistant sidebar. There is no login;
  only the Supervisor ingress address (172.30.32.2) is served, other addresses get 403.
- Standalone mode: a session is needed. Start one with `POST api/v1/login` and a JSON
  body `{"password": "..."}`: the answer sets the `mfi_session` cookie (204). Set the
  password with `python3 -m mfi_server set-password --data DIR`: it is asked twice,
  it must be at least 12 characters, and it is never given on the command line.
  A wrong password answers 401; five failures in 60 seconds from one address answer 429.
- Standalone mode: until the password is set, every route except `api/v1/health` answers 503
  `password_not_set`.

| Route | Method | Use |
|---|---|---|
| `api/v1/health` | GET | status and version, no login |
| `api/v1/login` | POST | start a session (standalone mode) |
| `api/v1/logout` | POST | end the session |
| `api/v1/devices` | GET | devices, ports and latest values |
| `api/v1/devices/<mac>` | GET | one device, same fields; unknown MAC answers 404 |
| `api/v1/devices/<mac>/ports/<port>/output` | POST | body `{"value": 0}` or `{"value": 1}`; 202 when queued |
| `api/v1/history` | GET | `mac`, `sensor_id`, `tag`, `from` and `to` (milliseconds); returns `points` as `[time_ms, value]` |

History is kept for `history_days` (default 30) in `history.sqlite3` inside the data folder.

Security warning: never expose 8099/tcp on the internet. Standalone mode has no built-in
HTTPS: for remote access put a reverse proxy with TLS in front of it, on the isolated network.

## Web page

The web page is served by the same server as the API, on port 8099 (`web_port`, variable `MFI_WEB_PORT`). It uses hand-written static files (HTML, CSS and JavaScript): there are no build tools and no resources loaded from the Internet.

- Add-on mode: open the mFi panel from the Home Assistant sidebar (ingress). There is no login: the page is served only through the ingress.
- Standalone mode: open `http://<host>:8099/` in the browser. If the password is not set yet, the page asks you to set it with `set-password` (see Web API). When the password is set, the login form appears and, after a successful login, the session cookie `mfi_session` is used.

The page is bilingual (English and Italian). The language selector is at the top right. The default language comes from the browser: Italian when the browser language starts with `it`, English otherwise. The choice of the user is saved in the browser and restored at the next visit.

The page shows:

- the device list: name, model, state and last contact;
- the ON/OFF switch of each outlet;
- the measurements of each outlet: power, voltage, current, power factor and energy;
- a chart of the last 24 hours, drawn as SVG, with the minimum and maximum values.

Security warning: never expose 8099/tcp to the internet. The page has no built-in HTTPS (see Web API).

## Automations

Automations use the same format as Home Assistant automations (`triggers`, `conditions`,
`actions`, and the old keys `trigger`, `condition`, `action`, `platform` and `service` are
also accepted). They are optional: without any automation the engine does nothing.
Automations are stored in `automations.json` inside the data folder.
Each automation has an `id` of 1 to 64 characters, using only lowercase letters, digits and `_`. `mode` defaults to `single`, and `enabled` defaults to `true`.

Example:

```yaml
id: evening_outlet
enabled: true
mode: single
triggers:
  - trigger: numeric_state
    entity_id: sensor.mfi_aabbccddeeff_1_active_pwr
    above: 1500
    for: "00:00:30"
conditions:
  - condition: time
    after: "18:00:00"
    before: "23:00:00"
actions:
  - action: switch.turn_on
    target:
      entity_id: switch.mfi_aabbccddeeff_2
  - delay: "00:05:00"
  - action: switch.turn_off
    target:
      entity_id: switch.mfi_aabbccddeeff_2
```

Supported and not supported compared with Home Assistant:

| Area | Supported | Not supported yet |
|---|---|---|
| Triggers | `state`, `numeric_state`, `time`, `time_pattern` | `{{ }}` templates, `sun`, `mqtt`, `event` |
| Conditions | `state`, `numeric_state`, `time`, `and`, `or`, `not` | `{{ }}` templates, `sun` |
| Actions | `switch.turn_on`, `switch.turn_off`, `switch.toggle`, `delay`, `if`, `choose` | `{{ }}` templates, `repeat`, `wait_template`, `wait_for_trigger`, `variables`, `event` |
| Modes | `single`, `restart`, `queued`, `parallel` | none |

A value that is not supported yet is rejected with `not supported yet` and the path of the field.

Routes (found by the `api/v1/` part of the path, same access rules as the other routes):

| Route | Method | Use |
|---|---|---|
| `api/v1/automations` | GET | list of the automations |
| `api/v1/automations` | POST | create one automation; 409 if the id exists, 400 with `details` if invalid |
| `api/v1/automations/<id>` | GET | one automation; 404 if unknown |
| `api/v1/automations/<id>` | PUT | replace one automation; the `id` in the body must match the URL; 400 if invalid |
| `api/v1/automations/<id>` | DELETE | delete one automation; 204, 404 if unknown |
| `api/v1/automations/<id>/trigger` | POST | run the actions now (conditions are still checked); 202, 404 if unknown |
| `api/v1/automations/<id>/enable` | POST | body `{"enabled": true}` or `{"enabled": false}`; 200, 400 if the body is wrong, 404 if unknown |
| `api/v1/automations/<id>/traces` | GET | last 5 runs as `{"traces": [...]}`; 404 if unknown |
| `api/v1/automations/validate` | POST | body `{"yaml": "..."}`; 200 with the normalized automations, 400 with `details` |
| `api/v1/automations/import` | POST | body `{"yaml": "..."}`; 200 `{"imported": [ids]}`, 400 with `details` |

### Automations web page

Open the mFi panel from the Home Assistant sidebar, or in standalone mode open `http://<host>:8099/` and log in. Follow the "Automations" link in the header; the link back to the devices is "Devices". The page uses relative addresses, so it also works under the ingress prefix. The texts are in English and Italian, with the same language selector as the devices page.

The list shows the alias (or the id), the mode, and a switch to enable or disable each automation. Next to it are the **Run** button, which runs the actions at once (the conditions are still checked), and the **Delete** button, which asks for confirmation first.

The YAML editor at the bottom accepts one automation or a list of automations. The buttons work as follows:

- **Check** validates the text and shows the errors, one per line, each with its path.
- **Save** creates a new automation, updates an existing one with the same id, or imports a list of automations.
- **New** inserts a ready example, to be edited before saving.

The history shows the last 5 runs of an automation, each with its start, its end, its result and its steps. The examples in this section use the entity names of the outlets, for example `switch.mfi_02aabbccdd01_1`.

Keep the devices on an isolated network without internet access.
- Never expose 6080/tcp, 3478/udp or 8099/tcp to the internet.
- Inform packets without encryption are refused with HTTP 400.
- The server never sends a factory reset to a device.
- The add-on runs as root because the Supervisor `/data` volume belongs to root.

## Network

The add-on uses the network of the host (`host_network`), so its ports open directly on the Home Assistant OS host, without a Docker port mapping.

| Port | Protocol | Use |
|---|---|---|
| 6080 | tcp | Inform: mFi devices report to the server (HTTP) |
| 3478 | udp | Wake-up packets sent to the devices |
| 8099 | tcp | Web API and web page |
| 10001 | udp | Outgoing discovery: the server asks the devices who they are, broadcast to 255.255.255.255 and multicast to 233.89.188.1 |

With the host network, port 8099 is reachable from the whole LAN, not only from Home Assistant. In add-on mode the server answers only the requests that come from the ingress peer, the address of the Home Assistant ingress (default 172.30.32.2). Requests from any other address get 403.

If the page answers 403, read the server log: the server writes a WARNING with the address that made the request. Put that address in the `ingress_peer` option of the add-on. In standalone mode, set the variable `MFI_INGRESS_PEER`, or the key `ingress_peer` in `settings.json`.

Keep the devices on an isolated network without internet access. Never expose 6080/tcp, 3478/udp or 8099/tcp to the internet.

## Ports

| Port | Protocol | Use |
|---|---|---|
| 6080 | tcp | Inform: mFi devices report to the server (HTTP) |
| 3478 | udp | Wake-up packets to the devices |
| 8099 | tcp | Web API (JSON); never expose it to the internet |
