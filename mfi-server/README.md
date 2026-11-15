# mFi Server

Our own controller for Ubiquiti mFi devices: the devices report to this server
directly, without the 2015 mFi Controller.

## Status

In progress. Standard library only. Not yet tested with a real device or on
Home Assistant OS.

## Features

- Encrypted inform packets (AES-128-CBC).
- Keys read from `.unf` controller backups.
- Device states and outlet commands.
- Measurements.
- Never sends a factory reset to a device.
- MQTT discovery for Home Assistant (optional in standalone mode).
- JSON web API on port 8099, and measurement history in `history.sqlite3` (30 days by default).

### Home Assistant entities

With MQTT, each outlet gets:

- a switch for its output (ON and OFF);
- sensors for power (W), voltage (V), current (A), power factor and energy (Wh).

Entity names use the port label, for example `Port 1 Power`.

## Requirements

Python 3.11 or later. No extra packages.

## Documentation

- [DOCS.md](DOCS.md)
- [CHANGELOG.md](CHANGELOG.md)
- [../docs/PROTOCOL.md](../docs/PROTOCOL.md)

## Security

Keep the mFi devices on an isolated network. Never expose ports 6080, 3478 or
8099 to the internet.

## Credits

- Specification in `docs/PROTOCOL.md`, written from the decompiled mFi Controller
  2.1.11. No vendor code is copied.
- [mcrute/ubntmfi](https://github.com/mcrute/ubntmfi) (BSD-3-Clause), used as a
  reference model. No code is copied.

## License

To be decided.
