# Ubiquiti mFi Controller (original)

> **Legacy add-on.** This runs the original Ubiquiti mFi software from 2015, unchanged and with no security updates. Keep it on an isolated network and never expose ports 6080/6443 to the internet. For normal use install **mFi Server (new)** instead; this add-on is kept only for comparison and to capture device traffic. In the administrator setup wizard the password field accepts letters only, a limitation of the 2015 Ubiquiti software, not of this add-on.

History in `CHANGELOG.md`. Usage guide in `DOCS.md`.

This app (add-on) runs the **original Ubiquiti mFi Controller 2.1.11** in a container on Home Assistant OS. It serves mPower power strips, mPort sensor hubs and mFi sensors, a product line discontinued in 2015.

Home Assistant talks to the controller through the `mfi` integration, which is still in Home Assistant core (library `mficlient` 0.5.0, YAML configuration only).

- **Architecture:** `amd64` only.
- **Ports:** 6080 (inform, used by the devices) and 6443 (web UI and API, HTTPS). With `record_traffic` on, the recorder also listens passively on UDP 10001 (discovery) and 3478 (wake-up); it never answers or sends packets.
- **Network:** the add-on uses the host network (`host_network: true`). Do not run it together with mFi Server, because both use port 6080. Keep the devices on an isolated network. With host networking the internal controller ports 16080 and 16443 may also be reachable from the LAN, bypassing the recorder (UNVERIFIED).
- **License:** the Ubiquiti software is not in this repository. The `Dockerfile` downloads it from `dl.ubnt.com` at build time and checks the sha256.
- **Status:** experimental. Built and tested with Docker on an amd64 Linux host; **not yet installed on Home Assistant OS**. The software is from 2015 and gets no security updates: keep it on the local network, never expose it to the internet.








