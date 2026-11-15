# mFi Server

## Status

In progress. Not yet tested with a real device. No Home Assistant entities yet,
no adoption of new devices, and no wake-up packet is sent yet.

## Install on Home Assistant OS

Copy the `mfi-server` folder into the local apps folder, as for `mfi-controller`:
the `local_apps` share of the Samba app, or `/addons` in the Advanced SSH & Web
Terminal app. Reload the store, then install the app.

## Options

| Option | Meaning |
|---|---|
| `backup_file` | Path of an old controller backup, for example `/share/mfi/backup.unf`. Imported at every start; the import is idempotent. |
| `log_level` | `debug`, `info`, `warning` or `error`. |

## Import the keys from a controller backup

Copy the `.unf` file into `/share/mfi/`, set `backup_file` and restart the app.

Or run, from the folder that contains `mfi_server`:

```
python3 -m mfi_server import-backup FILE --data DIR
```

The command prints only how many devices and ports were imported. The keys end up
in `devices.json` inside the data folder: protect that folder and never publish it.

## Run as a standalone program

```
cd mfi-server
python3 -m mfi_server --data ./data
```

An optional file `data/settings.json` may hold the same keys as the options.

| Variable | Default |
|---|---|
| `MFI_INFORM_PORT` | 6080 |
| `MFI_WAKEUP_PORT` | 3478 |
| `MFI_BIND_ADDRESS` | 0.0.0.0 |
| `MFI_BACKUP_FILE` | empty (not set) |
| `MFI_LOG_LEVEL` | info |

Precedence: variable, then file, then default.

## Decode a captured packet

```
python3 -m mfi_server decode FILE --key-file KEYFILE
```

The key is read from a file. It is never given on the command line.

## Security

- Keep the devices on an isolated network without internet access.
- Never expose 6080/tcp or 3478/udp to the internet.
- Inform packets without encryption are refused with HTTP 400.
- The server never sends a factory reset to a device.
- The add-on runs as root because the Supervisor `/data` volume belongs to root.

## Ports

| Port | Protocol | Use |
|---|---|---|
| 6080 | tcp | Inform: mFi devices report to the server (HTTP) |
| 3478 | udp | Wake-up packets to the devices |
