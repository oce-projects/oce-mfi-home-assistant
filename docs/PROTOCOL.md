# Device and protocol notes

Status: collected from public sources on 2026-11-15. Reverse engineering of
`ace.jar` 2.1.11 is in progress; its results will be added here with class and
method references. Anything marked `UNVERIFIED` must not be relied on.

## Devices

| Family | Models (from official Quick Start Guides) |
|---|---|
| mPower | mPower (3 outlets, US/EU), mPower mini (1 outlet, US/EU), mPower PRO (8 outlets US, 6 outlets EU) |
| mPort | mPort, mPort Serial |
| In-wall | outlet MPW / MPW-W, switch LD / LD-W |
| Sensors | mFi-CS (current), mFi-DS (door), mFi-MSC (ceiling motion), mFi-MSW (wall motion), mFi-THS (temperature) |

mPower runs Linux on a MIPS SoC (Atheros AR9330, from public reports,
UNVERIFIED on our units), Wi-Fi interface `ath0`, mDNS name
`mFi-mPower-<last MAC digits>.local`, services `ssh` and `web`.

## Inform (device to controller)

- HTTP POST to `http://<controller>:6080/inform`.
- Default controller address: host name `mfi`, polled every 15 s when unreachable
  (device log, firmware MF.v2.1.4 build 1301). After 10 failures the device
  restarts its Wi-Fi client.
- The controller address can also be set in the device web page as `IP:6080`
  (official FAQ).
- Packet: magic `TNBU`, AES-CBC encryption, a fixed default key before adoption,
  then a per-device `authkey` (public reverse engineering: `mcrute/ubntmfi`,
  archived 2017). Field layout, compression and adoption flow: UNVERIFIED until
  checked against `ace.jar`.
- Commands from controller to device, e.g. `mfi-output` to switch an outlet:
  UNVERIFIED.

## Local control without a controller (mPower)

From public projects, UNVERIFIED on our units:

- HTTP: `/login.cgi`, `/mfi/sensors.cgi`, `PUT /sensors/<n>`.
- SSH (legacy ciphers): relay state in `/proc/power/relay<n>`, readings in
  `/proc/power/*`.
- mPort local API: not documented.

## Factory state

- Default credentials `ubnt` / `ubnt`.
- Direct connection default IP `192.168.1.20`; DHCP on a LAN.
- Reset: hold the reset button until the LED changes (exact pattern per model in
  the Quick Start Guides).

## Controller backups (`.unf`)

The controller 2.1.11 backup format matches UniFi: AES-128-CBC with the public
UniFi backup key, giving a ZIP with `db.gz`, `format`, `timestamp`, `version`
(verified on real backups). `db.gz` is a MongoDB dump and contains device keys:
**never commit backups or their content.**
