# Web API and Comet of the mFi Controller 2.1.11 (clean room report)

This is a clean-room report of the web API and of the Comet live updates of the mFi Controller 2.1.11 (`ace.jar`). It is built only from the repository documents `docs/PROTOCOL.md` (PROTO), `docs/controller/INVENTORY.md` (INV) and `mfi-server/DOCS.md` (DOCS), plus the platform facts of `AGENTS.md`. The report contains no code from `ace.jar`, no pseudocode and no decompiler output. Every fact has a status (OBSERVED, INFERRED or UNVERIFIED) and a source. Nothing in this report was verified on a device.

## 1. Routes (path, method, parameters) and what each does

| Route | Method | Parameters | What it does | Status/Source |
|---|---|---|---|---|
| `/api/v1.0/<verb>/<object>` | UNVERIFIED | UNVERIFIED | Path pattern of the controller HTTP API | OBSERVED; INV "Areas" |
| `/api/v1.0/cmd/devmgr` | UNVERIFIED | `cmd`, `mac` | Carries device commands to the device manager, used by `mfi-output` and `kick-serial` | OBSERVED; PROTO "Commands to the device" and "mPort and sensors", section 6 |
| `mfi-output` through `/api/v1.0/cmd/devmgr` | UNVERIFIED | `port`, `val`, `timer`, `sId` | Switches an outlet on (`val` 1) or off (`val` 0) | OBSERVED; PROTO "Commands to the device" |
| `kick-serial` through `/api/v1.0/cmd/devmgr` | UNVERIFIED | `mac` | Serial command of an mPort Serial (M2S) | OBSERVED; PROTO "mPort and sensors", section 6 |
| `/api/v1.0/upd/sensor` | UNVERIFIED | UNVERIFIED | Saves the sensor calibration and rebuilds the device configuration | OBSERVED; PROTO "mPort and sensors", section 4 |
| Route that lists devices and sensors | UNVERIFIED | UNVERIFIED | Lists devices and sensors | UNVERIFIED; INV "Areas" (not read in the repository documents) |
| Route that reads measured values | UNVERIFIED | UNVERIFIED | Reads the values of the sensors | UNVERIFIED; INV "Areas" (not read in the repository documents) |

- UNVERIFIED: the route that lists devices and sensors, its method and its parameters; the repository documents do not name it. Source: INV "Areas".
- UNVERIFIED: the route that reads the measured values, its method and its parameters; the repository documents do not name it. Source: INV "Areas".
- OBSERVED: the output command `mfi-output` is an API command routed to `cmd/devmgr`; it is the only documented way to switch an outlet through the API. Source: PROTO "Commands to the device".

## 2. Login and session

- OBSERVED: a login and session filter exists in the controller (class `AuthFilter`). Source: INV "Users".
- INFERRED: the session and token classes (`Session`, `Token`, `AuthServer`) take part in the login, as their names suggest. Source: INV "Users" (status INFERRED there).
- UNVERIFIED: the login route. Source: INV "Users"; not named in the repository documents.
- UNVERIFIED: the login fields (user name, password or other). Source: INV "Users".
- UNVERIFIED: the name of the session cookie or token. Source: INV "Users".
- UNVERIFIED: the expiry of a session or token. Source: INV "Users".
- UNVERIFIED: whether a token alone gives access without a session. Source: INV "Users".

## 3. Response format (JSON, meta/data, error codes)

- UNVERIFIED: whether the responses use a `meta` and `data` envelope. Source: not in the repository documents (INV "Areas" names no response format).
- UNVERIFIED: the value that marks a successful response. Source: not in the repository documents.
- UNVERIFIED: the error codes and their names. Source: not in the repository documents.
- UNVERIFIED: the content type of the responses. Source: not in the repository documents.
- INFERRED: `ace.jar` is built on the UniFi code base (AGENTS "Facts"), so a `meta` and `data` envelope similar to UniFi is plausible; this is not confirmed. Source: AGENTS.md "Facts you can rely on".

## 4. Comet: live updates

