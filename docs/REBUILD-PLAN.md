# Rebuild plan: mfi-server feature parity with the mFi Controller 2.1.11

This plan covers a full rewrite of mfi-server to reach feature parity with the mFi Controller 2.1.11, in Home Assistant style, for the whole repository (mfi-server, mfi-controller, mfi-wifi-setup, docs and tests). The decision is recorded as RAG doc 12, dated 2026-11-18. That document is not in this repository, so this plan cites the decision and does not restate it. The plan is built only from the clean-room reports in `docs/controller/` and the repository documents listed in the ticket. It copies no code or pseudocode from `ace.jar` and contains no device or site data. Every fact keeps the OBSERVED, INFERRED or UNVERIFIED label of its source. "Equal to mfi" means the same device-facing functions and behaviour, not the same graphics.

## Feature parity table

Each row names one controller function, the clean-room document it comes from, the label copied from that document, and the epic that delivers it. Epic names are defined in section 6. Rows marked "only if approved" wait for the owner decision in section 3.

| Area | Function | Source doc | Label | Target epic |
|---|---|---|---|---|
| Inform and devices | Adoption from the UI (adopt command, SSH set-adopt on port 22) | docs/controller/device-lifecycle.md (section 1) | OBSERVED | EPIC-02 Inform and devices |
| Inform and devices | Credentials used for UI adoption (administrator or factory) | docs/controller/device-lifecycle.md (section 1) | UNVERIFIED, needs device test | EPIC-02 Inform and devices |
| Inform and devices | Decryption key order for a device that has a previous key | docs/controller/device-lifecycle.md (section 1) | UNVERIFIED, needs device test | EPIC-02 Inform and devices |
| Inform and devices | Device-side handling of a manual set-inform | docs/controller/device-lifecycle.md (section 1) | UNVERIFIED, needs device test | EPIC-02 Inform and devices |
| Inform and devices | Automatic re-adoption of an adopted device that informs with the default flag | docs/controller/device-lifecycle.md (section 2) | OBSERVED | EPIC-02 Inform and devices |
| Inform and devices | Inform URL pushed to a device with setparam (mgmt_cfg) | docs/controller/device-lifecycle.md (section 2) | OBSERVED | EPIC-02 Inform and devices |
| Inform and devices | Condition under which a changed inform URL is pushed to an adopted device | docs/controller/device-lifecycle.md (section 2) | UNVERIFIED, needs device test | EPIC-02 Inform and devices |
| Inform and devices | Forget a connected device: queued setdefault task, state 8 | docs/controller/device-lifecycle.md (section 3) | OBSERVED | EPIC-02 Inform and devices |
| Inform and devices | Forget removes device, alarm, event, token, task and ap statistics | docs/controller/device-lifecycle.md (section 3) | OBSERVED | EPIC-02 Inform and devices |
| Inform and devices | Forget also removes m2mgeneric, rollups and rule references (needs device test) | docs/controller/device-lifecycle.md (section 3) | UNVERIFIED, needs device test | EPIC-02 Inform and devices |
| Inform and devices | Factory reset commanded by the controller (setdefault message, no confirmation) | docs/controller/device-lifecycle.md (section 4) | OBSERVED | EPIC-02 Inform and devices |
| Inform and devices | Device-side result of setdefault (saved authkey cleared, factory key used) | docs/controller/device-lifecycle.md (section 4) | INFERRED | EPIC-02 Inform and devices |
| Inform and devices | Reboot command (queued reboot task, record reloaded in state 0) | docs/controller/device-lifecycle.md (section 6) | OBSERVED | EPIC-02 Inform and devices |
| Inform and devices | Locate command on a connected device | docs/controller/device-lifecycle.md (section 6) | OBSERVED | EPIC-02 Inform and devices |
| Inform and devices | Locate on a device in state 2 (discovery call with value 30, needs device test) | docs/controller/device-lifecycle.md (section 6) | UNVERIFIED, needs device test | EPIC-02 Inform and devices |
| Inform and devices | Reply to a device without work: noop with a 10 s interval | docs/PROTOCOL.md (Controller responses) | OBSERVED | EPIC-02 Inform and devices |
| Inform and devices | Heartbeat missed after 40 s (state 6), needs device test | docs/controller/device-lifecycle.md (section 6) | UNVERIFIED, needs device test | EPIC-02 Inform and devices |
| Inform and devices | Lost contact after 120 s in state 1 or 6: event, record reload, disconnected notice | docs/controller/device-lifecycle.md (section 6) | OBSERVED | EPIC-02 Inform and devices |
| Inform and devices | Unadopted device removed from memory after 120 s silent; state 2 after 60 s silent | docs/controller/device-lifecycle.md (section 6) | OBSERVED | EPIC-02 Inform and devices |
| Inform and devices | Command queue: task sent in the reply to the next inform, only if connected; newer task for the same port replaces the old one | docs/PROTOCOL.md (Commands to the device) | OBSERVED | EPIC-02 Inform and devices |
| Inform and devices | Firmware upgrade message with the bundles.json entry; state 4 for 180 s | docs/controller/firmware.md (sections 2 and 4) | OBSERVED | EPIC-02 Inform and devices |
| Inform and devices | Upgrade comparison rule ("differs" or "not older"), needs device test | docs/controller/firmware.md (section 1) | UNVERIFIED, needs device test | EPIC-02 Inform and devices |
| Inform and devices | Upgrade integrity check and retry behaviour, needs device test | docs/controller/firmware.md (sections 2 and 4) | UNVERIFIED, needs device test | EPIC-02 Inform and devices |
| Inform and devices | Auto-upgrade flag and any bulk upgrade, needs device test | docs/controller/firmware.md (section 5) | UNVERIFIED, needs device test | EPIC-02 Inform and devices |
| Inform and devices | Restored device comes back in state 0 with ports showing NONE | docs/controller/device-lifecycle.md (section 5) | OBSERVED | EPIC-02 Inform and devices |
| Inform and devices | Restored device returns to state 1 at its next inform with the stored key | docs/controller/device-lifecycle.md (sections 1 and 5) | INFERRED | EPIC-02 Inform and devices |
| Discovery | UDP discovery on port 10001 with TLV announcements and replies, needs device test | docs/PROTOCOL.md (Discovery), docs/controller/network-tools.md | UNVERIFIED, needs device test | EPIC-03 Discovery |
| Discovery | TLV type 3 (version string) and type 22 (firmware version) in the discovery reply | docs/controller/firmware.md (section 1); docs/PROTOCOL.md (Discovery) | OBSERVED | EPIC-03 Discovery |
| Discovery | Discovery reply of an mPower mini without type 22; firmware derived from type 3 (other models: needs device test) | docs/controller/firmware.md (section 1) | OBSERVED | EPIC-03 Discovery |
| Discovery | Devices managed by another controller are ignored (default flag false) | docs/controller/device-lifecycle.md (section 1) | OBSERVED | EPIC-03 Discovery |
| Discovery | New device found: pending record in memory, event EVT_AP_DiscoveredPending | docs/controller/alarms.md (section 1) | OBSERVED | EPIC-03 Discovery |
| Sensors and mPort | Sensor model table: MSW, MSC, CS, DS, THS, Counter, Input Digital, Input Analog, RTD, Output 5v, Output 12v, Output 24v, UVC PRO, Serial | docs/controller/mport.md (section 1) | OBSERVED | EPIC-04 Sensors and mPort |
| Sensors and mPort | Spelling "Output  5v" with two spaces versus "Output 5v" (needs device test) | docs/controller/mport.md (section 1) | UNVERIFIED, needs device test | EPIC-04 Sensors and mPort |
| Sensors and mPort | Assign a sensor type to a port; a sensor already on that port is unlinked | docs/controller/mport.md (section 2) | OBSERVED | EPIC-04 Sensors and mPort |
| Sensors and mPort | Port configuration lines of an mPort (port, AI, DI, DO) | docs/controller/mport.md (section 2); docs/PROTOCOL.md (mPort and sensors) | OBSERVED | EPIC-04 Sensors and mPort |
| Sensors and mPort | Sensor removal in a background thread: alarms, events, labels, readings, then the record | docs/controller/mport.md (section 2) | OBSERVED | EPIC-04 Sensors and mPort |
| Sensors and mPort | Per-sensor calibration string, default identity; changing it sends the configuration again | docs/controller/mport.md (section 3) | OBSERVED | EPIC-04 Sensors and mPort |
| Sensors and mPort | CustomSensors merged from dl/custom.json into the customSensors setting; built-in name takes precedence | docs/controller/mport.md (section 3) | OBSERVED | EPIC-04 Sensors and mPort |
| Sensors and mPort | Keys of a custom sensor definition and whether it reaches the device (needs device test) | docs/controller/mport.md (section 3) | UNVERIFIED, needs device test | EPIC-04 Sensors and mPort |
| Sensors and mPort | Output command (mfi-output) on an mPort output port; port mapping (needs device test) | docs/controller/mport.md (section 4) | UNVERIFIED, needs device test | EPIC-04 Sensors and mPort |
| Sensors and mPort | Output with output_lock 1 does not receive the output command | docs/controller/mport.md (section 4) | OBSERVED | EPIC-04 Sensors and mPort |
| Sensors and mPort | Output power-on state after power loss (model text says last state, needs device test) | docs/controller/mport.md (section 4) | UNVERIFIED, needs device test | EPIC-04 Sensors and mPort |
| Sensors and mPort | Serial settings sent as ser2net_cfg (enable, baudRate, parity, uartMode, termination, antenna) | docs/controller/mport-serial.md (section 1) | OBSERVED | EPIC-04 Sensors and mPort |
| Sensors and mPort | Serial flow control, data bits and stop bits effect (needs device test) | docs/controller/mport-serial.md (section 1) | UNVERIFIED, needs device test | EPIC-04 Sensors and mPort |
| Sensors and mPort | kick-serial command and event EVT_mFi_SerialKick (device effect needs device test) | docs/controller/mport-serial.md (section 3) | OBSERVED | EPIC-04 Sensors and mPort |
| Sensors and mPort | Serial data channel (TCP port and who opens it, needs device test) | docs/controller/mport-serial.md (section 2) | UNVERIFIED, needs device test | EPIC-04 Sensors and mPort |
| Sensors and mPort | Measurements of an mPort M2S beyond the Serial sensor (needs device test) | docs/controller/mport-serial.md (section 4) | UNVERIFIED, needs device test | EPIC-04 Sensors and mPort |
| Sensors and mPort | mPower outlet on/off with mfi-output (val 1 on, 0 off, timer in seconds) | docs/controller/mpower.md (section 2) | OBSERVED | EPIC-04 Sensors and mPort |
| Sensors and mPort | mPower outlet measures: output, pf, energy_sum, v_rms, i_rms, active_pwr | docs/controller/mpower.md (section 4) | OBSERVED | EPIC-04 Sensors and mPort |
| Sensors and mPort | Outlet energy counter base kept by the controller across counter resets | docs/controller/mpower.md (section 4) | OBSERVED | EPIC-04 Sensors and mPort |
| Sensors and mPort | Manual energy counter reset for outlets (needs device test) | docs/controller/mpower.md (section 4) | UNVERIFIED, needs device test | EPIC-04 Sensors and mPort |
| Sensors and mPort | Outlet lock (output_lock sent as lock in port_cfg) | docs/controller/mpower.md (section 3) | OBSERVED | EPIC-04 Sensors and mPort |
| Sensors and mPort | Outlet power-on state from configed_val, then output_val | docs/controller/mpower.md (section 3) | INFERRED | EPIC-04 Sensors and mPort |
| Sensors and mPort | Outlet timer field meaning (delay, pulse or cycle, needs device test) | docs/controller/mpower.md (section 2) | UNVERIFIED, needs device test | EPIC-04 Sensors and mPort |
| Sensors and mPort | Cycle command (off then on in one step, needs device test) | docs/controller/mpower.md (section 2) | UNVERIFIED, needs device test | EPIC-04 Sensors and mPort |
| Sensors and mPort | Model codes P1U, P1E, P3U, P3E, P6E, P8U and their outlet counts | docs/controller/mpower.md (section 1) | OBSERVED | EPIC-04 Sensors and mPort |
| Sensors and mPort | Power measurement of P1U, P3U and P8U (needs device test) | docs/controller/mpower.md (section 1) | UNVERIFIED, needs device test | EPIC-04 Sensors and mPort |
| Sensors and mPort | In-wall outlet IWO2U: two outlets, measures and mfi-output | docs/controller/in-wall.md (section 1) | OBSERVED | EPIC-04 Sensors and mPort |
| Sensors and mPort | In-wall dimmer IWD1U: dimmer_mode, dimmer_lock_setting, dimmer_level in mfi-output | docs/controller/in-wall.md (sections 2 and 3) | OBSERVED | EPIC-04 Sensors and mPort |
| Sensors and mPort | Dimmer level scale, step, ramp unit, minimum and maximum (needs device test) | docs/controller/in-wall.md (sections 2 and 3) | UNVERIFIED, needs device test | EPIC-04 Sensors and mPort |
| Sensors and mPort | In-wall switch IWS1U functions and physical button event (needs device test) | docs/controller/in-wall.md (section 4) | UNVERIFIED, needs device test | EPIC-04 Sensors and mPort |
| Sensors and mPort | LED settings and effect of locate on P models (needs device test) | docs/controller/mpower.md (section 5) | UNVERIFIED, needs device test | EPIC-04 Sensors and mPort |
| Sensors and mPort | Sensor and port API: list sensors, add to port, move, edit fields, label | docs/controller/mport.md (section 6) | OBSERVED | EPIC-04 Sensors and mPort |
| Rules and scenes | Ruleset conditions on a sensor: compare, limit, duration in minutes, all or any, edge or level | docs/PROTOCOL.md (Rules and scenes) | OBSERVED | EPIC-05 Rules and scenes |
| Rules and scenes | Rule actions: email, event, relaySwitch, script, state, url, scene, rule | docs/PROTOCOL.md (Rules and scenes) | OBSERVED | EPIC-05 Rules and scenes |
| Rules and scenes | Rule queue limit of 30 requests | docs/controller/mport.md (section 5) | OBSERVED | EPIC-05 Rules and scenes |
| Rules and scenes | Sensor threshold implemented as a ruleset, not as an alarm definition | docs/controller/alarms.md (section 5) | OBSERVED | EPIC-05 Rules and scenes |
| Rules and scenes | Time rules with weekly intervals in the server time zone and calendars | docs/PROTOCOL.md (Rules and scenes) | OBSERVED | EPIC-05 Rules and scenes |
| Rules and scenes | Scenes group relaySwitch, script and url actions and raise EVT_mFi_Action | docs/PROTOCOL.md (Rules and scenes, Events) | OBSERVED | EPIC-05 Rules and scenes |
| Rules and scenes | Script action run on a device over telnet (security question, see section 8) | docs/controller/INVENTORY.md (Classes, class_27) | OBSERVED | EPIC-05 Rules and scenes |
| Rules and scenes | relaySwitch action skips a port whose output_lock is 1 and records an error | docs/controller/in-wall.md (section 4) | OBSERVED | EPIC-05 Rules and scenes |
| Rules and scenes | URL action: POST with rule, sensor and value fields to the addr list | docs/PROTOCOL.md (Rules and scenes) | OBSERVED | EPIC-05 Rules and scenes |
| Events | Save device events to the event collection with key and message | docs/PROTOCOL.md (Events) | OBSERVED | EPIC-06 Events |
| Events | Save rule and scene actions to the actionevent collection | docs/PROTOCOL.md (Events) | OBSERVED | EPIC-06 Events |
| Events | Event message text from the messages resource, with curly-bracket substitution | docs/controller/alarms.md (section 3) | OBSERVED | EPIC-06 Events |
| Events | Text of the messages resource (not readable, needs device test) | docs/controller/alarms.md (section 3) | UNVERIFIED, needs device test | EPIC-06 Events |
| Events | E-mail notification: email action, addr list, minute throttle, last_time | docs/controller/alarms.md (section 3) | OBSERVED | EPIC-06 Events |
| Events | Mail-server settings (SMTP host, port, authentication, sender; needs device test) | docs/controller/alarms.md (section 3) | UNVERIFIED, needs device test | EPIC-06 Events |
| Events | Event and actionevent retention through ttl_time indexes (needs device test) | docs/controller/alarms.md (section 4) | UNVERIFIED, needs device test | EPIC-06 Events |
| Statistics | Aggregates per minute, quarter hour, hour and day: max, min, ave, size, last_val | docs/PROTOCOL.md (Statistics) | OBSERVED | EPIC-07 Statistics |
| Statistics | Read interval chooses the aggregate; intervals capped at 3 years | docs/controller/mpower.md (section 6) | OBSERVED | EPIC-07 Statistics |
| Statistics | Raw measurements in m2mgeneric; collection name case needs check | docs/controller/system.md (section 3) | UNVERIFIED, needs device test | EPIC-07 Statistics |
| Statistics | Pattern stat.type.period for Wi-Fi, user and device statistics | docs/controller/system.md (section 3) | OBSERVED | EPIC-07 Statistics |
| Statistics | Type and period values of stat collections (needs device test) | docs/controller/system.md (section 3) | UNVERIFIED, needs device test | EPIC-07 Statistics |
| Statistics | storage.ttl_time default 13 and its unit (needs device test) | docs/controller/system.md (section 4) | UNVERIFIED, needs device test | EPIC-07 Statistics |
| Statistics | Deletion job of documents without ttl_time (needs device test) | docs/controller/system.md (section 3) | UNVERIFIED, needs device test | EPIC-07 Statistics |
| Alarms | Startup alarm definitions: DiscoveredPending, RediscoveredPending, Lost_Contact, WU and WG AssocPending, AD_UpdateAvailable | docs/controller/alarms.md (section 1) | OBSERVED | EPIC-08 Alarms |
| Alarms | Lost contact alarm raised after 120 s without inform, with repeat | docs/controller/alarms.md (sections 1 and 2) | OBSERVED | EPIC-08 Alarms |
| Alarms | Trigger of EVT_AD_UpdateAvailable (needs device test) | docs/controller/alarms.md (section 1) | UNVERIFIED, needs device test | EPIC-08 Alarms |
| Alarms | Monitor timers: 40 s and 60 s check, 120 s lost contact | docs/controller/alarms.md (section 2) | OBSERVED | EPIC-08 Alarms |
| Alarms | Monitor class fields and link to the contact check (needs device test) | docs/controller/alarms.md (section 2) | INFERRED | EPIC-08 Alarms |
| Alarms | Alarm record fields archived, occurs and handled_* | docs/controller/alarms.md (section 4) | OBSERVED | EPIC-08 Alarms |
| Alarms | Meaning of archived, occurs and handled_* (needs device test) | docs/controller/alarms.md (section 4) | INFERRED | EPIC-08 Alarms |
| Alarms | Acknowledge, archive and delete routes for alarms (needs device test) | docs/controller/alarms.md (section 4) | UNVERIFIED, needs device test | EPIC-08 Alarms |
| Alarms | Alarm retention and removal job (needs device test) | docs/controller/alarms.md (section 4) | UNVERIFIED, needs device test | EPIC-08 Alarms |
| Users | Administrator account used for automatic re-adoption | docs/controller/users.md (section 1) | OBSERVED | EPIC-09 Users |
| Users | Groups, per-account permissions and access to devices or locations (needs device test) | docs/controller/users.md (section 1) | UNVERIFIED, needs device test | EPIC-09 Users |
| Users | Login filter that protects the web routes (AuthFilter) | docs/controller/users.md (section 2) | OBSERVED | EPIC-09 Users |
| Users | Session, token and AuthServer roles in login (needs device test) | docs/controller/users.md (sections 2 and 4) | INFERRED | EPIC-09 Users |
| Users | Login route, session cookie and token expiry of the controller (needs device test) | docs/controller/users.md (section 2) | UNVERIFIED, needs device test | EPIC-09 Users |
| Users | Lockout after failed attempts on the controller (needs device test) | docs/controller/users.md (section 2) | UNVERIFIED, needs device test | EPIC-09 Users |
| Users | External authentication such as RADIUS or LDAP (needs device test) | docs/controller/users.md (section 4) | UNVERIFIED, needs device test | EPIC-09 Users |
| Users | Token created per device at adoption and removed at forget | docs/controller/users.md (section 3) | OBSERVED | EPIC-09 Users |
| Users | Standalone login: POST api/v1/login, session cookie, 401 and 429 limits | docs/controller/users.md (gaps section, from mfi-server/DOCS.md) | OBSERVED | EPIC-09 Users |
| Web API | Route family /api/v1.0/verb/object on the HTTPS port (port INFERRED) | docs/controller/web-api.md | INFERRED | EPIC-11 Web API |
| Web API | cmd/devmgr for mfi-output and kick-serial | docs/controller/web-api.md; docs/PROTOCOL.md (Commands to the device) | OBSERVED | EPIC-11 Web API |
| Web API | upd/sensor for sensor updates | docs/controller/web-api.md | OBSERVED | EPIC-11 Web API |
| Web API | Comet long-poll live updates backed by the cometmessage capped collection | docs/controller/web-api.md | OBSERVED | EPIC-11 Web API |
| Web API | Comet route name and message format (needs device test) | docs/controller/web-api.md | UNVERIFIED, needs device test | EPIC-11 Web API |
| Web API | Statistics, rule, event and alarm routes (names needs device test) | docs/controller/web-api.md | UNVERIFIED, needs device test | EPIC-11 Web API |
| Maps and dashboard | Location class and location collection (fields needs device test) | docs/controller/ui.md (section 1) | INFERRED | EPIC-12 Maps and dashboard |
| Maps and dashboard | Geofence class with markers and label (fields needs device test) | docs/controller/ui.md (section 2) | INFERRED | EPIC-12 Maps and dashboard |
| Maps and dashboard | Geofence entries per device, at most 11 (needs device test) | docs/controller/ui.md (section 2) | UNVERIFIED, needs device test | EPIC-12 Maps and dashboard |
| Maps and dashboard | LiveView and Widget classes (widget types needs device test) | docs/controller/ui.md (section 3) | INFERRED | EPIC-12 Maps and dashboard |
| Maps and dashboard | Template and ConfigTemplate classes (application to devices needs device test) | docs/controller/ui.md (section 4) | INFERRED | EPIC-12 Maps and dashboard |
| Maps and dashboard | Maps stay in the controller and are not sent to devices | docs/PROTOCOL.md (Device configuration) | OBSERVED | EPIC-12 Maps and dashboard |
| Maps and dashboard | Map upload form and map image route (needs device test) | docs/controller/system.md (section 5) | UNVERIFIED, needs device test | EPIC-12 Maps and dashboard |
| System | Backup file format: ZIP with db.gz, format, timestamp and version | docs/PROTOCOL.md (Controller backups) | OBSERVED | EPIC-10 System |
| System | Backup restore check of the version and timestamp entries | docs/controller/device-lifecycle.md (section 5); docs/controller/system.md (section 2) | OBSERVED | EPIC-10 System |
| System | Restore body: whole database dropped before reading the file (needs device test) | docs/controller/system.md (section 2) | UNVERIFIED, needs device test | EPIC-10 System |
| System | Excluded collections in a backup (cometmessage, system indexes, profile; statistics without a full backup) | docs/controller/device-lifecycle.md (section 5) | OBSERVED | EPIC-10 System |
| System | Database migration on version change (DbMigrator class exists; steps need device test) | docs/controller/system.md (section 3) | UNVERIFIED, needs device test | EPIC-10 System |
| System | Default settings written at first start (needs device test) | docs/controller/system.md (section 4) | UNVERIFIED, needs device test | EPIC-10 System |
| System | outputTimer default 0 and timezone setting with default PST | docs/PROTOCOL.md (Device configuration); docs/PROTOCOL.md (Rules and scenes) | OBSERVED | EPIC-10 System |
| System | Launcher and Java 7 runtime (not carried over; replaced by the standalone program) | docs/controller/system.md (section 6); AGENTS.md (facts) | OBSERVED | EPIC-10 System |
| System | Update check that contacts a vendor address (needs device test) | docs/controller/system.md (section 6) | UNVERIFIED, needs device test | EPIC-10 System |
| System | Status servlet response fields (needs device test) | docs/controller/system.md (section 5) | UNVERIFIED, needs device test | EPIC-10 System |
| Network and Wi-Fi | SSH from the controller web interface (SshServlet), only if approved | docs/controller/network-tools.md (section 1) | INFERRED | EPIC-13 Network and Wi-Fi (only if approved) |
| Network and Wi-Fi | Web shell (WebshellServlet and input), only if approved | docs/controller/network-tools.md (section 1) | INFERRED | EPIC-13 Network and Wi-Fi (only if approved) |
| Network and Wi-Fi | UPnP service announcements (UpnpServlet), needs device test | docs/controller/network-tools.md (section 2) | UNVERIFIED, needs device test | EPIC-13 Network and Wi-Fi (only if approved) |
| Network and Wi-Fi | Guest access page (GuestServlet), needs device test | docs/controller/network-tools.md (section 3) | UNVERIFIED, needs device test | EPIC-13 Network and Wi-Fi (only if approved) |
| Network and Wi-Fi | Wi-Fi setup form: essid, security, WEP and WPA fields, no channel field | docs/PROTOCOL.md (Wi-Fi setup mode); docs/WIFI-SETUP.md | OBSERVED | EPIC-13 Network and Wi-Fi |
| Network and Wi-Fi | WLAN settings change the configuration version and are sent with setparam | docs/PROTOCOL.md (Device configuration); docs/controller/network-tools.md (section 4) | OBSERVED | EPIC-13 Network and Wi-Fi |
| Network and Wi-Fi | Wi-Fi block format sent to devices and the vap_table conflict (needs device test) | docs/controller/network-tools.md (section 4) | UNVERIFIED, needs device test | EPIC-13 Network and Wi-Fi |

