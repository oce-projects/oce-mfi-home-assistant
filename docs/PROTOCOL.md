# Device and protocol notes

Status: public sources collected on 2026-11-15, plus the decompiled controller code. Source of the code facts: `mFi/lib/ace.jar` from `mFi.unix.zip` 2.1.11 (ace.jar 777,033 bytes, sha256 `dbf83f894eb15e4ac24b8729246642832206a02bbd3fd173d2459ef21c7a5bbe`, 205 classes, obfuscated), decompiled with the FernFlower decompiler. References give class and method names; obfuscated names are kept as they are. The decompiled source is not in this repository (vendor code, AGENTS.md rule 1).

Labels used below:

- OBSERVED: read in the decompiled code.
- BYTECODE: also checked with `javap -c` on the original class.
- INFERRED: deduced from the code or from other facts; the reason is given.
- MEASURED: seen on a real device; date and model are given.
- UNVERIFIED: not confirmed.

Anything marked `UNVERIFIED` must not be relied on.

## Devices

| Family | Models (from official Quick Start Guides) |
|---|---|
| mPower | mPower (3 outlets, US/EU), mPower mini (1 outlet, US/EU), mPower PRO (8 outlets US, 6 outlets EU) |
| mPort | mPort, mPort Serial |
| In-wall | outlet MPW / MPW-W, switch LD / LD-W |
| Sensors | mFi-CS (current), mFi-DS (door), mFi-MSC (ceiling motion), mFi-MSW (wall motion), mFi-THS (temperature) |

mPower runs Linux on a MIPS SoC (Atheros AR9330, from public reports, UNVERIFIED on our units), Wi-Fi interface `ath0`, mDNS name `mFi-mPower-<last MAC digits>.local`, services `ssh` and `web`.

Model codes (OBSERVED, `DeviceManager`). Ports created at adoption:

| Model code | Ports created at adoption |
|---|---|
| M2S | 1 |
| M2M | 3 |
| P1U, P1E | 1 |
| P3U, P3E, EM3 | 3 |
| P6E | 6 |
| P8U | 8 |
| IWO2U | 2 |
| IWD1U (dimmer) | 1 |
| EM24, THERM, IWS1U | none |

Models accepted as mFi: `M2M M2S P1U P3U P8U P1E P3E P6E IWO2U IWS1U IWD1U EM3 EM24 THERM`. A model missing from `dl/firmware/bundles.json` gets HTTP 400. Commercial names are not in the code. INFERRED from device names in real backups: P1E = mPower mini EU, P3E = mPower EU (3 outlets), M2M = mPort, M2S = mPort Serial.

## Transport

- OBSERVED: HTTP POST to `/inform` on port 6080 (property `unifi.http.port`, default 6080, `com.ubnt.service.system.SystemService`; servlet `com.ubnt.net.InformServlet`).
- OBSERVED: the URL written into the device configuration is `http://<host>:<port>/inform` (`ConfigService`).
- OBSERVED response codes: 200 (encrypted body or JSON), 400 (bad packet or unmanaged device), 404 (unknown device), 503 (handler error).
- Default host name `mfi`. A device that cannot reach a controller polls every 15 s (device log posted on the Ubiquiti forum, firmware MF.v2.1.4 build 1301). After 10 failures the Wi-Fi client restarts.
- The address can be set in the device web page as `IP:6080` (official FAQ).

## Packet format

OBSERVED (`InformServlet`). All integers are big-endian.

| Offset | Bytes | Field | Rule |
|---|---|---|---|
| 0 | 4 | magic | must be 1414414933 ("TNBU"), else "Bad packet magic" |
| 4 | 4 | version | echoed in the response |
| 8 | 6 | device MAC | must equal `mac` in the payload, else 400 |
| 14 | 2 | flags | `0x1` encrypted, `0x2` compressed |
| 16 | 16 | AES IV | |
| 32 | 4 | data version | 0 or 1; greater than 1 is rejected |
| 36 | 4 | data length | payload length |
| 40 | n | payload | encrypted when flag `0x1` is set |

The body is at least 8 bytes and the header at least 40 bytes ("Header is too short").

## Encryption

- OBSERVED: AES-128-CBC with PKCS5 padding (`Cipher.getInstance("AES/CBC/PKCS5Padding")`). On a padding error the controller retries with `AES/CBC/NoPadding` and logs "Bad padding detected, trying to recover...".
- OBSERVED: the key is the device authkey: 32 hex characters converted to 16 bytes. The IV is the IV of the request header.
- OBSERVED: the response is encrypted with the same key and **the same IV**, with the same header (magic, version, MAC, flags, IV, data version) and the new length. `Content-Type: application/x-binary`, length 40 + n.
- OBSERVED: an unencrypted request gets plain JSON.
- OBSERVED: every response carries `server_time_in_utc` (milliseconds since 1970, as a string).

Keys tried (OBSERVED, `DeviceManager`), in order. The first key that decrypts wins; otherwise the log says "inform decrypt error (tried all N keys)":

| Device state | Keys tried, in order |
|---|---|
| unknown MAC | default key |
| device with `x_prev_authkey` | `x_prev_authkey`, then `x_authkey` |
| known device | `x_authkey`, then default key |

- Default key: `ba86f2bbe107c7c57eb5f2690775c712`. OBSERVED: it is a factory constant fixed in the controller code, the same for every reset device. It is not a site key and gives no access to an adopted device, which uses its own `x_authkey`. Already public in `mcrute/ubntmfi`. Never write a real `x_authkey` in this repository (AGENTS.md rule 2).
- OBSERVED: `x_prev_authkey` is only read, never written in the code.
- Measured on real backups: every `x_authkey` is 32 lowercase hex characters.

## Compression

- OBSERVED and BYTECODE: the 2.1.11 controller decrypts, parses the payload, and only then inflates with zlib (`java.util.zip.Inflater`) when flag `0x2` is set. It discards the result.
- INFERRED: a compressed inform cannot work with 2.1.11, so devices that worked with it did not compress. A new server should still accept zlib.

## Payload

- Data version 1 = JSON (the mFi format).
- Data version 0 = text: a first line containing `,platform`, an empty line, then `key=value` lines. INFERRED old format, not used by mFi 2.x.
- OBSERVED JSON fields read and stored: `mac`, `model`, `serial`, `ip`, `inform_url`, `connect_request_ip`, `connect_request_port`, `version`, `fingerprint`, `uptime`, `cfgversion`, `portversion`, `local_version`, `default`, `port_table`, `alarm` (measurements).
- OBSERVED: the UniFi Wi-Fi tables `radio_table` and `vap_table` are read, but mFi does not use them.

## Adoption

OBSERVED flow:

1. Discovery (section Discovery) goes to `DeviceManager`. A new device that is not "default" is ignored ("managed by another AC"). Otherwise it gets state 2, pending adoption.
2. A non-adopted device that informs gets HTTP 400, or `setdefault` when it uses a non-default key and does not declare `default`. **A device adopted by another controller is reset to factory settings if it talks to this one.**
3. SSH adoption (`com.ubnt.net.UbntDiscoveryServer`, sshj library): port 22, timeout 3000 ms, **no host key check** (`PromiscuousVerifier`), command `/usr/bin/syswrapper.sh set-adopt <url> <authkey>`. The result is not read.
4. Credentials: `ubnt` / `ubnt` for a normal adoption. For an automatic re-adoption, the controller administrator name and password.
5. State 7 (adopting) lasts 120 s. The device informs with the new key and gets `setparam`.

