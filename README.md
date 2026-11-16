# oce-mfi-home-assistant

![License](https://img.shields.io/badge/license-Apache--2.0-blue) [![tests](https://github.com/oce-projects/oce-mfi-home-assistant/actions/workflows/tests.yml/badge.svg)](https://github.com/oce-projects/oce-mfi-home-assistant/actions/workflows/tests.yml)

Home Assistant add-ons to bring **Ubiquiti mFi** devices back to life:
mPower and mPower PRO/mini power strips, mPort and mPort Serial sensor hubs,
in-wall outlets and switches, and mFi sensors (current, door, motion, temperature).

The mFi product line and its controller software were discontinued by Ubiquiti.
Many devices still work fine. This repository aims to run them from
Home Assistant OS, locally, without the vendor cloud.

> Status: **early work, public.** The `mfi-server` app installs from this repository (experimental, not yet tested with a real device).

## Plan

| Phase | Add-on | What it does | Status |
|---|---|---|---|
| 1 | mFi Controller (original): `mfi-controller` | runs the original mFi Controller 2.1.11 in a container; Home Assistant talks to it with the core `mfi` integration | tested with Docker, not yet on HAOS (version in `mfi-controller/config.yaml`) |
| 2 | mFi Server (new): `mfi-server` | our own server that speaks the device protocol directly and creates Home Assistant entities, without vendor code | in progress: inform core in pure Python (encryption, keys from .unf backups, states, commands, measurements); Home Assistant entities through MQTT discovery (broker optional); not yet tested with a real device (version in mfi-server/config.yaml). It also runs on its own, outside Home Assistant: see [mfi-server/README.md](mfi-server/README.md) |

**Which one?** For normal use, choose **mFi Server (new)**. **Ubiquiti mFi Controller (original)** is the unchanged Ubiquiti controller from 2015: use it only for comparison and to capture device traffic.

Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
Phase 2 add-on notes: [mfi-server/DOCS.md](mfi-server/DOCS.md).

Project: [CHANGELOG.md](CHANGELOG.md), [security policy](SECURITY.md),
[contributing guide](CONTRIBUTING.md), [open issues](https://github.com/oce-projects/oce-mfi-home-assistant/issues).

## Install

Home Assistant now calls add-ons "apps". The `mFi Server` app is installed from
this repository (experimental, not yet tested with a real device).

1. Optional, for the Home Assistant entities: install an MQTT broker app, for
   example Mosquitto. MQTT is optional: without a broker the server still runs.
2. In Home Assistant: Settings, Apps, App store, menu (three dots), Repositories.
   Add the URL `https://github.com/oce-projects/oce-mfi-home-assistant`.
3. Install the app `mFi Server` from the store. The first build takes a few minutes.
4. Copy the controller backup (`.unf`) into `/share` and write its path in the
   `backup_file` option, for example `/share/backup.unf`.
5. Start the app.
6. Open `mFi` in the sidebar.

To test a local change, copy the add-on folder into the local apps folder of
Home Assistant OS (the `local_apps` share of the Samba app, or `/addons` in the
Advanced SSH & Web Terminal app). Step-by-step guide for the original controller:
[mfi-controller/DOCS.md](mfi-controller/DOCS.md).

## Vendor software

This repository contains **no Ubiquiti software**. The phase 1 add-on downloads
the official mFi Controller package from Ubiquiti when it is built and checks
its sha256. You are responsible for complying with Ubiquiti's license.

## Security

The mFi firmware and the 2015 controller are old. Keep mFi devices on an
isolated network and never expose ports 6080, 6443 or 3478 to the internet.

## For contributors and agents

Read [AGENTS.md](AGENTS.md). Tests: `python3 -m unittest discover -s tests -v`.
mfi-server tests: `python3 -m unittest discover -s mfi-server/tests -t mfi-server -v`.

## Credits

Add-on icons drawn by `tools/make_icons.py` after the Material Design Icons "power-socket-eu" glyph (Pictogrammers, Apache License 2.0).

## License

Apache License 2.0, see `LICENSE`. The mFi Controller downloaded by the `mfi-controller` add-on at build time is proprietary Ubiquiti software and is not covered by this license.