## Architecture

The new server is one standard-library Python package in `mfi-server/mfi_server/`, run as a Home Assistant add-on and as a standalone program (ARCHITECTURE decisions, 2026-11-15). The module names below are proposals. The current module names are not listed in the documents read for this plan, so EPIC-00 checks them against `mfi-server/DOCS.md` and keeps the existing names where they fit (UNVERIFIED until that check).

### Server modules

| File under mfi-server/mfi_server/ | Responsibility | Public interface (proposed names) |
|---|---|---|
| `__init__.py` | Package version | `__version__` |
| `config.py` | Settings from environment, then settings.json, then defaults | `load_settings(data_dir)` |
| `store.py` | sqlite3 and JSON persistence, temp file then rename, transactions | `Store.open()`, `Store.transaction()` |
| `crypto.py` | Own AES-128 for the inform payload; PBKDF2 hash for passwords | `aes128_decrypt()`, `pbkdf2_hash()`, `pbkdf2_verify()` |
| `bson.py` | BSON reader for controller backups | `read_bson_stream(fileobj)` |
| `inform.py` | Inform handling and the reply (noop, setparam, upgrade, cmd) | `handle_inform(payload, registry)` |
| `devices.py` | Device records, state machine, adoption, forget, factory reset | `DeviceRegistry` |
| `tasks.py` | Command queue delivered on the next inform | `TaskQueue.enqueue()`, `TaskQueue.pop_for_mac()` |
| `firmware.py` | Firmware table per model and upgrade message | `firmware_for_model(model)` |
| `discovery.py` | UDP discovery on port 10001 (needs device test) | `DiscoveryServer` |
| `sensors.py` | Sensor models, port configuration, outlets, calibration, custom sensors | `build_port_config()`, `SensorRegistry` |
| `serial.py` | mPort Serial settings and kick-serial | `build_ser2net_cfg()`, `kick_serial()` |
| `rules.py` | Rulesets, rule actions, scenes, time rules | `RuleEngine.evaluate()` |
| `events.py` | Events and their message text | `EventLog.record()` |
| `alarms.py` | Alarm definitions and alarm lifecycle | `AlarmStore.raise_alarm()` |
| `stats.py` | Aggregates per minute, quarter hour, hour and day | `Aggregator.add()`, `Aggregator.read()` |
| `auth.py` | Users, sessions and login with PBKDF2 hashes | `login()`, `check_session()` |
| `web.py` | HTTP API and the web page | `make_handler()` |
| `comet.py` | Live update buffer for the long poll | `CometBuffer` |
| `maps.py` | Maps, locations, geofences, dashboards (if approved) | `MapStore` |
| `mqtt.py` | MQTT discovery and state messages for Home Assistant | `discovery_messages()`, `state_messages()` |
| `migrate.py` | Data migration and backup import | `migrate_all(data_dir)`, `import_backup(path)` |