Not used: `mca-cli`, `set-inform` (not found). Other SSH commands present: `/usr/bin/syswrapper.sh restore-default`, and a `sed` that sets `mgmt.is_default=true` in `/etc/persistent/cfg/mgmt`.

Authkey generation (OBSERVED): at adoption, 32 characters from `0123456789abcdef` with `java.util.Random`. This is **not cryptographic**. If an adopted device still uses the default key, a new key is made with `SecureRandom` and sent in the `mgmt_cfg` of a `setparam`.

## Controller responses

OBSERVED (`DeviceManager`). One response per inform; the first matching row wins.

| Order | Condition | Response |
|---|---|---|
| 1 | not adopted, non-default key | `setdefault` |
| 2 | server busy | `noop` without `interval` |
| 3 | firmware differs from `bundles.json` and auto-upgrade is on | `upgrade` with `url`, `version` |
| 4 | payload `cfgversion` differs | full `setparam` |
| 5 | adopted device still on default key | new key, `setparam` with `mgmt_cfg` |
| 6 | reboot detected from `uptime` | `setparam` with `port_cfg` and `device_cfg` |
| 7 | `portversion` differs, or `new_config` / `resetcounter` | `setparam` |
| 8 | labels changed on the device (`local_version`) | `setparam` with `mgmt_cfg` |
| 9 | a queued command, and the device was already connected | `cmd` |
| 10 | otherwise | `noop` with `interval` |

- noop interval, BYTECODE: `now + 10 + (long)Math.random() * 5` casts `Math.random()` to long before multiplying, so the random part is always 0. Interval = 10 s, always.
- UNVERIFIED (approximate reading of `DeviceManager`, not reconciled with the states below): the controller stores next heartbeat = now + 20 s and a "lost" time of now + 60 s. Do not rely on these two values; see "Device states in the controller".
- The 15 s retry in the forum log is the case of a device that cannot find a controller.
- OBSERVED: `cfgversion` and `portversion` are not hashes. They are 16 random hex characters (`java.util.Random`), regenerated on every change. A mismatch makes the controller resend the configuration.

`setparam` (OBSERVED, `ConfigService`): message fields `_type=setparam`, `cfgversion`, `system_cfg`, `mgmt_cfg`, `port_cfg`, `device_cfg`, `blocked_sta`, `authorized_guests`, and `ser2net_cfg` only for M2S. Each `*_cfg` is text of `key=value` lines.

- `mgmt_cfg`: `mgmt.is_default=false`, `mgmt.authkey=<key>` (only when the key used by the device differs from `x_authkey`), `mgmt.cfgversion`, `mgmt.portversion`, `mgmt.localversion`, `mgmt.servers.1.url=http://<host>:<port>/inform`, `mgmt.selfrun_guest`.
- `system_cfg`: `users.1.name=<controller admin name>`, `users.1.password=<DES crypt of the admin password, random 2-letter salt>`. After adoption, the device SSH and web user is the controller administrator. INFERRED, approximate: services `telnetd`, `snmp`, `dhcpd`, `dnsmasq` disabled; `httpd.port=80`; bridge `br0`; syslog on; server time zone; host name from the device name (max 31 characters). Interface `eth1` for P1U, P1E, P3U, P3E, P8U, P6E, IWO2U, IWS1U, IWD1U; `eth0` for the others.
- `port_cfg` for mPower and in-wall outlets. For each outlet K: `vpower.K.relay=0|1`, `vpower.K.output=0|1`, `vpower.K.lock`, `vpower.K.rep_output=1`, `rep_pf`, `rep_energy_sum`, `rep_v_rms`, `rep_i_rms`, `rep_active_pwr`, and tags `vpower.K.output_tag=output`, `pf_tag=pf`, `energy_sum_tag=energy_sum`, `v_rms_tag=v_rms`, `i_rms_tag=i_rms`, `active_pwr_tag=active_pwr`. Plus `port.N.model`, `port.N.label`, `port.N.sensorId` (or `port.N.mode=off` for an empty port). The device reports only quantities with `rep_<name>=1`.
- `port_cfg` for mPort (M2M, M2S): lines `port.N`, `PWR.N`, `AI.N`, `DI.N`, `DO.N`. The line format is in section 3 of "mPort and sensors (from ace.jar 2.1.11)"; how the device applies each line is UNVERIFIED.
- `ser2net_cfg` (M2S with a Serial sensor): `enable=on`, `baudRate`, `parity`, `uartMode`, `termination`, `antenna`.

## Commands to the device

`mfi-output` (switch an outlet). OBSERVED: queued as a task; a new command for the same port replaces the old one. The controller sends the wake-up packet and delivers the command as the response to the **next inform**, `_type=cmd`.

Fields (INFERRED from construction and serialisation):

```
{"_type":"cmd","cmd":"mfi-output","mac":...,"port":N,"sId":<sensor id>,"val":0|1,
 "volt":...,"off_volt":...,"timer":<seconds>,"dimmer_level":...,"dimmer_ramp":...,
 "_id":...,"device_id":...,"datetime":...,"server_time_in_utc":...}
```

- `val` 1 = on, 0 = off.
- `volt` is the model output voltage when on, 0 when off.
- `dimmer_level` only for dimmers.
- For M2M the port becomes `2*(port-1) + outport`.
- OBSERVED: the command is deleted once sent, with no acknowledgement. The wanted value is kept as `configed_val` and cleared when a later inform reports it in `alarm`.
- OBSERVED: delivered only if the device was already connected (state 1).
- The structure matches what `mcrute/ubntmfi` observed on the network.

Other commands:

| Command | Fields |
|---|---|
| `_type: reboot` | none |
| `_type: upgrade` | `url` `http://<host>:<port>/dl/firmware/<path>`, `version` |
| `_type: setdefault` | none; used for a device of another controller, or a connected device being deleted |
| `cmd: locate` | none |
| `cmd: set-rmsSum` | `sId`, `mac`, `port`, `val` |
| `cmd: dimmer_lock_setting` | `sId`, `mac`, `port`, `val` |
| `kick-sta`, `block-sta`, `unblock-sta`, `authorize-guest`, `unauthorize-guest`, `kick-serial` | `mac` (inherited from UniFi) |

Not found in the code: `set-locate`, `speedtest`, `provision`.

## Firmware archive (MEASURED 2026-11-17)

Source: `mFi.unix.zip` 2.1.11 (Linux package, 26,896,961 bytes, sha256 in AGENTS.md). The archive was listed and its files extracted and hashed. The firmware file was also downloaded from `https://dl.ubnt.com/mfi/2.1.11/firmware/M2M/firmware.bin` and hashed on the same day.

- MEASURED: `mFi/dl/firmware/M2M/2.1.11.1309/firmware.bin` in the package is 7,418,034 bytes. It is byte for byte the same file as `https://dl.ubnt.com/mfi/2.1.11/firmware/M2M/firmware.bin`, with sha256 `7dc6fb4bd67c6352b940d8b65dd0d99325199e8dc4052c20139aaf861fec2a79`.
- MEASURED: `mFi/dl/firmware/bundles.json` is 904 bytes and uses single quotes. It is not strict JSON, so a strict parser such as `json.load` rejects it.
- MEASURED: the 2.1.11 `bundles.json` lists 10 models: IWD1U, P1E, IWO2U, P8U, M2S, M2M, P6E, P1U, P3E, P3U. For every one of them the path is `M2M/2.1.11.1309/firmware.bin`, the version is `2.1.11.1309`, and the display name is empty.
- MEASURED: EM3, EM24, THERM and IWS1U are accepted as mFi models (section Devices) but have no entry in this file. INFERRED: the controller offers no firmware upgrade to them.

