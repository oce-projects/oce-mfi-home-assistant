# mFi Wi-Fi Setup (Windows helper)

Version 0.5.2 - the Windows program: the version 2 window (guided setup, the
Wi-Fi network is chosen in the program) and the version 1 window (bridge to the
device page), in `mfi_wifi_setup/`. `build_windows.cmd` builds the `.exe` (see
"Build"); the first device test is ticket W3.

Wi-Fi mFi devices (mPower, mPower mini) without a Wi-Fi configuration run their
own access point and serve their setup page at `https://192.168.2.20`, over
TLS 1.0 only. Current browsers refuse TLS 1.0, so the page cannot be opened.
This folder will hold a small Windows program that opens that page from the
browser the user already has. Wired devices do not need it: mfi-server finds
them on the LAN.

- Specification, tests and tickets: `docs/WIFI-SETUP.md`
- Device facts (TLS, endpoints, form fields, states): `docs/PROTOCOL.md`,
  section "Wi-Fi setup mode"

## Run

From the `mfi-wifi-setup/` folder, with Python 3 (standard library only):

- `python -m mfi_wifi_setup` opens the window.
- On Windows, run it without a console window: `pythonw -m mfi_wifi_setup`.

Offline tests, from the repository root:

    python3 -m unittest discover -s mfi-wifi-setup/tests -t mfi-wifi-setup -v

## Step by step

Taken from the mPower mini (EU) Quick Start Guide, pages 3-4 and 12-15:

1. **Factory reset.** Press and hold the Reset button until the Status LED alternates colors (page 4). A quick press only restarts the device (page 4).
2. **Status LED** (page 3):

| Status LED | Meaning |
|---|-|
| Solid yellow | first powered on in factory default mode |
| Flashing yellow | connecting to a Wi-Fi network |
| Flashing blue | connecting to the mFi Controller |
| Solid blue | connected to the mFi Controller |

Taken from the mPower mini guide; for other Wi-Fi models UNVERIFIED.

3. **Join the device network.** In Windows, connect to the open Wi-Fi network whose name is `mFi` followed by the last six characters of the MAC address (page 12). The exact separator in the name is UNVERIFIED.
4. **Run the program** (`.exe` from the release, see "Download"). Step 1 checks the device and shows model and firmware.
5. **Choose the home network** and type its password; press `Configure`; wait until the window shows the device address on the home network. The LED goes from flashing yellow to flashing blue.
6. **Back to the home network.** Reconnect the PC to the home Wi-Fi network if Windows does not do it by itself (page 15, step 9).
7. **Adoption.** With mfi-server: version 1.0.0 does not adopt devices yet (adoption is not wired in mfi-server/mfi_server_next/__main__.py); until a later version, adopt the device with the original controller (mfi-controller add-on). With the original controller (mfi-controller add-on): the device appears as pending and must be adopted by hand, because the program does not write the controller fields. Alternative: the version 1 button "Open the device page" shows the original portal, where Address (controller IP and port 6080, for example `HOME-ASSISTANT-IP:6080`), User and Password of the controller can be entered (page 14); with those the device can be adopted by the controller without pressing Adopt (UNVERIFIED with this program).

## Troubleshooting

- SmartScreen or the antivirus warn: the `.exe` is not code-signed; check the sha256 first (see "Download").
- The device network does not appear: do a factory reset again (step 1).
- The LED keeps flashing yellow: wrong Wi-Fi password or a network type that is not listed (WEP, enterprise); reset and repeat. (cause UNVERIFIED: not in the Quick Start Guide).
- The LED keeps flashing blue: the device is on the home network but no controller answers on port 6080; check that mfi-server (or mfi-controller) is running and that only one of them uses port 6080. (cause UNVERIFIED: not in the Quick Start Guide).

## Version 2: guided setup (0.3.0)

The version 2 window does the whole setup in the program:

1. Join the PC to the Wi-Fi network of the device (step 1 checks the device).
2. Choose your home network in the list and type its password.
3. Press `Configure`. The window follows the device and shows the device address
   on your network when it has one.
4. Adopt the device with the original controller: mfi-server 1.0.0 does not adopt devices yet (see "Step by step", step 7).

- Only open networks and WPA/WPA2 personal networks are listed. WEP and enterprise
  networks are not.
- The program never changes the controller fields of the device, and it does not
  ask for a controller address.
- The password is never written to disk or to the log.
- The version 1 button "Open the device page" stays as an alternative.

Sources, and the points still unverified on a device: `docs/WIFI-SETUP.md`.

## Prototype

`prototype/legacy_tls_proxy.py`, Python standard library, verified on a device
on 2026-11-17.

1. Join the PC to the Wi-Fi network of the device.
2. Run `python prototype/legacy_tls_proxy.py --open`.
3. The browser opens `http://127.0.0.1:8020/` with the device page.
4. Close the window to stop.

The proxy listens on 127.0.0.1 only, does not verify the device certificate
(self-signed and expired) and never writes query strings to its log: the
setup form sends the Wi-Fi password in the query string.

## Download

The Windows program is built by GitHub Actions on a Windows runner and attached
to every published release of this repository (workflow
`.github/workflows/windows-exe.yml`). The `.exe` is not stored in the repository.

1. Open the latest release on the GitHub page of the repository.
2. Download `mfi-wifi-setup-<version>-windows-x64.exe` and its `.sha256` file.
3. Check the hash before you run the program. In `cmd`, from the download folder:

    certutil -hashfile mfi-wifi-setup-<version>-windows-x64.exe SHA256

   The hash printed by `certutil` must equal the hash in the `.sha256` file.

The `.exe` is not code-signed, so Windows SmartScreen or an antivirus program may
warn about it. Run it only when the hash matches.

## Build

Build the `.exe` on Windows. A person runs it; DevAgentAi cannot.

- Requirements: Windows 10 or 11, 64-bit; Python 3.12 or newer, from python.org or
  from the Microsoft Store. No administrator rights.
- Command: double-click `build_windows.cmd` in this folder, or run it from `cmd`.
- Output: `mfi-wifi-setup\dist\mfi-wifi-setup-<version>-windows-x64.exe` and the
  `.sha256` file next to it.
- Publication: GitHub Actions builds the `.exe` on `windows-latest` and attaches
  both files to each published release (see "Download").
- The `.exe` never enters the repository (AGENTS.md rule 1): `dist/` and `build/`
  are in the root `.gitignore`.

## Rules

- The built `.exe` is never committed (AGENTS.md rule 1). It is published as a
  release asset with its sha256.
- This folder is not a Home Assistant add-on: it has no `config.yaml`.