### Data model

The controller stores its data in MongoDB collections. The new server uses sqlite3 tables or JSON files from the standard library. The stores are proposals; the collection names come from `docs/controller/system.md` (section 3) and `docs/controller/INVENTORY.md`.

| Controller collection | Proposed store | Notes |
|---|---|---|
| device | `devices.json` in the data folder (existing) | Written by temp file then rename |
| task | `state.sqlite3`, table `task` (new) | Queue needs transactional updates |
| sensor | `state.sqlite3`, table `sensor` (new) | Port links and calibration |
| rule, ruleset, ruleaction, rulestate, rulestatecalendar, ruleschedule, rulecondition | `automations.json` (existing automations file) | Home Assistant format; state fields kept in the same file |
| scene, sceneaction, script | `automations.json` (existing automations file) | Script fields UNVERIFIED, needs device test |
| event, actionevent | `state.sqlite3`, tables `event` and `actionevent` (new) | Retention by age, needs device test |
| alarm, alarmdef | `state.sqlite3`, tables `alarm` and `alarmdef` (new) | Definitions created at startup |
| minute, quarterhour, hour, day | `history.sqlite3` (existing) | 30-day retention (ARCHITECTURE) |
| m2mgeneric (raw measurements) | `history.sqlite3`, table `raw` (new) | 30-day retention |
| setting | `settings.json` (existing, optional) | Environment variables take precedence |
| cometmessage | `comet.py` ring buffer in memory | Not persisted; size limit set by the owner |
| map (and GridFS image) | `maps.json` plus image files in `maps/` in the data folder (new) | Image size limit to be set |
| user, admin, session | `users.json` with PBKDF2 hashes (new) | Sessions in memory |
| location, geofence, liveview, widget, template, configtemplate | `maps.json` (only if approved) | Fields UNVERIFIED, needs device test |