Upgrade message:

- OBSERVED (`DeviceManager`, row 3 of "Controller responses"): an inform gets an `upgrade` response when the device firmware differs from `bundles.json` and auto-upgrade is on. The controller does not send an upgrade to a device whose firmware is not older than the archive version.
- OBSERVED: the message has the form `{"_type":"upgrade","url":"http://<host>:<port>/dl/firmware/<path>","version":"<version>"}`.
- OBSERVED (state table): the device is in state 4 (firmware upgrade) for 180 s.
- UNVERIFIED: the exact format of the `version` field in the inform payload. The hypothesis is `2.1.11.1309`. Do not rely on it.

## Wake-up packet (UDP 3478)

OBSERVED (`com.ubnt.net.E`, JSTUN library): the controller opens a UDP socket on `0.0.0.0:3478`. It answers STUN requests and sends a 20-byte "connection request" starting with bytes `0x88 0x88` to `connect_request_ip:connect_request_port` from the inform payload. The device then informs at once.

## Measurements

OBSERVED: measurements arrive in the `alarm` list. Each item has:

- `sId`: sensor id.
- `tag`: the quantity.
- `type`.
- `val`: number.
- `time`: ms since 1970; 0 = controller time.

An item may contain an `entries` list. Each entry inherits the parent fields. Quantities are values of `tag`, not JSON keys.

| tag | unit | meaning |
|---|---|---|
| `output` | 0 or 1 | relay state (on/off) |
| `active_pwr` | W | active power |
| `v_rms` | V | voltage |
| `i_rms` | A | current |
| `pf` | | power factor |
| `energy_sum` | Wh | cumulative energy |
| `motion` | no motion / motion | OBSERVED (`SystemService` table): wall (MSW) or ceiling (MSC) motion sensor, input 0 |
| `tamper` | state (unit not in the report) | tag OBSERVED (`SystemService` table), unit UNVERIFIED: tamper switch of the motion sensor, input 1 |
| `magnetic` | closed / open | OBSERVED (`SystemService` table): door or window sensor (DS), inversion applied |
| `amps` | A (INFERRED: the converted value is in A, see "mPort and sensors" section 4; conversion `xyz*100`, max 120) | tag OBSERVED (`SystemService` table): current of a current sensor (CS) |
| `ampHours` | UNVERIFIED (not in the report) | tag OBSERVED (`SystemService` table), unit UNVERIFIED: second tag of CS; meaning INFERRED from the name |
| `temperature` | CELSIUS | OBSERVED (`SystemService` table): THS (conversion `xyz*30 - 10`) and RTD PT-100 |
| `degreeHours` | UNVERIFIED (not in the report) | tag OBSERVED (`SystemService` table), unit UNVERIFIED: second tag of THS; meaning INFERRED from the name |
| `humidity` | % | OBSERVED (`SystemService` table): THS humidity (conversion `xyz*50`) |
| `counter` | counts | OBSERVED (`SystemService` table): pulse counter input |
| `input` | on / off | OBSERVED (`SystemService` table): digital input |
| `volts` | V (range -2 to +2 V) | OBSERVED (`SystemService` table): analog input voltage |
| `voltSum` | UNVERIFIED (not in the report) | tag OBSERVED (`SystemService` table), unit UNVERIFIED: second tag of the analog input; meaning INFERRED from the name |

- `energy_sum`, OBSERVED: when a new value is below 0.9 times the last one, the controller treats the counter as reset and adds the old value to a base. It discards increases above 0.001 Wh per millisecond.
- OBSERVED: `type="detected"` with `index="DI<n>"` means a new sensor on an mPort, not yet configured.
- The value of `type` for analog readings: UNVERIFIED. The REA report found none and says the path does not change for analog and RMS readings (section 1 of "mPort and sensors (from ace.jar 2.1.11)").
- Third-party measurement, UNVERIFIED on our units: the mPower energy counter is kept in RAM and restarts from zero after a power loss (`feiglein74/mpower`).

## mPort and sensors (from ace.jar 2.1.11)

The items below come from the `ace.jar` 2.1.11 REA report (ticket T-MWMG5ETI) and from its full re-run (ticket T-MWMQLEW5). The report gives no Evidence ID, so each item cites the report's class and method, or its output number and approximate line. Report outputs of the first run: n.2 `ConfigService`, n.5 `SystemService`, n.6 `DeviceManager`, n.7 the sensor service (`com.ubnt.service.ooOO`), n.9 the API (`com.ubnt.ace.api`). Full re-run outputs: n.2 sensor service, n.3 `ConfigService`, n.4 `DeviceManager`, n.5 API, n.6 `SystemService`, n.7 `ApiServlet`; items marked "full re-run" use these numbers. Items the report does not prove stay UNVERIFIED, with a note of what was searched (AGENTS.md rule 6). The report's constants (noop interval 10 to 15 s, lost-device rule of 3 intervals plus 10 s) are not transcribed here: they disagree with "Controller responses" and "Device states in the controller", and stay unreconciled.

### 1. Measurements of mPort ports in the inform

- OBSERVED (n.9, `class_46`, method `method_146`): the inform `alarm` list may contain an `entries` list. Each entry takes the fields of its parent item. Fields read: `type`, `tag`, `val`, `time`, `index`, `sId`, `label`, `model`.
- OBSERVED (n.9): `sId` is the sensor id. The controller sends the same id to the device as `sensorId` in `port_cfg` (section 3).
- OBSERVED (n.9): each measurement is saved in the collection `M2mgeneric` with `time` and `ttl_time`. `index`, `label` and `model` are removed before saving.
- OBSERVED (n.9): tag `energy_sum` is saved twice, the second time as `raw_energy_sum`. Tag `output` is passed to the UI as `output_val`.
- OBSERVED (n.7, sensor service, approx. lines 620-800): the code tests the `type` values `output`, `input`, `counter` and `detected`. Analog and RMS readings take the same path whatever their `type`.
- OBSERVED (n.9, approx. lines 1137-1139): for `index` `DI<n>` the mPort port is n divided by 2 (integer division), plus 1.
- OBSERVED (full re-run, n.3 approx. 410-430 and n.5 approx. 1148-1152): the two formulas agree. With the 1-based port of the alarm index, `k` = 2*(port-1) + j, with j = 0 or 1; with the 0-based index `i` of the `port_cfg` list, `k` = 2*i + j. Both give the same `DI.<k>` line.
- OBSERVED (n.5, `SystemService`): the tag names of each sensor kind are in the model table of section 2. The units are in the tag table under "Measurements", where the report gives them.

### 2. Sensor type recognition on an mPort port

- OBSERVED (n.5, `SystemService`, constructor, approx. lines 140-735): a table keyed by model. Fields: `desc`, `pwr_volt`, `analog`/`digital`/`rtd`, `rep_*`, `*_tag`, `unit`, `precision`, `conversion`, `do_volt<n>`, `inversion<n>`, `outport`, `default_tag`.
- UNVERIFIED: the product name after the `Ubiquiti ` prefix. The prefix comes from a static field returned by `getProduct`; its assignment is not in the part of `SystemService` read by the full re-run (n.6, lines 1-200, 380-1200 and 2240-2390). The full re-run also lists names without the prefix (`Counter`, `Outlet`, `Dimmer Switch`, `Output 24v`, `Output 12v`, `Output 5v`, `Input Digital`, `Input Analog`, `RTD`, `Serial`) and the full name `Ubiquiti UVC PRO (to camera)`. The rows below give the model suffix.

