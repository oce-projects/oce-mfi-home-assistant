# Device and protocol notes

Status: public sources collected on 2026-11-15, plus the decompiled controller code. Source of the code facts: `mFi/lib/ace.jar` from `mFi.unix.zip` 2.1.11 (ace.jar 777,033 bytes, sha256 `dbf83f894eb15e4ac24b8729246642832206a02bbd3fd173d2459ef21c7a5bbe`, 205 classes, obfuscated), decompiled with the FernFlower decompiler. References give class and method names; obfuscated names are kept as they are. The decompiled source is not in this repository (vendor code, AGENTS.md rule 1).

Labels used below:

- OBSERVED: read in the decompiled code.
- BYTECODE: also checked with `javap -c` on the original class.
- INFERRED: deduced from the code or from other facts; the reason is given.
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

- Default key: `ba86f2bbe107c7c57eb5f2690775c712`. It is fixed in the code, the same for every reset device, and already public (`mcrute/ubntmfi`).
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
- INFERRED, approximate reading: the controller stores next heartbeat = now + 20 s and considers the device lost at now + 60 s.
- The 15 s retry in the forum log is the case of a device that cannot find a controller.
- OBSERVED: `cfgversion` and `portversion` are not hashes. They are 16 random hex characters (`java.util.Random`), regenerated on every change. A mismatch makes the controller resend the configuration.

`setparam` (OBSERVED, `ConfigService`): message fields `_type=setparam`, `cfgversion`, `system_cfg`, `mgmt_cfg`, `port_cfg`, `device_cfg`, `blocked_sta`, `authorized_guests`, and `ser2net_cfg` only for M2S. Each `*_cfg` is text of `key=value` lines.

- `mgmt_cfg`: `mgmt.is_default=false`, `mgmt.authkey=<key>` (only when the key used by the device differs from `x_authkey`), `mgmt.cfgversion`, `mgmt.portversion`, `mgmt.localversion`, `mgmt.servers.1.url=http://<host>:<port>/inform`, `mgmt.selfrun_guest`.
- `system_cfg`: `users.1.name=<controller admin name>`, `users.1.password=<DES crypt of the admin password, random 2-letter salt>`. After adoption, the device SSH and web user is the controller administrator. INFERRED, approximate: services `telnetd`, `snmp`, `dhcpd`, `dnsmasq` disabled; `httpd.port=80`; bridge `br0`; syslog on; server time zone; host name from the device name (max 31 characters). Interface `eth1` for P1U, P1E, P3U, P3E, P8U, P6E, IWO2U, IWS1U, IWD1U; `eth0` for the others.
- `port_cfg` for mPower and in-wall outlets. For each outlet K: `vpower.K.relay=0|1`, `vpower.K.output=0|1`, `vpower.K.lock`, `vpower.K.rep_output=1`, `rep_pf`, `rep_energy_sum`, `rep_v_rms`, `rep_i_rms`, `rep_active_pwr`, and tags `vpower.K.output_tag=output`, `pf_tag=pf`, `energy_sum_tag=energy_sum`, `v_rms_tag=v_rms`, `i_rms_tag=i_rms`, `active_pwr_tag=active_pwr`. Plus `port.N.model`, `port.N.label`, `port.N.sensorId` (or `port.N.mode=off` for an empty port). The device reports only quantities with `rep_<name>=1`.
- `port_cfg` for mPort (M2M, M2S): lines `port.N`, `PWR.N`, `AI.N`, `DI.N`, `DO.N`. UNVERIFIED, not analysed line by line.
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

- `energy_sum`, OBSERVED: when a new value is below 0.9 times the last one, the controller treats the counter as reset and adds the old value to a base. It discards increases above 0.001 Wh per millisecond.
- OBSERVED: `type="detected"` with `index="DI<n>"` means a new sensor on an mPort, not yet configured.
- The value of `type` for analog readings: UNVERIFIED.
- Third-party measurement, UNVERIFIED on our units: the mPower energy counter is kept in RAM and restarts from zero after a power loss (`feiglein74/mpower`).

## Discovery (UDP 10001)

OBSERVED (`DatagramQueryServer`, `LiteStationQueryServer`):

- UDP port 10001, multicast `233.89.188.1` and broadcast `255.255.255.255`.
- Request of 4 bytes `01 00 00 00` (version 1, command 0, length 0).
- Reply: version, command, length, then TLV fields `type (1 byte) length (2 bytes) data`.
- Main types: 1 MAC, 2 MAC+IPv4, 3 version, 10 uptime, 11 hostname, 12 platform, 21 model, 22 firmware version, 23 "default" flag.
- No keys or configuration in discovery.

## Device states in the controller

| State | Meaning | Timeout |
|---|---|---|
| 0 | initial or disconnected | |
| 1 | connected | |
| 2 | discovered, pending adoption | |
| 4 | firmware upgrade | 180 s |
| 5 | configuration sent | 120 s |
| 6 | heartbeat lost (no inform for more than 40 s) | |
| 7 | adopting | 120 s |
| 8 | being deleted | |

- OBSERVED: after 120 s without an inform the device is lost (`EVT_AP_Lost_Contact`).
- The meanings of states 0, 5, 6 and 8 are INFERRED (no names in the code).

## Security summary

- Fixed public default key, and SSH `ubnt` / `ubnt` without host key check, for first contact.
- Adoption key from `java.util.Random`.
- The administrator password is stored in clear text and reused as the SSH password of every adopted device.
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

## Controller backups (`.unf`)

The controller 2.1.11 backup format matches UniFi: AES-128-CBC with the public UniFi backup key, giving a ZIP with `db.gz`, `format`, `timestamp`, `version` (verified on real backups).

- Measured: in 4 of 4 real backups, Python `zipfile` could not read the ZIP central directory. Reading the local file headers one by one and inflating with zlib works.
- `db.gz` is a stream of MongoDB BSON documents. A document `{"__cmd": "select", "collection": "<name>"}` marks the start of each collection.
- `db.gz` contains device keys: **never commit backups or their content.**

## Open questions (need a real device)

1. The exact inform JSON of an mPower and of an mPort.
2. Whether firmware 2.1.11.1309 ever compresses.
3. Whether the device accepts the extra command fields `_id`, `device_id`, `datetime`.
4. The mPort `port_cfg` format, line by line.
5. When `x_prev_authkey` appears.
6. What a factory-reset device sends on first adoption.
7. Whether a factory device looks up `http://mfi:6080/inform` by itself.
8. Firmware of devices not in the backups.
9. Load with 50 devices (about 5 requests per second at one inform every 10 s).
10. Whether the portal user and password travel in the inform.
11. mPort processor, system and factory reset.
12. Whether a modern SSH library accepts the devices' legacy algorithms.
13. Real memory of mPower mini and PRO.