### Web API routes

Routes mirror the controller route family in `docs/controller/web-api.md`. The standalone login route already exists in mfi-server (`docs/controller/users.md`).

| Path | Method | Purpose | Status |
|---|---|---|---|
| `/api/v1/login` | POST | Password login; sets the session cookie | OBSERVED (mfi-server) |
| `/api/v1/logout` | POST | End the session (route name needs device test) | UNVERIFIED, needs device test |
| `/api/v1/cmd/devmgr` | POST | Device commands: mfi-output, kick-serial | OBSERVED (controller route name) |
| `/api/v1/upd/sensor` | POST | Update sensor fields, calibration, label | OBSERVED (controller route name) |
| `/api/v1/comet` | GET | Live updates long poll (route name needs device test) | UNVERIFIED, needs device test |
| `/api/v1/stat/<interval>` | GET | Read aggregates by interval (route name needs device test) | UNVERIFIED, needs device test |
| `/api/v1/rules` | GET, POST | Rules and scenes (route name needs device test) | UNVERIFIED, needs device test |
| `/api/v1/events` and `/api/v1/alarms` | GET | Events and alarms (route names need device test) | UNVERIFIED, needs device test |
| `/api/v1/upload/backup` | POST | Import a controller backup (mirrors `/upload/backup`) | OBSERVED (controller route) |
| `/dl/firmware/<path>` | GET | Firmware files from the own table; 404 for any other path | OBSERVED (mfi-server) |
| `/api/v1/maps` | GET, POST | Maps and images (only if approved) | UNVERIFIED, needs device test |