| Model (suffix) | Kind | Tags (input) | Unit or conversion |
|---|---|---|---|
| MSW | wall motion | `motion` (input 0), `tamper` (input 1) | state: no motion / motion |
| MSC | ceiling motion | `motion`, `tamper` | state: no motion / motion |
| CS | current | `amps`, `ampHours` | conversion `xyz*100`, maximum 120 |
| DS | door/window magnetic | `magnetic` | closed / open, inversion applied |
| THS | temperature | `temperature`, `degreeHours` | CELSIUS, conversion `xyz*30 - 10` |
| `THS: Humidity` | humidity | `humidity` | %, conversion `xyz*50` |
| Counter | counter | `counter` | counts |
| Input Digital | digital input | `input` | on / off |
| Input Analog | analog input | `volts`, `voltSum` | volts, -2 V to +2 V |
| RTD | PT-100 | `temperature` | CELSIUS, gain 8, res 18 |
| Outlet, Dimmer, Dimmer Switch | mPower outlets (not mPort) | `output`, `pf`, `energy_sum`, `v_rms`, `i_rms`, `active_pwr` | |
| Output 5v, 12v, 24v, UVC PRO (to camera) | outputs | `output` | on / off |
| Serial | serial | none | |

- OBSERVED (n.7, sensor service, approx. lines 160-260): the sensor record is saved in the collection `sensor` with `mac`, `port`, `model`, `label`, `_id`, `calibration`, `output_val`, `configed_val`, `output_lock` and `tags`.
- INFERRED (n.9 field `model`, n.5 table keyed by model): the alarm entry carries `model`, which selects the row above. The report does not show the code that matches them.
- OBSERVED (n.2): the port's sensor is also named in `port_cfg` by `sensorId` (section 3).

### 3. Format of `port_cfg` for mPort

- OBSERVED (REA report on `ace.jar` 2.1.11, ticket T-MWMG5ETI, model rows): the form of `port_cfg` depends on the model. P* (all P models), IWO2U, IWS1U and IWD1U use `vpower` lines (see "Controller responses"). M2M, M2S and the other models use the `port.N`, `AI.N`, `DI.N` and `DO.N` lines below. Only M2S receives `ser2net_cfg`. Only IWD1U gets `dimmer_mode` in `device_cfg` (see "Device configuration (setparam)").
- OBSERVED (n.2, `ConfigService`, `port_cfg` generator, approx. lines 215-500): plain text with one `key=value` per line.
- OBSERVED: an empty port has `port.<i>.mode=off`. A port with a sensor has `port.<i>.model`, `port.<i>.label` and `port.<i>.sensorId`. Each port has a `PWR.<i>.volt` line.
- OBSERVED: an analog input has `AI.<i>` with `sensorId`, `model`, `label`, `gain`, `res`, `conversion`, `calibration`, `rep_analog`, `rep_sum`, `rep_rms`, `rep_rms_sum` and the `*_tag` keys. For the RTD, `i` is the port + 1.
- OBSERVED: a digital input or output has `DI.<k>` or `DO.<k>`, with `k` = 2*port + 0 or 1. Fields: `sensorId`, `rep_input`, `rep_output`, `rep_counter`, `rep_counter_rate`, `conversion`, `calibration`, `input_tag`, `counter_tag` and `output_tag`. An output also has `DO.<k>.volt`.
- OBSERVED: the voltage line of an output is 0 or on, depending on the state in `output_val` and on the inversion flag.
- OBSERVED (n.2): `analog_cfg` and `serial_cfg` have their own generators: `analog.<n>` with `mode`, `gain`, `res`, `label`, `type`, `upv` and `unit`; `serial.<n>` with `speed` and `destination`.
- OBSERVED (n.6, `DeviceManager`, approx. lines 540-700): the controller sends `port_cfg` as a field of a `setparam` message, with `device_cfg` and, for M2S, `ser2net_cfg`.
- OBSERVED (n.6, `DeviceManager`): the configuration is sent when (a) `cfgversion` differs; (b) the `portversion` in the inform differs from the expected one; (c) `new_config` is set and the inform has no `portversion`; (d) after a reboot (uptime lower than expected); (e) after a counter reset (`resetcounter`); (f) after a `local_version` with ports changed locally.
- OBSERVED (n.6, approx. lines 1560-1600): at adoption an M2S gets 1 port and an M2M gets 3 ports, as in "Devices".
- UNVERIFIED: how the device applies each line. The full re-run covers the controller side only (`ace.jar`); the device firmware (`dl/firmware/M2M/2.1.11.1309/firmware.bin`, see "Firmware archive") was not analysed.

### 4. Calibration and conversion

- OBSERVED (n.5, `SystemService`, model table): each model row has a `conversion` string, for example `xyz*100` for CS, `xyz*30 - 10` for THS temperature and `xyz*50` for THS humidity (section 2). The string is sent to the device as `conversion` in `port_cfg` (section 3).
- INFERRED: `xyz` is the placeholder for the raw value in the conversion expression, as in `xyz*30 - 10`. The full re-run found no definition in the code. The default `calibration` (full re-run, n.2 approx. 1060-1075) is a plain `xyz`, which means the raw value is left unchanged.
- INFERRED: the conversion is applied on the device, not by the controller. The controller sends the string in `AI` and `DI` lines; in the alarm ingestion the value `val` is saved as it arrives (full re-run, n.5 approx. 1150-1185 and n.2 approx. 680-900), and no code read evaluates the expression. So the value that reaches the controller is already in °C, % or A. This is inferred from the code read, not from a full search of ace.jar; the unit of each tag (CELSIUS for `temperature`, % for `humidity`, A for `amps`) follows from the model row that owns the conversion string (section 2), not from a measurement on a device.
- OBSERVED (n.7, sensor service, approx. lines 290-330): the user field `calibration` of a sensor sets `new_config`, so the port configuration is sent again (section 3, case c).
- OBSERVED (full re-run, n.2 approx. 1060-1075): a sensor-service method takes the sensor id and returns the `calibration` field of that sensor, or `xyz` when it is missing. So `AI.<i> calibration` and `DI.<k> calibration` carry that string unchanged. This corrects the earlier note, which read the same call as returning a label: the full re-run found that the method returning `label` is a different one.
- INFERRED: there are no separate offset and scale fields. The configuration generator and the sensor service only have `calibration` and `conversion`, both strings. The `upd/sensor` API action saves `calibration`, sets `new_config` and rebuilds the configuration (full re-run, n.2 approx. 245-290). The absence is inferred from the code read, not from a full search of ace.jar.

### 5. 12 V outputs of the mPort relay

- OBSERVED (n.6, `DeviceManager`, `mfi-output`, approx. lines 1410-1440): the on/off command is the API command `mfi-output`. It queues a `cmd` task for the device with `cmd` = `mfi-output`, `port`, `val`, `timer` and `sId`; `val` is 0 (off) or 1 (on). The task is sent as the response to the next inform (n.6, approx. lines 590-690).
- OBSERVED (n.6, `DeviceManager`): for M2M the port becomes `2*(port-1) + outport`. `outport` is read from the model table (section 2), 0 when absent. Every "Output" model has `outport` 0, so for these outputs the port is `2*(port-1)`. This confirms the rule in "Commands to the device" for the report's models.
- UNVERIFIED: whether an mPort 12 V output is the model "Output 12v" of section 2. The model table (full re-run, n.6 approx. 590-620) has `Output 12v` as a digital output with `outport` 0 and `do_volt0` 12, the same as `UVC PRO (to camera)`, so the table does not single it out. No code read links an mPort port to a model row. Searched: the model table and the port generator.
- UNVERIFIED: whether the extra fields of "Commands to the device" (`volt`, `off_volt`, `_id`, `datetime`) are sent with this command. The full re-run found that the command is a copy of the API request parameters. The code read sets only `cmd`, `port` and `timer` (full re-run, n.4 approx. 1420-1445), and sets neither `volt` nor `off_volt`. Whether a request can carry them is UNVERIFIED. The full re-run does not mention `_id` or `datetime`.