- OBSERVED: Comet delivers live updates with long-poll messages. Source: INV "Areas" (Web API row).
- OBSERVED: the MongoDB collection `cometmessage` holds the messages and is capped at 1,000,000 bytes. Source: INV "Areas" (Web API row).
- OBSERVED: the Comet classes are named `CometServlet` and `CometMessage`. Source: INV "Areas" (Web API row).
- UNVERIFIED: the names of the published events. Source: not in the repository documents.
- UNVERIFIED: the exact JSON of a Comet message. Source: not in the repository documents.
- UNVERIFIED: the route of the Comet servlet, its parameters and the long-poll timeout. Source: not in the repository documents.
- UNVERIFIED: whether Comet messages carry device measurements. Source: not in the repository documents.

## 5. Ports and protocols (6080 HTTP, 6443 HTTPS) and which routes on which port

- OBSERVED: port 6080 is the inform port, HTTP, served by `InformServlet`; the default is set by the property `unifi.http.port`. Source: PROTO "Transport".
- OBSERVED: port 6443 is the web UI over HTTPS since controller 1.1.0; ports 9080 and 9443 were used up to 1.0.8. Source: AGENTS.md "Facts you can rely on" (official Ubiquiti FAQ, 2013).
- OBSERVED: the ports are configurable in `<mFi>/data/system.properties`. Source: AGENTS.md "Facts you can rely on".
- OBSERVED: `/inform` is on port 6080. Source: PROTO "Transport".
- INFERRED: the `/api/v1.0` routes and Comet are on the web UI service, port 6443 over HTTPS. Source: AGENTS.md "Facts you can rely on"; INV "Areas".
- UNVERIFIED: whether the `/api/v1.0` routes are also served on port 6080. Source: not in the repository documents.
- OBSERVED: AGENTS.md rule 8 forbids exposing ports 6080 and 6443 to the internet. Source: AGENTS.md, hard rule 8.

## Gaps in mfi-server

The mfi-server code was not read for this report; the comparison is with DOCS, PROTO, INV and AGENTS.md only. Reading the `mficlient` library was out of scope (no network).

- OBSERVED: mfi-server serves its JSON API on port 8099 under the `api/v1/` path. The controller serves its API on 6443 under `/api/v1.0`. Source: DOCS "Web API"; AGENTS.md "Facts you can rely on".
- OBSERVED: the documented mfi-server routes are `api/v1/login`, `api/v1/logout`, `api/v1/devices`, `api/v1/devices/<mac>/ports/<port>/output`, `api/v1/history` and `api/v1/discovery`, plus others. Source: DOCS "Web API".
- OBSERVED: mfi-server has no route that matches the controller `/api/v1.0/<verb>/<object>` pattern. Source: DOCS "Web API" (route table).
- OBSERVED: in add-on mode the mfi-server API is reached only through the Home Assistant ingress, from the peer address 172.30.32.2 by default; there is no login in add-on mode. Source: DOCS "Web API" and "Options".
- OBSERVED: in standalone mode the mfi-server login uses a password set with `set-password` and a session cookie `mfi_session`. Source: DOCS "Web API".
- INFERRED: the standalone password is stored as a salted PBKDF2 hash. Source: ARCHITECTURE.md "Decisions" (2026-11-15).
- OBSERVED: mfi-server has no Comet or long-poll route in its web API table. Source: DOCS "Web API".
- INFERRED: mfi-server does not push live updates through its web API; Home Assistant entities arrive through MQTT discovery. Source: DOCS "MQTT and Home Assistant" and "Web API".
- OBSERVED: the mfi-server JSON responses are documented as top-level keys (for example `devices`, `points`, `backup`, `result`) with no `meta` and `data` envelope. Source: DOCS "Web API".
- OBSERVED: mfi-server documents its own error keys (for example `not_found`, `invalid_input`, `password_not_set`), which are not the controller error codes. Source: DOCS "Web API" and "Adopting and re-pointing devices".
- INFERRED: the Home Assistant core `mfi` integration (library `mficlient`), which talks to the controller API, does not work against mfi-server, because mfi-server does not implement the `/api/v1.0` routes. Source: AGENTS.md "Facts you can rely on" (core integration); DOCS "Web API".
- UNVERIFIED: the behaviour of `mficlient` on a server that answers the mfi-server routes. Source: not read (out of scope, no network).