### Web page in style A

The page follows style A of `docs/design/DESIGN.md` for its look. This plan defines no CSS and no colours. The views mirror the controller interface areas. Which controller screens exist is UNVERIFIED, needs device test.

- Devices: list, state, adopt, forget, reboot, locate, firmware.
- Ports and outlets: outlet switches, dimmer level, lock, timer, mPort port assignment, calibration.
- Measurements: chart by interval from the aggregates.
- Rules and scenes: rulesets, actions, time rules, scenes.
- Alarms and events: lists, archive and acknowledge if approved.
- Users: password and accounts (see section 3).
- Maps and dashboard: only if the owner approves.
- System and settings: backup import, settings, version, update status.

### MQTT discovery toward Home Assistant

Home Assistant entities come through MQTT discovery (ARCHITECTURE decision, 2026-11-15). The table lists the entities per device type. The scales of the dimmer and the power-on behaviour are UNVERIFIED, needs device test.

| Device type | Home Assistant entities | Status |
|---|---|---|
| mPower outlet (P1U, P1E, P3U, P3E, P6E, P8U) | One switch per outlet; sensors for active power, power factor, energy, voltage and current | OBSERVED (measures); entity mapping is a proposal |
| In-wall outlet IWO2U | Two switches and their measure sensors | OBSERVED (measures); proposal |
| In-wall dimmer IWD1U | One light per port; brightness scale needs device test | UNVERIFIED, needs device test |
| In-wall switch IWS1U | None until its functions are read | UNVERIFIED, needs device test |
| mPort sensors MSW and MSC | Motion binary sensors and the tamper sensor | OBSERVED (tags); proposal |
| mPort sensor DS | Door or window binary sensor (inversion applied) | OBSERVED (tags); proposal |
| mPort sensor CS | Current sensor (amps, amp-hours) | OBSERVED (tags); proposal |
| mPort sensor THS | Temperature and humidity sensors | OBSERVED (tags); proposal |
| mPort sensor RTD, Counter, Input Analog, Input Digital | Temperature, counter, voltage and binary sensors | OBSERVED (tags); proposal |
| mPort output models and UVC PRO | Switches for the output port | OBSERVED (tags); port mapping needs device test |
| mPort Serial | No entity; serial settings through the web page | OBSERVED (no tags) |