### 6. mPort Serial (M2S): serial configuration

- OBSERVED (n.2, `ConfigService`, `ser2net_cfg`, approx. lines 570-600): text with `enable` (`on` or `off`), `baudRate`, `parity`, `uartMode`, `termination` and `antenna`. Only M2S receives `ser2net_cfg`.
- OBSERVED (n.2): `serial_cfg` lines `serial.<n>` carry `speed` and `destination` (section 3).
- Speed: OBSERVED (`baudRate` in `ser2net_cfg`, `speed` in `serial_cfg`). Parity: OBSERVED (`parity` in `ser2net_cfg`).
- Data bits and stop bits: OBSERVED not written. `databits` and `stopbits` are read but not emitted in `ser2net_cfg` (full re-run, n.3 approx. 560-590). Their effect on the device is UNVERIFIED.
- TCP port: OBSERVED absent from the generator. The controller sends no TCP port in `ser2net_cfg` (full re-run, n.3 approx. 560-590). The port the device listens on is UNVERIFIED.
- `kick-serial` (question 6): OBSERVED (n.6, `DeviceManager`, approx. lines 1385-1395). The controller raises the event `EVT_mFi_SerialKick` and queues a `cmd` task with `cmd` = `kick-serial` for the device. The request is `/api/v1.0/cmd/devmgr` with `cmd` and `mac` (full re-run, n.4 approx. 1385-1395). UNVERIFIED: what the device does with it; the effect is not in the controller code.

### 7. New sensor with `type="detected"`

- OBSERVED (n.9): when an alarm item has `type` = `detected`, the controller takes the port from `index` (section 1). This is the new-sensor entry listed under "Measurements".
- OBSERVED (n.7, approx. lines 890-905): the controller creates an in-memory sensor with model `detected`, label "unconfigured sensor" and `time` set to the current time.
- OBSERVED (n.7, approx. lines 905-920): a `detected` sensor not seen for more than 20 seconds is removed.
- OBSERVED (full re-run, n.7 approx. lines 85-100 and n.5 approx. lines 1470-1500): the user links the sensor to a port with `POST /api/v1.0/new/sensor`, which takes `mac`, `port`, `model` and `label`. It replaces a `detected` sensor on that port and updates its `port_cfg` entry (full re-run, n.2 approx. lines 330-400). `POST /api/v1.0/mov/sensor` moves an existing sensor (`sId`, `newMac`, `newPort`), and `upd/sensor` edits its fields. After each link the controller sets `new_config`, so the flow of section 3 sends the configuration again.
- OBSERVED (full re-run, n.4 approx. lines 1585-1590 and 785-800; this corrects the first run): on creation of an M2M the controller calls an internal sensor-service method with the list [-1], which removes the `detected` sensors of the device from the cache. An empty `alarm` received in an inform has the same effect. The controller sends no `alarm` list in this case, so no message carries it.

### 8. Message flow with an mPort or mPower device

Source: the flow part of the REA report on `ace.jar` 2.1.11 (ticket T-MWMG5ETI, no output number). The steps are OBSERVED as the report describes them. Message fields are the ones of "Measurements" and "Controller responses".

1. The device sends an inform with `alarm`. `portversion` and `local_version` are top-level fields of the same inform, not nested inside `alarm` (OBSERVED, full re-run, n.4 approx. lines 540-690).
2. The controller replies with `setparam` if the configuration changed, with `cmd` if a task is queued, or with `noop` otherwise (rules of "Controller responses").
3. The controller saves the measurements in `M2mgeneric` and compares the reported output values with the configured ones (see `configed_val` in "Commands to the device").
4. User commands (`mfi-output`, `kick-serial`) become tasks, and the device gets them in the reply to its next inform.

The report writes both `localversion` and `local_version`. This file uses `local_version` for the inform field and `mgmt.localversion` for the configuration key, as in the sections above.

## Discovery (UDP 10001)

OBSERVED (`DatagramQueryServer`, `LiteStationQueryServer`):

- UDP port 10001, multicast `233.89.188.1` and broadcast `255.255.255.255`.
- Request of 4 bytes `01 00 00 00` (version 1, command 0, length 0).
- Reply: version, command, length, then TLV fields `type (1 byte) length (2 bytes) data`.
- Main types: 1 MAC, 2 MAC+IPv4, 3 version, 10 uptime, 11 hostname, 12 platform, 21 model, 22 firmware version, 23 "default" flag.
- No keys or configuration in discovery.

MEASURED 2026-11-17 (mPower mini, platform P1E, firmware 2.1.11.1309, just reset and never adopted):

- The reply has 8 TLV fields, in this order: 2 (MAC+IPv4), 1 (MAC), 10 (uptime), 11 (hostname), 12 (platform "P1E"), 13 (ESSID, 10 bytes), 14 (1 byte, value 0x02), 3 (version string, 34 bytes, e.g. "MF.ar933x.v2.1.11.1309.150406.1423").
- 13 = ESSID (the device access point name). 14 = a single byte (0x02); its meaning is UNVERIFIED.
- Fields 21 (model), 22 (firmware) and 23 ("default" flag) do NOT arrive from this firmware. The server therefore derives the model from field 12 (platform) and the firmware from field 3 (version string), and leaves the "default" flag unknown.

## Device states in the controller

| State | Meaning | Timeout |
|---|---|---|
| 0 | initial or disconnected | |
| 1 | connected | |
| 2 | discovered, pending adoption | |
| 4 | firmware upgrade | 180 s |
| 5 | configuration sent | 120 s |
| 6 | heartbeat lost (no inform for more than 40 s, UNVERIFIED) | |
| 7 | adopting | 120 s |
| 8 | being deleted | |

- OBSERVED: after 120 s without an inform the device is lost (`EVT_AP_Lost_Contact`).
- The 40 s (state 6), 60 s (see "Controller responses") and 120 s values come from different code paths and were not reconciled. A new server should use only the OBSERVED 120 s value to declare a device lost; the other two are UNVERIFIED.
- The meanings of states 0, 5, 6 and 8 are INFERRED (no names in the code).

## Security summary

- Fixed public default key, and SSH `ubnt` / `ubnt` without host key check, for first contact.
- Adoption key from `java.util.Random`.
- The controller keeps the administrator password in clear text (OBSERVED; where exactly it is stored is UNVERIFIED). The device receives it as a DES crypt in `system_cfg` (see "Controller responses"), and it becomes the SSH and web password of every adopted device.
- The authkey appears in clear text in a log line of a simulation class.
- Devices belong on an isolated network without internet access (AGENTS.md rule 8).

## Local control without a controller (mPower)

From public projects, UNVERIFIED on our units:

- HTTP: `/login.cgi`, `/mfi/sensors.cgi`, `PUT /sensors/<n>`.
- SSH (legacy ciphers): relay state in `/proc/power/relay<n>`, readings in `/proc/power/*`.
- mPort local API: not documented.

## Factory state

