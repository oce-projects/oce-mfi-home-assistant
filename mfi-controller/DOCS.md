# Ubiquiti mFi Controller - guide

This page appears in the "Documentation" tab of the app in Home Assistant.

## What it does

The app runs the **original Ubiquiti mFi Controller 2.1.11** in a container. The controller talks to mPower power strips, mPort sensor hubs and mFi sensors. Home Assistant talks to the controller through the core `mfi` integration.

```
mFi devices  --6080 inform-->  mFi Controller app  <--6443 API--  Home Assistant "mfi" integration
                                      |
                       /data (MongoDB database, configuration, logs)
```

## Installation

The container is built on the Home Assistant machine: there is no prebuilt image. The first installation downloads about 26.9 MB from Ubiquiti plus the Debian packages of that era, so Home Assistant needs internet access to `dl.ubnt.com`, `archive.debian.org` and Docker Hub.

1. Open **Settings > Apps > App store**.
2. For a local copy: top-right menu, **Check for updates**. The app appears under **Local apps**.
3. Open **Ubiquiti mFi Controller** and press **Install**. Wait until the build ends.
4. Press **Start**.
5. Open `https://HOME-ASSISTANT-IP:6443/`. The certificate is self-signed: the browser asks for confirmation.
6. Follow the controller setup wizard and create the administrator.

### Installing from the local apps folder (without a repository URL)

1. Install and start an app that gives file access: **Samba share** or **Advanced SSH & Web Terminal**.
2. Find the local apps folder. With Samba it is the share `local_apps`. With Advanced SSH & Web Terminal it is `/addons`. Both are the same Supervisor folder (`apps/local`).
3. Copy the whole `mfi-controller` folder there, so that `local_apps/mfi-controller/config.yaml` exists.
4. Continue with step 1 of the installation above.

If the app does not appear: **Settings > System > Logs**, choose **Supervisor** and look for the `config.yaml` validation error.

## Options

| Option | Default | Meaning |
|---|---|---|
| `java_max_memory_mb` | 1,024 | maximum Java heap, 256 to 4,096 MB |

## Connecting the mFi devices

Each device must know the controller address with port **6080**.

1. Open the web portal of the device (factory user and password `ubnt` / `ubnt`).
2. In the **Configuration** tab, field **mFi Controller**, enter `HOME-ASSISTANT-IP:6080`.
3. Enter **User** and **Password** of the controller administrator.
4. Adopt the device in the controller.

A device without a controller looks for `http://mfi:6080/inform` by itself. A DNS name `mfi` pointing to Home Assistant may therefore let devices find it without configuring them one by one. UNVERIFIED with this app: the behavior comes from device logs posted on the Ubiquiti forum.

## Connecting Home Assistant

The `mfi` integration is configured in `configuration.yaml`, not from the UI.

```yaml
sensor:
  - platform: mfi
    host: HOME-ASSISTANT-IP
    port: 6443
    ssl: true
    verify_ssl: false
    username: !secret mfi_username
    password: !secret mfi_password

switch:
  - platform: mfi
    host: HOME-ASSISTANT-IP
    port: 6443
    ssl: true
    verify_ssl: false
    username: !secret mfi_username
    password: !secret mfi_password
```

`verify_ssl: false` is needed because the controller certificate is self-signed.

## Backup and restore

- A Home Assistant backup stops the app, saves `/data` and starts it again (`backup: cold`), so the MongoDB database stays consistent.
- A `.unf` backup of an old controller is loaded from the bottom panel **Admin**, box **Restore**. The controller reloads the database by itself, without restarting the app.
- After a restore the administrators and passwords **of the backup** apply, not the one created in the wizard.
- A settings-only backup (52 KB in the test) restores in about 5 seconds. A backup with the measurement history (263.5 MB in the test) had not finished after 19 minutes and already used 6.9 GB: check the free space of Home Assistant before loading it.
- The **Admin** panel also has **Backup Database**, which downloads a controller `.unf`.

## Known limits

- The **Map** tab needs Adobe Flash Player, which browsers dropped in 2021: the map is not shown. The Data, Events, Rules, Scenes and Energy tabs and the Admin panel are HTML and open (tested with Chromium 140, 0 JavaScript errors, no devices).
- Charts in the Data tab with real devices have not been tested.
- MongoDB 2.4 listens only inside the container, on `127.0.0.1:37017`: it cannot be reached from the network.
- The controller checks for updates at `http://www.ubnt.com/downloads/mfi/updates/`. There are none any more.
- Stopping takes 1.5 to 26 seconds (measured): the app allows up to 120 seconds.
- Space used in `/data` right after the first start: 289 MB.

## Security

The controller is from 2015 and gets no updates: Java 7 and MongoDB 2.4 are out of support. Use the app **only on the local network**, ideally with the devices on an isolated network. Never open ports 6080 and 6443 to the internet.

## Data

| Path in the container | Content |
|---|---|
| `/data/mfi` | configuration `system.properties`, database `db/`, certificate `keystore` |
| `/data/logs` | `server.log` and `mongod.log` |

The controller log also appears in the **Log** tab of the app.
