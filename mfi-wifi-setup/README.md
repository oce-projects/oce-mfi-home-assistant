# mFi Wi-Fi Setup (Windows helper)

Version 0.4.0 - the Windows program: the version 2 window (guided setup, the
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

## Version 2: guided setup (0.3.0)

The version 2 window does the whole setup in the program:

1. Join the PC to the Wi-Fi network of the device (step 1 checks the device).
2. Choose your home network in the list and type its password.
3. Press `Configure`. The window follows the device and shows the device address
   on your network when it has one.
4. Open mfi-server: it adopts the device.

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

## Build

Build the `.exe` on Windows. A person runs it; DevAgentAi cannot.

- Requirements: Windows 10 or 11, 64-bit; Python 3.12 or newer, from python.org or
  from the Microsoft Store. No administrator rights.
- Command: double-click `build_windows.cmd` in this folder, or run it from `cmd`.
- Output: `mfi-wifi-setup\dist\mfi-wifi-setup-<version>-windows-x64.exe` and the
  `.sha256` file next to it.
- Publication: attach both files as assets of a GitHub release.
- The `.exe` never enters the repository (AGENTS.md rule 1): `dist/` and `build/`
  are in the root `.gitignore`.

## Rules

- The built `.exe` is never committed (AGENTS.md rule 1). It is published as a
  release asset with its sha256.
- This folder is not a Home Assistant add-on: it has no `config.yaml`.