- Default credentials `ubnt` / `ubnt`.
- Direct connection default IP `192.168.1.20`; DHCP on a LAN.
- Reset: hold the reset button until the LED changes (exact pattern per model in the Quick Start Guides).
- Wi-Fi models (mPower, mPower mini, in-wall outlet MPW/MPW-W, in-wall switch LD/LD-W) without a Wi-Fi configuration run their own access point; setup page at `https://192.168.2.20` (8 Quick Start Guides). See "Wi-Fi setup mode".
- mPort and mPort Serial: no access point. Setup page over Ethernet at `http://192.168.1.20` with the computer on a static `192.168.1.x` address, or through DHCP on the LAN (mPort Quick Start Guides). Its TLS: UNVERIFIED.

## Wi-Fi setup mode (access point)

MEASURED on 2026-11-17 on an mPower mini (firmware v2.1.11, from `status.cgi`), from a Windows PC joined to the device access point. Raw captures stay outside the repository: they contain MAC addresses and the names of nearby networks.

- The setup page is at `https://192.168.2.20`, the same address on every device. Ping: 4 of 4 replies, 2 to 7 ms.
- The access point is an open network (no password, no encryption) named `mFi` plus the last 6 hex digits of the MAC address, on channel 1 (`netsh wlan show interfaces` on the joined PC; channel also in `status.cgi`).
- TLS (OpenSSL 3.2.1 `s_client`): TLSv1 only; TLSv1.1 and TLSv1.2 fail. Accepted suites: `AES256-SHA`, `AES128-SHA`, `DHE-RSA-AES256-SHA`, `DHE-RSA-AES128-SHA`. Refused: `ECDHE-RSA-AES256-SHA`, `ECDHE-RSA-AES128-SHA`, `CAMELLIA256-SHA`, `DHE-RSA-CAMELLIA256-SHA`. Not tested (missing in the client build): `DES-CBC3-SHA`, `RC4-SHA`, `RC4-MD5`, `SEED-SHA`. RSA key 1024 bit, DH 1024 bit, signature digest MD5-SHA1.
- Certificate: self-signed, `O=Ubiquiti Networks Inc.`, `CN=ubnt`, `sha1WithRSAEncryption`, valid from 2007-05-17 to 2018-04-29 (expired). Web server `lighttpd/1.4.31`.
- Current browsers refuse TLS 1.0, so the page needs a bridge: `docs/WIFI-SETUP.md`.

Endpoints, OBSERVED in the page script and MEASURED in the responses:

| Endpoint | Method | What | Seen |
|---|---|---|---|
| `/` | GET | setup page, sets cookie `AIROS_SESSIONID` | 200, `text/html`, 36,535 bytes |
| `/captivepoll.cgi` | GET | JSON `{mac, ip, ap}` | 200, 46 bytes |
| `/status.cgi` | GET | JSON `host`, `lan`, `wlan`, `ppp`, `wireless`, `services`, `firewall`; the page polls it every 1 s | 200, 1,577 bytes |
| `/survey.json.cgi` | GET | JSON array of visible networks, served as `text/html` | 200, 15 networks, 5,718 bytes |
| `/captive.cgi` | GET | applies the form; the page sends the form serialized in the query string | not called |
| `/leaveap.cgi` | POST | the page asks the device to close its access point | not called |
| `http://<new address>/ping.cgi` | GET, JSONP | the page checks the device on the home network | not called |
| `jsl10n.cgi` | GET | page translations | not called |

Network object of `survey.json.cgi`: `mac`, `mode`, `frequency`, `channel`, `quality`, `signal_level`, `noise_level`, `encryption`, `essid`, `pairwise_ciphers`, `group_cipher`, `auth_suites`, `htcap`, `airmax_ie`, `mtik_name`, `ieee_mode`.

`status.cgi` before setup: `host.fwversion` `v2.1.11`, `host.hostname` `mFi-mPowerMini-<last 6 MAC digits>`, `host.netrole` `router`, `host.ctrl_state` `default`, `host.cp_state` `none`, `wireless.mode` `sta`, `wireless.essid` empty, `wlan.ip` `0.0.0.0`, `services.dhcpd` 1.

Form `wifiform`, fields sent to `/captive.cgi` (OBSERVED in the page):

| Field | Values |
|---|---|
| `type` | `POST` (hidden) |
| `essid` | network name, 0 to 32 printable ASCII characters; filled from the scan list |
| `security` | `none`, `wep`, `wpa`, `wpatkip`, `wpaaes`, `wpa2`, `wpa2tkip`, `wpa2aes` |
| `authtype` | `1`, `2` (WEP) |
| `wep_key_length`, `wep_key_type` | `wep64`, `wep128`; `1` HEX, `2` ASCII |
| `wep_key`, `wep_key_id` | WEP key; key index `1` to `4` |
| `wpa_auth` | `WPA-PSK`, `WPA-EAP` |
| `wpa_key` | WPA passphrase, 8 to 63 printable ASCII characters |
| `wpa_eap`, `wpa_inner` | `TTLS`; `auth=MSCHAPV2` |
| `wpa_ident`, `wpa_user`, `wpa_passwd` | EAP identity, user and password |
| `inform_addr` | controller address, default `mfi.ubnt.com`, up to 268 characters |
| `cloud_name`, `cloud_pass` | mFi cloud account; the page labels them "User" and "Password" for a personal controller |

The mPort Quick Start Guide describes the same controller settings on its Configuration tab: the address is "the IP address and http port used by the Controller", usually 6080, for example `mfi.acme.com:6080`; user name and password are the controller administrator credentials. For the Wi-Fi page fields `inform_addr`, `cloud_name` and `cloud_pass` this meaning is INFERRED.

States used by the page script after Apply (OBSERVED):

- `host.cp_state`: `none`, `wifipending`, `wifitimeout`, `iptimeout`, `ctrlconnected`, `ctrltimeout`, `ctrlerror`, `byebye`.
- `host.ctrl_state`: `unknown`, `default`, `managed`, `selfrun`, `upgrade`.
- Wi-Fi connected: `wireless.essid` set, `wireless.apmac` not all zeros, `wlan.ip` not `0.0.0.0`.
- Controller connected: `ctrl_state` `managed`, or `unknown` with `cp_state` `ctrlconnected` or `byebye`. Then the page posts `/leaveap.cgi` and polls `ping.cgi` on the new address.

Open questions for this mode: 15 to 17 below.

## Controller backups (`.unf`)

The controller 2.1.11 backup format matches UniFi: AES-128-CBC with the public UniFi backup key, giving a ZIP with `db.gz`, `format`, `timestamp`, `version` (verified on real backups).

- Measured: in 4 of 4 real backups, Python `zipfile` could not read the ZIP central directory. Reading the local file headers one by one and inflating with zlib works.
- `db.gz` is a stream of MongoDB BSON documents. A document `{"__cmd": "select", "collection": "<name>"}` marks the start of each collection.
- `db.gz` contains device keys: **never commit backups or their content.**

## Device configuration (setparam)

Status: OBSERVED or UNVERIFIED per item below. Source: the REA report on `ace.jar` 2.1.11, questions 1 and 2. The report cites classes by their number in the report (n.2, n.8). Where it gives no method name, the citation gives the class only.

The `setparam` message itself is described under "Controller responses" (OBSERVED, `ConfigService`). This section does not repeat or change that paragraph.

