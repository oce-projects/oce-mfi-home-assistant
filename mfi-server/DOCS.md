# mFi Server

## Quick start

1. If you want the entities in Home Assistant, install the Mosquitto broker app.
2. Copy the backup of the old controller (`.unf` file) into `/share`.
3. Write its file name in the `backup_file` option (for example `backup.unf`).
4. Start the app.
5. Open "mFi" in the sidebar, open the Search tab and press Search, then press Re-point on your devices.

Wi-Fi devices after a reset need the Windows program mFi Wi-Fi Setup first. The mFi page has a download box for it, which links to the latest release on GitHub.

## Status

In progress. Not yet tested with a real device. Home Assistant entities come
through MQTT discovery (a broker is needed). Adoption and re-pointing by SSH are in
place but not yet tested on a real device (see [Adopting and re-pointing devices](#adopting-and-re-pointing-devices)). A
wake-up packet is sent to a device when its address is known (from its inform
connect_request), UNVERIFIED on a real device.

## Install on Home Assistant OS

Add the repository `https://github.com/oce-projects/oce-mfi-home-assistant` in
the app store (Settings, Apps, App store, menu, Repositories), then install
`mFi Server (new)` from the store. The first build takes a few minutes.

To test a local change, copy the `mfi-server` folder into the local apps folder,
as for `mfi-controller`: the `local_apps` share of the Samba app, or `/addons` in
the Advanced SSH & Web Terminal app. Reload the store, then install the app.

## Options

| Option | Meaning |
|---|---|
| `backup_file` | Path of an old controller backup, for example `/share/mfi/backup.unf`. A bare file name (for example `backup.unf`) is looked up in `/share`. Imported at every start; the import is idempotent. |
| `log_level` | `debug`, `info`, `warning` or `error`. |
| `mqtt_topic_prefix` | Prefix of the MQTT topics. Default `mfi`. |
| `mqtt_discovery_prefix` | Prefix of the Home Assistant discovery topics. Default `homeassistant`. |
| `ingress_peer` | Add-on mode: the only address served by the web page (Home Assistant ingress). Default `172.30.32.2`. See [Network](#network). |
| `server_address` | IPv4 address of the host where mfi-server runs. Empty = automatic. See [Adopting and re-pointing devices](#adopting-and-re-pointing-devices). |
| `device_ssh_username` | Administrator name of the old controller, used to re-point devices. |
| `device_ssh_password` | Administrator password of the old controller, used to re-point devices. Never shown in the API or in the logs. |
| `ssh_extra_options` | Extra SSH algorithm options. The default is UNVERIFIED, see [Adopting and re-pointing devices](#adopting-and-re-pointing-devices). |

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
| `MFI_INGRESS_PEER` | 172.30.32.2 |
| `MFI_SERVER_ADDRESS` | empty (automatic) | Address of the server in the inform URL, see [Adopting and re-pointing devices](#adopting-and-re-pointing-devices) |
| `MFI_DEVICE_SSH_USERNAME` | empty | SSH user of the old controller, used to re-point devices |
| `MFI_DEVICE_SSH_PASSWORD` | empty | SSH password of the old controller, never logged or shown in the API |
| `MFI_SSH_EXTRA_OPTIONS` | see [Adopting and re-pointing devices](#adopting-and-re-pointing-devices) | Extra SSH algorithm options (the default is UNVERIFIED) |
| `MFI_FIRMWARE_DIR` | /opt/mfi-server/firmware | Folder of the firmware archive, see [Firmware](#firmware) |

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
  only the address set in the `ingress_peer` option (default 172.30.32.2, see [Network](#network)) is served, other addresses get 403.
- Standalone mode: a session is needed. Start one with `POST api/v1/login` and a JSON
  body `{"password": "..."}`: the answer sets the `mfi_session` cookie (204). Set the
  password with `python3 -m mfi_server set-password --data DIR`: it is asked twice,
  it must be at least 12 characters, include one upper-case letter, one lower-case letter, one digit and one
  special character (any character that is not a letter or a digit), and it is never given on the command line.
  Any character is allowed, accents, spaces and symbols included. The `device_ssh_password` option has no such
  rules: it must match the password of the device.
  A wrong password answers 401; five failures in 60 seconds from one address answer 429.
- Standalone mode: until the password is set, every route except `api/v1/health` answers 503
  `password_not_set`.

| Route | Method | Use |
|---|---|---|
| `api/v1/health` | GET | status and version, no login |
| `api/v1/login` | POST | start a session (standalone mode) |
| `api/v1/logout` | POST | end the session |
| `api/v1/status` | GET | import status of the controller backup, as `{"backup": {...}}` with the keys `configured`, `file`, `devices` and `error`; same access rules as the other routes (not public like `api/v1/health`) |
| `api/v1/devices` | GET | devices, ports and latest values |
| `api/v1/devices/<mac>` | GET | one device, same fields; unknown MAC answers 404 |
| `api/v1/devices/<mac>/ports/<port>/output` | POST | body `{"value": 0}` or `{"value": 1}`; 202 when queued |
| `api/v1/history` | GET | `mac`, `sensor_id`, `tag`, `from` and `to` (milliseconds); returns `points` as `[time_ms, value]` |
| `api/v1/discovery` | GET | devices found on the network by the last UDP discovery scan, as `{"devices": [...]}`; each has `known` (already in the server) |
| `api/v1/discovery/scan` | POST | run a new scan now (3 s by default) and return the devices found; 409 `scan_in_progress` if a scan is already running |
| `api/v1/discovery/<mac>/adopt` | POST | adopt a factory-default device over SSH; 202 `{"result": "sent"}` |
| `api/v1/devices/<mac>/repoint` | POST | re-point a known device over SSH; optional body `{"ip": "..."}`; 202 |

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
- a chart of the last 24 hours, drawn as SVG, with the minimum and maximum values;
- a message at the top of the page when the backup in `backup_file` fails to import (with the error), has no devices, or, when no backup is set and there are no devices, asks to set `backup_file`;
- a section of the devices found on the network by UDP discovery (port 10001, see [Network](#network)), with a search button that starts a new scan. The main table shows only the mFi devices, with name, MAC (with colons), IP, model, firmware and a state: factory default, on this server, or not on this server. Adopt is shown only for factory-default devices, and Repoint only for devices already on this server. The other Ubiquiti devices found are listed below the table in a closed section, without buttons. The server also scans once at startup. The results are kept in memory only.
- a box "New Wi-Fi device?" with a link to the latest GitHub release, where the Windows program mFi Wi-Fi Setup can be downloaded: Wi-Fi devices after a reset must be joined to the home network with it before they appear in discovery. The link opens in a new tab and the page loads nothing from it.

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

## Adopting and re-pointing devices

An mFi device reaches a server in one of two ways:

- **Adoption**: a device that is factory new or was reset is adopted. The server sets the device's inform address and a new authentication key over SSH.
- **Re-pointing**: a device already adopted by an old controller is pointed at the new server over SSH. The device keeps the key it already has, so it does not have to be reset.

Adopt a device from the discovery table of the web page with the **Adopt** button, or with `POST api/v1/discovery/<mac>/adopt`. Re-point a device with the **Repoint** button in the device list (for devices that are not connected), or with `POST api/v1/devices/<mac>/repoint`; the body may hold `{"ip": "..."}` to give the device address, otherwise the address from the last discovery scan is used.

Adoption is refused with 409 `not_factory_default` when the discovery scan does not report the device as factory default. Re-pointing needs the device to be known (it must have an authentication key) and the two `device_ssh_*` options to be set.

### Server address

The address written into the device is the address of the machine where mfi-server runs: the IP of the Home Assistant host, or of the network card of the PC where the server runs. It is **not** the address of the old controller. Set it with the `server_address` option. Empty means automatic: the server uses the address of the local network card that routes to the device. The device then informs at `http://<address>:6080/inform`.

### Options

| Option | Meaning |
|---|---|
| `server_address` | IPv4 address of the host where mfi-server runs. Empty = automatic. |
| `device_ssh_username` | Administrator name of the old controller. Used only to re-point devices. |
| `device_ssh_password` | Administrator password of the old controller. Used only to re-point devices. It is never shown in the API or in the logs. |
| `ssh_extra_options` | Extra SSH algorithm options, as `KEY=value` pairs separated by `;`. Allowed keys: `KexAlgorithms`, `HostKeyAlgorithms`, `Ciphers`, `MACs`, `PubkeyAcceptedAlgorithms`, `PubkeyAcceptedKeyTypes`. Other text is rejected. Default: `KexAlgorithms=+diffie-hellman-group1-sha1,diffie-hellman-group14-sha1;HostKeyAlgorithms=+ssh-rsa;Ciphers=+aes128-cbc,3des-cbc`. OpenSSH 10 has no DSA, so `ssh-dss` is not in the default. Before each ssh call, names in a `+` list that the local ssh does not know are removed, so options saved by older versions keep working; the saved options are not changed. The default is UNVERIFIED on a device: which old algorithms are really needed is known only from a test on a device (question 12 in docs/PROTOCOL.md). |

### Factory adoption

Factory-new devices use the public factory credentials `ubnt` / `ubnt` (docs/PROTOCOL.md). The host key check of the SSH connection is **disabled**, as in the original controller: a device can be impersonated by another host on the same network. Keep the devices on an isolated network without internet access.

The server runs the system `ssh` program without a shell. Passwords never go on the command line: they are given through a temporary askpass script, removed after each call. The adoption command sends the inform address and the new key to the device (`/usr/bin/syswrapper.sh set-adopt`). The configuration of the device is not sent yet: that step follows once it has been tested on a real device.

Errors, from the `api/v1/discovery/<mac>/adopt` and `api/v1/devices/<mac>/repoint` routes: 404 `not_found` for an unknown device, 400 `invalid_input` for a bad value, 409 for a device or a setting that does not allow the action, 502 with the reason (`ssh_not_installed`, `timeout`, `connection_failed`, `ssh_options_rejected` or `command_failed`). `ssh_options_rejected` means the local ssh refused the SSH options (for example "Bad key types"); the add-on log shows the first line of the ssh error at WARNING. The device state becomes `adopt_failed` when adoption fails.

### SSH program

In add-on mode the `ssh` program is included in the add-on. In standalone mode the host must provide `ssh` from OpenSSH 8.4 or newer, because the askpass method needs the `SSH_ASKPASS_REQUIRE` variable.

Not tested on a real device.

## Firmware

The firmware is not in this repository. The image downloads it at build time from `dl.ubnt.com` and checks it with sha256 before installing it. The file is `M2M/2.1.11.1309/firmware.bin`: 7,418,034 bytes, sha256 `7dc6fb4bd67c6352b940d8b65dd0d99325199e8dc4052c20139aaf861fec2a79` (measured 2026-11-17, see docs/PROTOCOL.md, section "Firmware archive"). It is installed read-only at `/opt/mfi-server/firmware/M2M/2.1.11.1309/firmware.bin`. The folder is set by the `firmware_dir` setting (environment variable `MFI_FIRMWARE_DIR`, default `/opt/mfi-server/firmware`).

The table `mfi_server/firmware_bundles.json` covers 10 models: IWD1U, P1E, IWO2U, P8U, M2S, M2M, P6E, P1U, P3E and P3U, all on version 2.1.11.1309. EM3, EM24, THERM and IWS1U are not covered, so they never get an upgrade.

At startup the server checks the size and the sha256 of each file in the table. If a file is missing or does not match, the archive is not available: no Update button appears, and `api/v1/status` reports `firmware.available` as `false` with the error `missing`, `size` or `sha256`.

The inform server serves `GET /dl/firmware/<path>` on the inform port (default 6080). It serves only the paths in the table; any other path gets 404. Keep 6080/tcp on the isolated network.

### Updating a device

The Update button appears only when all of these are true: the device is adopted (known to the server), connected, its model is in the table, and its firmware version is older than the archive. The server never downgrades and never updates automatically.

When you press Update, the page asks for confirmation: the device downloads the firmware and reboots, it can take up to 3 minutes, and the power must not be switched off. The upgrade command is sent with the next inform of the device, so the device must reach the server at the address set by `server_address` (automatic if empty).

Only one device is upgraded at a time: a second request while an upgrade is in progress gets 409 `upgrade_in_progress`.

The device firmware version is read from the `version` field of the inform payload. Its format is UNVERIFIED on a real device (docs/PROTOCOL.md). After the upgrade the status is `updated` when the inform reports the new version. If it does not within 180 s, the status is `not_confirmed`. The upgrade state is kept in memory and is reset at restart.

Test: all current devices are already on 2.1.11.1309, so the Update button must not appear on them. The Update button itself is UNVERIFIED until it is tested on a device with older firmware.

## Network

The add-on uses the network of the host (`host_network`), so its ports open directly on the Home Assistant OS host, without a Docker port mapping.

| Port | Protocol | Use |
|---|---|---|
| 22 | tcp | Outgoing SSH to the devices, for adoption and re-pointing |
| 6080 | tcp | Inform: mFi devices report to the server (HTTP) |
| 3478 | udp | Wake-up packets sent to the devices |
| 8099 | tcp | Web API and web page |
| 10001 | udp | Outgoing discovery (UNVERIFIED on a device, from the controller code, see docs/PROTOCOL.md): the server asks the devices who they are, broadcast to 255.255.255.255 and multicast to 233.89.188.1 |

With the host network, port 8099 is reachable from the whole LAN, not only from Home Assistant. In add-on mode the server answers only the requests that come from the ingress peer, the address of the Home Assistant ingress (default 172.30.32.2, UNVERIFIED on Home Assistant with the host network). Requests from any other address get 403.

If the page answers 403, read the server log: the server writes a WARNING with the address that made the request. Put that address in the `ingress_peer` option of the add-on. In standalone mode, set the variable `MFI_INGRESS_PEER`, or the key `ingress_peer` in `settings.json`.

Keep the devices on an isolated network without internet access. Never expose 6080/tcp, 3478/udp or 8099/tcp to the internet.

### Script action over telnet (off by default)

A `script` action sends a block of plain text over telnet to the serial port of the corresponding adopted mPort Serial. It is not a root shell on the device. What the serial device does with the text is device-specific and not yet verified on a real device.

Risks:

- The text travels in clear text over telnet, so anyone on the network path can read it. Keep the devices and the mPort Serial on the isolated network.
- The serial device receives the text as written. A wrong or unexpected text can change how the device behaves.

Rules:

- Off by default: `allow_script_action` is `False`. It is not an add-on option yet, only a parameter of the engine, so a script action is refused with `script action is disabled` until the owner enables it.
- Only the host and port of an adopted mPort Serial are allowed. Any other target is refused with `device is not an adopted mPort Serial`.
- The length of the text is limited (`script_max_length`, default 1024 characters). Longer text is refused with `script text too long`.
- The owner must approve this action before it is enabled.

## Risky functions

Four extra network functions from the original 2.1.11 controller are implemented but **off by default**. Each one stays disabled until its setting is set to `true` in the server settings (`settings.json` in the data folder). These settings are not add-on options yet. The owner must approve these functions before the add-on is published. Keep the devices on an isolated network and never expose ports 6080/tcp, 6443/tcp or 8099/tcp to the internet (AGENTS.md rule 8).

| Function | Setting (default `false`) | Who | What it does |
|---|---|---|---|
| Web shell | `allow_webshell` | admin only | Checks that the serial line of an adopted mPort Serial is reachable (telnet, port 2323, UNVERIFIED on a device - see network_tools.py). The interactive session is not built yet (UI work, EPIC-16). The host and port are taken only from the stored device record, never from the request. |
| SSH from the browser | `allow_browser_ssh` | admin only | Checks that an adopted device is reachable over SSH (port 22). It is separate from the adoption SSH call. The interactive session is not built yet (UI work, EPIC-16). The host and port are taken only from the stored device record. |
| UPnP announcements | `allow_upnp` | admin only | Builds the UPnP announcement content: only the product name, no version string. The network send is not built yet (transport and UI work, EPIC-16). Their use by mFi devices is UNVERIFIED and needs a device test. |
| Guest access page | `allow_guest_page` | admin only | Builds the guest access page content. It is rate limited only when a rate limiter is configured in the context. Its use with mFi devices is UNVERIFIED (most likely a UniFi remnant) and needs a device test. |

Risks: a web shell or an SSH session gives access to a device over weak, old ciphers with no host-key check; UPnP announcements can reveal the product on the local network; a guest page can open network access to clients that were never authorised. When any of these is off, its route answers `403` with the error key `disabled` and opens no connection. The RADIUS secret of the Wi-Fi Enterprise settings is never written to a log.