## Security review

Each entry gives the risk, the proposal, and the owner decision still needed. The risks come from AGENTS.md rule 8 and the clean-room reports. No attack steps are given. Every entry needs the owner's answer before EPIC-13 starts.

### Webshell

- Risk: a terminal in the browser on a device or on the controller would give a shell to anyone who reaches the web interface. The 2015 firmware and controller have known weaknesses and an authentication bypass reported in 2015 (AGENTS.md rule 8). The access check of the controller is UNVERIFIED, needs device test (`docs/controller/network-tools.md`, section 1).
- Proposal: do not implement.
- OWNER DECISION NEEDED.

### SSH from the browser

- Risk: an SSH session opened from the web interface gives the same exposure as the webshell. The SSH connection has no host key check and uses old SSH ciphers on the device side (`docs/controller/network-tools.md`, section 5; `docs/controller/device-lifecycle.md`, section 1).
- Proposal: do not implement. The adoption SSH call stays, as it does today in mfi-server, and is not offered to the browser.
- OWNER DECISION NEEDED.

### UPnP

- Risk: service announcements on the local network may reveal the product and version. Their use by mFi devices is UNVERIFIED, needs device test. No repository document says the devices use UPnP (`docs/controller/network-tools.md`, section 2).
- Proposal: do not implement. If the owner wants it, implement it off by default, with a setting that is visible on the page.
- OWNER DECISION NEEDED.