- OBSERVED (`DeviceManager`, n.8, inform handler): a `setparam` is sent when `cfgversion` differs from the device (with `port_cfg` only if `portversion` also differs or is missing), when `portversion` differs, after a reboot (uptime lower than expected: `port_cfg`, `device_cfg` and, for M2S, `ser2net_cfg`), when `new_config` is set (`port_cfg` and `device_cfg`), when `resetcounter` is set (`port_cfg`), and when a device that still uses the adoption key informs (a new key goes in `mgmt_cfg`).
- OBSERVED (`DeviceManager`, n.8, change listener): a rename, and a change of the WLAN, admin, timezone, rsyslog, country or guest access settings, change `cfgversion`. A change of `port_cfg` or `device_cfg` changes `portversion`.
- OBSERVED (`DeviceManager`, n.8): the device confirms a configuration by sending back the same `cfgversion` or `portversion` in its inform. When the value matches, the controller sends nothing. After a send, the device state becomes 5, with a 120 second timeout.
- OBSERVED (`ConfigService`, n.2): the device name is the `name` field of the `device` collection. `system_cfg` carries it only as a host name, with non-alphanumeric characters removed and at most 31 characters.
- OBSERVED (`ConfigService`, n.2; `DeviceManager`, n.8): each port label is the `label` field of its `sensor` record (`mac`, `port`, `model`, `label`) and is sent as `port.N.label` in `port_cfg`. The default label is "Outlet" plus the last 6 characters of the MAC without colons plus the port number; the IWD1U type is "Dimmer Switch". If the local version block of the inform reports changed labels, the controller updates `sensor.label`.
- OBSERVED (`ConfigService`, n.2, outlet part): for each outlet, `relay` and `output` come from the configured state (`configed_val`) or the reported state (`output_val`); for IWD1U only `output` is sent. `lock` comes from `output_lock`, and the `rep_*` flags and `*_tag` names are sent too. `device_cfg` carries `dimmer_mode` (default `switch`). Tags, maps and `sensor.tags` stay in the controller.
- OBSERVED (`DeviceManager`, n.8; `DbService`, n.10): the `mfi-output` command has a `timer` field in seconds, default 0. A global setting `outputTimer` also has default 0.
- INFERRED: the state at power-on. The `relay` and `output` values sent to the device come from `configed_val` when it exists, otherwise from `output_val` (`ConfigService`, REA 2 quater, n.13). The reasoning: the configured value is the state the controller last asked for, and it is sent again in the configuration after a reboot (the reboot rule of "Controller responses"). The report shows no field named for power-on. Not tested on a device.
- OBSERVED as rules, not sent to the device: the thresholds of an outlet are stored in the rulesets of the controller (`ruleset`, REA 2 quater, n.8) and do not reach the device. The report found no threshold field in `ConfigService`, `DeviceManager` or the sensor service. See "Rules and scenes".

The report found no new command to the device, so the table under "Commands to the device" is unchanged.

## Events

Status: OBSERVED or UNVERIFIED per item below. Source: the REA report on `ace.jar` 2.1.11, question 3, and the serial kick event of section 6 of "mPort and sensors (from ace.jar 2.1.11)". The report cites classes by their number; where it gives no method name, the citation gives the class only.

- OBSERVED (`EventManager`, n.6; `DbService`, n.10): events are saved in the collection `event`, rule and scene actions in `actionevent`, and alarms in `alarm`.
- OBSERVED (`EventManager`, n.6, event creation method): a saved event has `datetime`, `ttl_time` (same date), `key` (the event type), `msg` (localized text), and the fields the caller passes, such as `ap` (device MAC), `sId` (sensor id as ObjectId), `admin`, `version_from`, `version_to` and `duration`.
- OBSERVED (`DbService`, n.10): when the key has a definition in `alarmdef`, the event creates or updates an `alarm` with the fields `archived`, `occurs` and `handled_*`. The definitions created at startup are DiscoveredPending, RediscoveredPending, Lost_Contact, WU_AssocPending, WG_AssocPending and AD_UpdateAvailable.
- OBSERVED (`DeviceManager`, n.8): the event keys and what raises them:

| Key | Raised when |
|---|---|
| `EVT_AP_DiscoveredPending` | a new device is found |
| `EVT_AP_RediscoveredPending` | an adopted device informs again |
| `EVT_AP_AutoReadopted` | automatic re-adoption |
| `EVT_AP_Adopted` | adoption by the administrator |
| `EVT_AP_Deleted` | deletion |
| `EVT_AP_Restarted` | restart requested by the administrator |
| `EVT_AP_UpgradeScheduled` | upgrade scheduled |
| `EVT_AP_Upgraded` | version changed |
| `EVT_AP_Connected` | first connection after a loss |
| `EVT_AP_Lost_Contact` | more than 120 seconds without an inform |
| `EVT_AP_RestartedUnknown` | uptime lower than expected |
| `EVT_WU_Disconnected`, `EVT_WG_Disconnected` | Wi-Fi client disconnected |
| `EVT_WC_Blocked`, `EVT_WC_Unblocked` | a client blocked or unblocked |
| `EVT_mFi_SerialKick` | serial command |
| `EVT_mFi_Action` | action of a rule or scene (saved in `actionevent`) |
| `EVT_<product>_SensorRuleset` | "event" action of a rule (n.12) |

- OBSERVED (`DeviceManager`, n.8): a device with no inform for more than 40 seconds gets state 6. After more than 120 seconds the controller raises `EVT_AP_Lost_Contact`. The check timer runs every 60 seconds.
- Already known: `EVT_AP_Lost_Contact` (OBSERVED, see "Device states in the controller") and `EVT_mFi_SerialKick` (OBSERVED, section 6 of "mPort and sensors (from ace.jar 2.1.11)").
- OBSERVED (the localization method, inner class 51, REA 2 quater, n.11): the text comes from a resource file named `messages`, read in the language of the system under the event key. A name in curly brackets is replaced with the field of the same name from the event. A missing key gives the key itself between two tildes.
- UNVERIFIED: the texts themselves. The `messages` file is not in the code and REA could not read it. Searched `EventManager` and the localization method (n.11).
- OBSERVED (`DbService`, REA 2 quater, n.14): at startup the controller creates the alarm definitions `EVT_AP_DiscoveredPending`, `EVT_AP_RediscoveredPending`, `EVT_AP_Lost_Contact` (with repeat set), `EVT_WU_AssocPending`, `EVT_WG_AssocPending` and `EVT_AD_UpdateAvailable`. `EVT_AD_UpdateAvailable` is not in the table above. When it is raised is UNVERIFIED: its trigger is not in the classes read.
- OBSERVED (`EventManager` and the rule action handler, REA 2 quater, n.9 and n.10): a sensor rule event uses the key `EVT_<product>_SensorRuleset`. For this product the product name is `mFi`, so the key is `EVT_mFi_SensorRuleset`. The action key `EVT_mFi_Action` is raised by rule and scene actions (n.9, n.6).
- UNVERIFIED: the complete list of `EVT_*` keys. Searched `DeviceManager`, `DbService`, the rule action handler and `EventManager`; the report found the keys listed above and no others.
- UNVERIFIED: an event for a sensor threshold other than `SensorRuleset`. Searched the rule action handler (n.9) and `EventManager` (n.10): none found.

## Rules and scenes

Status: OBSERVED or UNVERIFIED per item below. Source: the REA reports on `ace.jar` 2.1.11. The first run classes are cited as n.3, n.11, n.12, n.13 and n.14; items from the full re-run (REA 2 quater) cite its output numbers. The citations give the class or the inner class. No rule is imported by this section; rule import belongs to a later epic.

