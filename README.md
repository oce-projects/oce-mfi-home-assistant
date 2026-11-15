# mfi-home-assistant

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
| 1 | `mfi-controller` | runs the original mFi Controller 2.1.11 in a container; Home Assistant talks to it with the core `mfi` integration | in progress |
| 2 | `mfi-server` | our own server that speaks the device protocol directly and creates Home Assistant entities, without vendor code | not started |

Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Install (when an add-on is ready)

1. In Home Assistant: Settings, Add-ons, Add-on Store, menu, Repositories.
2. Add the URL of this repository.
3. Install the add-on from the store.

While the repository is private, an add-on can be tested by copying its folder
into the `/addons` folder of Home Assistant OS (local add-on).

## Vendor software

This repository contains **no Ubiquiti software**. The phase 1 add-on downloads
the official mFi Controller package from Ubiquiti when it is built and checks
its sha256. You are responsible for complying with Ubiquiti's license.

## Security

The mFi firmware and the 2015 controller are old. Keep mFi devices on an
isolated network and never expose ports 6080 or 6443 to the internet.

## For contributors and agents

Read [AGENTS.md](AGENTS.md). Tests: `python3 -m unittest discover -s tests -v`.

## License

To be decided.