### Guest access page

- Risk: a guest page can open network access to clients that were never authorised. The page is most likely inherited from UniFi, and its use with mFi devices is UNVERIFIED, needs device test (`docs/controller/network-tools.md`, section 3).
- Proposal: do not implement.
- OWNER DECISION NEEDED.

### Users and permissions

- Risk: the controller keeps the administrator password in clear text and sends it to every device as a DES-based crypt, which is weak by modern standards (`docs/controller/users.md`, section 5). mfi-server has a single password today, with no roles, no external authentication and no per-device token (`docs/controller/users.md`, gaps section). Groups and external authentication are UNVERIFIED, needs device test.
- Proposal: implement. Add accounts with PBKDF2 hashes, two roles (administrator and read-only), the existing lockout (401 and 429 limits), and no external authentication until the owner asks for it. The administrator password is never sent to devices; only the device key is used.
- OWNER DECISION NEEDED.

## Data migration

The migration runs at start, is idempotent, and makes a timestamped backup of every file before it changes anything. Old data stays readable: every new reader falls back to the old form. The migration never drops or rewrites user data without a backup.

- devices.json: the existing file keeps its keys and records. The migration adds the new fields with defaults and keeps the old keys. A second run changes nothing.
- history.sqlite3: the existing tables stay. The migration adds the new raw table (m2mgeneric) if it is missing. Retention stays at 30 days.
- Automations: the existing automations file is read in its current form. The migration only adds new fields with defaults. Script fields are UNVERIFIED, needs device test.
- Password hashes: salted PBKDF2 hashes stay as they are. Migration keeps the stored iteration count and salt and only adds a user record when none exists.
- Imported .unf backup: the device keys imported from a backup stay in devices.json, as today. A backup is only read; the migration never writes a backup back. The restore of the controller database (drop and rebuild) is not carried over (system area, `docs/controller/system.md`, section 2).

Each step writes a copy named with the date and time before the change. If a step fails, the copy is restored and the start stops with a message that names the file.

## mfi-controller and mfi-wifi-setup

- mfi-controller: keep. It is Phase 1, the original 2.1.11 controller in a container. It is the reference for comparing traffic and for the device tests that the rebuild needs (`docs/ARCHITECTURE.md`, Phase 1). Rewriting it would replace the reference. Whether it is retired after parity is an owner question (section 8).
- mfi-wifi-setup: keep. It is the Windows helper for the TLS 1.0 setup page of Wi-Fi devices, decided on 2026-11-17 (`docs/ARCHITECTURE.md`, decisions). mfi-server does not serve that page and does not replace the helper, so the helper stays as it is. Its spec stays in `docs/WIFI-SETUP.md`.

