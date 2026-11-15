# Changelog

## 0.1.0 - 2026-11-15

- First version of the phase 2 add-on.
- Pure Python AES-128 and BSON reader.
- Inform packets: decrypt, compressed payloads, same IV in the response.
- Device store `devices.json` with schema 1.
- Import of keys and ports from `.unf` backups.
- Device states (a device is lost after 120 s without an inform).
- `mfi-output` command queue.
- Wake-up packet builder.
- Measurements with energy counter compensation.
- HTTP inform server.
- Command line: `decode` and `import-backup`.
- Never sends a factory reset.
