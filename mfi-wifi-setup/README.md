# mFi Wi-Fi Setup (Windows helper)

Version 0.1.0 - prototype. The Windows program is not built yet.

Wi-Fi mFi devices (mPower, mPower mini) without a Wi-Fi configuration run their
own access point and serve their setup page at `https://192.168.2.20`, over
TLS 1.0 only. Current browsers refuse TLS 1.0, so the page cannot be opened.
This folder will hold a small Windows program that opens that page from the
browser the user already has. Wired devices do not need it: mfi-server finds
them on the LAN.

- Specification, tests and tickets: `docs/WIFI-SETUP.md`
- Device facts (TLS, endpoints, form fields, states): `docs/PROTOCOL.md`,
  section "Wi-Fi setup mode"

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

## Rules

- The built `.exe` is never committed (AGENTS.md rule 1). It is published as a
  release asset with its sha256.
- This folder is not a Home Assistant add-on: it has no `config.yaml`.
