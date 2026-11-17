# Changelog - mfi-wifi-setup

## 0.2.0 - 2026-11-17

- Version 1 of the program, from the verified prototype: a Windows window
  (`tkinter`, no console) with numbered steps, started with
  `python -m mfi_wifi_setup` from this folder. The `.exe` is not built yet
  (ticket W2).
- Core modules without `tkinter`: `bridge.py` (local bridge to the device page
  on 127.0.0.1, next free port when 8020 is busy), `device_check.py` (device
  state every 2 s), `messages.py` (Italian and English), `config_store.py` (the
  controller address only).
- Offline tests in `tests/` with the standard library: the core does not import
  `tkinter`, and the version matches this changelog.
- Specification in `docs/WIFI-SETUP.md`, version 0.2.0. The prototype
  `prototype/legacy_tls_proxy.py` is unchanged.

## 0.1.1 - 2026-11-17

- The program will be a graphical window (`tkinter`) with numbered steps, no
  console; specification 0.2.0 in `docs/WIFI-SETUP.md`. The prototype is
  unchanged.

## 0.1.0 - 2026-11-17

- Prototype `prototype/legacy_tls_proxy.py`: local bridge from the browser
  (plain http on 127.0.0.1) to the device setup page (TLS 1.0). Verified on an
  mPower mini with firmware v2.1.11: the setup page (36,535 bytes) and the JSON
  of `captivepoll.cgi`, `status.cgi` and `survey.json.cgi` come through; query
  strings are hidden in the log. Not verified yet: Apply (`captive.cgi`) and
  the switch of the device to the home network.
- Specification in `docs/WIFI-SETUP.md`.
