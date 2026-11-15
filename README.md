# oce-mfi-home-assistant

Home Assistant add-ons to bring **Ubiquiti mFi** devices back to life:
mPower and mPower PRO/mini power strips, mPort and mPort Serial sensor hubs,
in-wall outlets and switches, and mFi sensors (current, door, motion, temperature).

The mFi product line and its controller software were discontinued by Ubiquiti.
Many devices still work fine. This repository aims to run them from
Home Assistant OS, locally, without the vendor cloud.

> Status: **early work, private repository.** Nothing here is ready to install yet.

## Plan

| Phase | Add-on | What it does | Status |
|---|---|---|---|
| 1 | `mfi-controller` | runs the original mFi Controller 2.1.11 in a container; Home Assistant talks to it with the core `mfi` integration | tested with Docker, not yet on HAOS (version in `mfi-controller/config.yaml`) |
| 2 | `mfi-server` | our own server that speaks the device protocol directly and creates Home Assistant entities, without vendor code | in progress: inform core in pure Python (encryption, keys from .unf backups, states, commands, measurements); Home Assistant entities through MQTT discovery (broker optional); not yet tested with a real device (version in mfi-server/config.yaml) |

Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
Phase 2 add-on notes: [mfi-server/DOCS.md](mfi-server/DOCS.md).

## Install (when an add-on is ready)

Home Assistant now calls add-ons "apps".

1. In Home Assistant: Settings, Apps, App store, menu, Repositories.
2. Add the URL of this repository.
3. Install the app from the store.

While the repository is private, an app can be tested by copying its folder
into the local apps folder of Home Assistant OS: the `local_apps` share of the
Samba app, or `/addons` in the Advanced SSH & Web Terminal app (same folder).
Step-by-step guide: [mfi-controller/DOCS.md](mfi-controller/DOCS.md).

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

## License

To be decided.