- OBSERVED (n.3, n.13, n.14): collections `rule` (fields `label` and `val`, default -1, and `type` "embed"), `ruleset` (conditions), `ruleaction`, `rulestate`, `rulestatecalendar`, `ruleschedule`, `rulecondition`, `scene`, `sceneaction` and `script`.
- OBSERVED (`service.D`, inner class 31, rules engine, n.11): a condition in `ruleset` has `rulesetId` (ObjectId of the rule), `rulesetName`, `trigger`, `sId`, `type`, `compare`, `limit`, `duration`, `enable`, `allorany`, `edgeorlevel` and `conditionset`. Its state is kept in `violation`, `condition_since` and `last_checked`.
- OBSERVED (n.11): `trigger` is `sensor`, `state` or `time`.
- OBSERVED (n.11): `compare` 0 means greater than, 2 equal and 4 less than. `duration` is in minutes. `allorany` is `all` (default) or `any`; `edgeorlevel` is `edge` (default) or `level`.
- OBSERVED (`service.D`, inner class 33, rule actions, n.12): a `ruleaction` has `rulesetId`, `type`, `sId`, `val`, `timer`, `minute` (minimum minutes between two actions), `addr` (list of addresses, for e-mail and URL actions), `scriptId` and `stateId`.
- OBSERVED (rule action handler, inner class 33, REA 2 quater, n.9): `type` of `ruleaction` has eight values: `email`, `event`, `relaySwitch`, `script`, `state`, `url`, `scene` and `rule`. The words outlet, output and notification are not values of this field. Behaviour of each value:
  - `email`: sent only when `enable` is true, to each valid address of `addr`, at most once per `minute` minutes (the last send is kept in `last_time`).
  - `event`: saves an event. When `alert` is true the level is 2. The same `minute` interval applies.
  - `relaySwitch`: when the sensor has `output_lock` equal to 1, the port is locked, and the rule records an error and does nothing. Otherwise it sends a command to the port and creates an action event.
  - `script`: runs script `scriptId` on the device of sensor `sId`.
  - `state`: sets state variable `stateId` to `val`.
  - `url`: with `enable` true, sends a POST whose body has URL-encoded `rule`, `sensor` and `value` fields (inner classes 33 and 30, n.9).
  - `scene`: starts scene `sceneId` in a separate thread.
  - `rule`: enables or disables the ruleset `raId`, as `val` says.
- OBSERVED (scene, inner class 34, REA 2 quater, n.6): a `scene` has `label` and `_id`, the latter set by the database. A `sceneaction` has `sceneId`, `sId` and `scriptId` (ObjectIds), `type`, `val`, `timer`, `dimmer_level` and `dimmer_ramp`. The `type` of a scene action is `relaySwitch`, `script` or `url`; `email`, `event`, `scene` and `rule` do not occur. The save operation receives `sceneId` (the value "NEW" creates a scene), `sceneName` and the list of actions. It deletes the old actions of the scene and inserts the new ones. The default `dimmer_ramp` is 2 in a scene and 1 in a rule. A scene also raises `EVT_mFi_Action`.
- OBSERVED (time rules, scheduler, inner class 35, REA 2 quater, n.7): a time rule is a `RuleStateCalendar` record with `trigger` set to `time`, a `stateId`, `start` and `end`. Both are minutes from the start of the week: Sunday at 00:00 is 0, each day adds 1440 minutes, and the week has 10080 minutes. An interval whose `end` is smaller than `start` crosses Sunday midnight, and 10080 is added to `end`. The time zone is the server time zone, read from the setting `timezone` (field `zone`, default `PST`). The state `RuleState` has `val` 1 inside the interval and 0 outside, and `lastRunTime` keeps the last check. A ruleset of type state or time fires when the state's `val` equals its `limit`.
- OBSERVED (scheduler constants, inner class 35, n.7): the time-rule job starts 20 seconds after startup and then runs every 5 seconds. A second job starts after 600 seconds and then every 60 seconds; it checks the sensor rulesets with `compare` equal to 2 and `duration` above 0. A state rule is not run again within 1,800,000 milliseconds (30 minutes).

## Statistics

Status: OBSERVED or UNVERIFIED per item below. Source: the REA report on `ace.jar` 2.1.11, question 5 (ticket T-MWMG5EW9, rest of the report). Items cite the report's output number (n.X) where it gives one, otherwise its section.

- OBSERVED (report section 5, "Misure"): every measurement point is saved in the collection `m2mgeneric` with the fields `sId`, `tag`, `type`, `val`, `time` (milliseconds) and `ttl_time`. The name matches `M2mgeneric` in the mPort part below (same collection, INFERRED from the name).
- OBSERVED (n.20): for every numeric value the controller updates four aggregate collections: `minute` (60 s), `quarterhour` (900 s), `hour` (3600 s) and `day` (86400 s). Each aggregate record has `sId`, `tag`, `type`, `time`, `max`, `min`, `ave`, `size` (number of values), `last_val`, `last_val_time` and `ttl_time`.
- OBSERVED (n.10): a read chooses the collection by the length of the requested interval: more than 60 days uses `day`, more than 7 days uses `hour`, more than 1 day uses `quarterhour`, otherwise `minute`. Intervals are capped at 3 years.
- OBSERVED (report section 5, "Energia e contatori"): counters are cumulative. A new value below 90% of the previous one is treated as a reset, and the previous value is added to a base.
- OBSERVED (report section 5, "Stato"): `stat.*` covers Wi-Fi, users and devices, not measurements.
- OBSERVED (n.10): the indexes on `ttl_time` are created without an explicit expiry. The `storage` setting has `enable` and `ttl_time`; its default is 13 (unit UNVERIFIED, see below).
- UNVERIFIED: the unit of the `storage` default 13. The default itself is OBSERVED (`DbService`, REA 2 quater, n.14, with `enable` true). Searched `DbService`, `SystemService`, the inner class 46 and `DeviceManager`: the report found no code that reads this setting, so the unit is not known.
- UNVERIFIED: the job that deletes old data. Indexes on `ttl_time` exist for `day`, `hour`, `quarterhour`, `minute`, `m2mgeneric`, `event`, `actionevent` and `alarm` (eight indexes, `DbService`, REA 2 quater, n.14), created without an expiry time. The report found no deletion job in the classes read (`DbService`, the scheduler of inner class 35, `DeviceManager`). Not verified that old data is removed.

## Open questions (need a real device)

1. The exact inform JSON of an mPower and of an mPort.
2. Whether firmware 2.1.11.1309 ever compresses.
3. Whether the device accepts the extra command fields `_id`, `device_id`, `datetime`.
4. The mPort `port_cfg` format, line by line. (answered for the controller side; how the device applies each line is UNVERIFIED - see section "mPort and sensors (from ace.jar 2.1.11)", subsection 3)
5. When `x_prev_authkey` appears.
6. What a factory-reset device sends on first adoption.
7. Whether a factory device looks up `http://mfi:6080/inform` by itself.
8. Firmware of devices not in the backups.
9. Load with 50 devices (about 5 requests per second at one inform every 10 s).
10. Whether the portal user and password travel in the inform.
11. mPort processor, system and factory reset.
12. Whether a modern SSH library accepts the devices' legacy algorithms.
13. Real memory of mPower mini and PRO.
14. After how many seconds without an inform the controller shows a device as heartbeat lost (40 s or 60 s). (answered: see section Events)
15. The exact `inform_addr` format accepted by the Wi-Fi setup page (`host:6080` like the mPort, or a full inform URL).
16. What `cloud_name` and `cloud_pass` do with a personal controller, and whether they travel in the inform (see question 10).
17. What a Wi-Fi device does after Apply when the home network or the controller is not reachable, and whether the mPort setup page is TLS 1.0 only too.
