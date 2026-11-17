# Contributing

Read [AGENTS.md](AGENTS.md) first: it holds the full rules for this repository. Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) before changing the structure, and [docs/PROTOCOL.md](docs/PROTOCOL.md) before touching anything that talks to devices.

## Running the tests

The tests run offline and use the Python standard library only. Run these commands from the repository root. All must exit with status 0.

```
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s mfi-server/tests -t mfi-server -v
python3 -m unittest discover -s mfi-wifi-setup/tests -t mfi-wifi-setup -v
```

## Rules in short

- No Ubiquiti files: no `.jar`, `.zip`, `.deb`, `.bin`, `.unf`, firmware or controller binaries. Add-ons download the controller at build time and check its sha256.
- No private data: no passwords, `authkey` values, SSH keys, real MAC addresses, home IP addresses, host names or local paths. Controller backups never enter the repository.
- Version and changelog on every change: raise the version (`VERSION` for the repository, `version` in `<addon>/config.yaml` for an add-on) and add a changelog entry in the same commit. Use semantic versioning: fix = patch, feature = minor.
- `mfi-server` uses the Python standard library only.
- Tests run offline: no network, no Docker, no device, no Home Assistant.
- Do not weaken a test to make it pass. If a test is wrong, fix it in its own commit and explain why in the changelog.
- All files in this repository are in English.
- Every number in the docs (sizes, ports, versions) comes from a file, a command output or a cited source. Mark anything unverified as `UNVERIFIED`.