## Epic plan

Rules for every epic: at most 10 subtasks, each with at most 10 files. Common interfaces come first. Area epics follow in the order of their dependencies. The area epics map one-to-one to the target names used in section 1. EPIC-14 and EPIC-15 are cross-cutting and are not target names.

1. **EPIC-00 Skeleton of the new server.** Files: the new modules of `mfi-server/mfi_server/` as stubs with their docstrings, and the skeleton tests in `mfi-server/tests/`. Dependencies: none. Expected version: mfi-server minor, new package not yet wired; the old code keeps running.
2. **EPIC-01 Shared interfaces.** Files: `config.py`, `store.py`, `crypto.py`, `bson.py` and their tests. Dependencies: EPIC-00. Expected version: mfi-server minor.
3. **EPIC-02 Inform and devices.** Files: `inform.py`, `devices.py`, `tasks.py`, `firmware.py` and their tests. Dependencies: EPIC-01. Expected version: mfi-server minor.
4. **EPIC-03 Discovery.** Files: `discovery.py` and its tests. Dependencies: EPIC-02. Expected version: mfi-server minor.
5. **EPIC-04 Sensors and mPort.** Files: `sensors.py`, `serial.py` and their tests. Dependencies: EPIC-02. Expected version: mfi-server minor.
6. **EPIC-05 Rules and scenes.** Files: `rules.py` and its tests. Dependencies: EPIC-04. Expected version: mfi-server minor.
7. **EPIC-06 Events.** Files: `events.py` and its tests. Dependencies: EPIC-05 (actionevent), EPIC-01. Expected version: mfi-server minor.
8. **EPIC-07 Statistics.** Files: `stats.py` and its tests. Dependencies: EPIC-01, EPIC-04. Expected version: mfi-server minor.
9. **EPIC-08 Alarms.** Files: `alarms.py` and its tests. Dependencies: EPIC-06, EPIC-02. Expected version: mfi-server minor.
10. **EPIC-09 Users.** Files: `auth.py` and its tests. Dependencies: EPIC-01. Expected version: mfi-server minor.
11. **EPIC-10 System.** Files: `migrate.py` and its tests. Dependencies: EPIC-01, EPIC-07, EPIC-02. Expected version: mfi-server minor.
12. **EPIC-11 Web API.** Files: `web.py`, `comet.py` and their tests. Dependencies: EPIC-02, EPIC-04, EPIC-05, EPIC-07, EPIC-09. Expected version: mfi-server minor.
13. **EPIC-12 Maps and dashboard.** Files: `maps.py` and its tests. Dependencies: EPIC-11. Expected version: mfi-server minor, only if approved.
14. **EPIC-13 Network and Wi-Fi.** Files: the Wi-Fi setup fields in `web.py` and the Wi-Fi block in `sensors.py`, with tests. The webshell, SSH from the browser, UPnP and guest page are built only if the owner approves them. Dependencies: EPIC-02, EPIC-09, EPIC-11. Expected version: mfi-server minor.
15. **EPIC-14 MQTT discovery.** Files: `mqtt.py` and its tests. Dependencies: EPIC-02, EPIC-04, EPIC-05, EPIC-07, EPIC-08. Expected version: mfi-server minor.
16. **EPIC-15 Migration and 1.0.0 switch.** Files: `migrate.py` wiring, the add-on entry point, `config.yaml`, `Dockerfile`, `CHANGELOG.md`, `mfi_server/__init__.py`. Dependencies: all epics above. Expected version: mfi-server 1.0.0 (major).

## Version strategy

The new server ships as mfi-server 1.0.0, a major version, because everything changes. It keeps the same add-on slug so Home Assistant upgrades it in place. Until EPIC-15, today's code stays and keeps working; each epic raises mfi-server by one minor version through `tools/bump_version.py`. The switch to 1.0.0 is one bump of the major version in the same commit as the code switch, and the changelog says what changed for users.

## Open questions for the owner

- RAG doc 12 (2026-11-18) is not in this repository. The plan cites it as the decision; the owner confirms that its content matches this plan.
- Security OWNER DECISION NEEDED: webshell, SSH from the browser, UPnP, guest access page, and users and permissions (section 3).
- Script action over telnet (class_27 in the inventory): keep it, drop it, or keep it off by default? The security review does not cover it yet.
- Whether mfi-controller is retired after parity, or kept as the reference (section 5).
- Whether mfi-wifi-setup stays a separate Windows helper, or its setup fields move into the web page (section 5).
- Map and dashboard features (Location, Geofence, LiveView, Widget, Template): build them, or leave them to Home Assistant dashboards?
- Device-test gaps that block parts of the plan: the discovery port 10001, the decryption key order, the manual set-inform, the upgrade comparison rule and integrity check, the outlet timer and cycle command, the dimmer scale, the mPort port mapping for outputs, the custom sensor keys, and the serial data channel.
- UNVERIFIED routes: the Comet route, the statistics, rule, event and alarm routes, logout, and the map upload. Each needs a route check against a running controller before EPIC-11 starts.
- Settings and retention: the unit of `storage.ttl_time`, whether a removal job runs by itself, and the size limit of the live update buffer and of map images.
- Restore body: whether a failed backup read leaves a partial database in the controller. This must be tested on a copy of a controller before the migration design is final.
- Firmware fallback table: the measured table (10 models, 2.1.11.1309) against the 13-model table at 2.0.7 that the report mentions. Which one applies is UNVERIFIED, needs device test.
- Credentials for UI adoption and the decryption order: the sources disagree, so the owner chooses which behaviour mfi-server follows until a device test settles it.
