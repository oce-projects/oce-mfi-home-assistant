# Compatibility replay fixtures

This folder holds the fixtures of the offline replay bench for the new server
(`mfi_server_next`). Each fixture describes one exchange with a device or with
the controller interface, and the answer the new server must give to it.

## Purpose

The bench replays recorded or synthetic exchanges against the handler that owns
each route, offline, with the standard library only. Every fixture today is
synthetic. The handlers of the OBSERVED routes of the controller-compatible API
(`compat_api.py`, EPIC-17) are implemented, so their fixtures are active; the
fixtures of the UNVERIFIED routes are PENDING.

Real recordings are added later as more `*.json` files in this folder. Adding a
recording needs no code change: the helper `compat_replay.py` and the test
`test_compat_replay.py` read every file in the folder.

## One fixture = one file

Each file is one JSON object for one exchange, with exactly these top-level keys:

| Key | Type | Meaning |
|---|---|---|
| `code` | string | Recording code, one of the values below |
| `source` | string | `synthetic` or `recording` |
| `owner_epic` | string | The epic that implements the handler, for example `EPIC-02` |
| `handler` | string | Dotted name inside `mfi_server_next`, for example `mfi_server_next.inform.handle_inform` |
| `request` | object | The input given to the handler. Its shape depends on `code` |
| `expected` | object | What the handler must answer (see below) |

### Allowed values of `code`

`R-ADOPT`, `R-POWER`, `R-FORGET`, `R-RESET`, `R-UPDATE`, `R-MPORT`, `R-SERIAL`,
`R-MPOWER`, `R-WEB`, `R-DISC`. The meaning of each code is in
`docs/REBUILD-PLAN.md`, section 8. `R-WEB` has no fixture yet. `R-INWALL` is
UNVERIFIED and is not an allowed `code`.

### Allowed values of `source`

- `synthetic`: written by hand from the protocol notes in `docs/PROTOCOL.md`.
- `recording`: anonymised from a real run of the original controller.

### `owner_epic`

Must be an epic known to the bench: `EPIC-00` to `EPIC-19`, or `EPIC-01b`.

### `handler`

A dotted name of at least `module.attribute` inside `mfi_server_next`. The
helper imports the module and reads the attribute. A name that does not exist
is rejected. Only names that start with `mfi_server_next.` are accepted: a
handler in another module (for example `os.system`) is rejected by the
validation, so a fixture cannot import a foreign module.

### `expected`

- `status` (optional): the HTTP status as an integer, for example `200`.
- `keys` (object): maps each expected JSON key name to an expected type name.
  Allowed type names: `str`, `int`, `float`, `bool`, `list`, `dict`, `null`.
- `tlv_order` (optional, only for discovery): a list of TLV type numbers in the
  order they must appear in the reply.
- `values` (optional): a map of key name to the exact value the handler must
  return, for keys whose value is not a per-device value (for example a firmware
  URL or version). Recorded for reference; per-device values stay compared by
  type.

Per-device values (MAC address, key, time) are compared by TYPE, not by value,
because the new server generates its own values. Only the type named in `keys`
is checked.

## PENDING fixtures

A fixture whose handler still raises `NotImplementedError` is PENDING. The
test does not skip it in silence: every PENDING fixture is printed with its
`owner_epic` in the test output, so the list of work still to do is visible.
A fixture becomes active when its owner epic implements the handler.

## Fake values

Synthetic and anonymised fixtures use fake values only:

- MAC addresses without colons, for example `002722000001`. Never write a MAC
  address with colons.
- The only IPv4 address allowed is `192.168.1.20`, the factory default.
- Keys are fake hexadecimal strings.
- Host names are names such as `mfi-server`, never IP addresses.
- No e-mail addresses.

`tests/test_repository.py` scans this README and every fixture for private
data. A file that breaks these rules makes the repository tests fail.
