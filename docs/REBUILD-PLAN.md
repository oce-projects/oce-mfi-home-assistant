# Rebuild plan: mfi-server feature parity with the mFi Controller 2.1.11

This plan covers a full rewrite of mfi-server to reach feature parity with the mFi Controller 2.1.11, in Home Assistant style, for the whole repository (mfi-server, mfi-controller, mfi-wifi-setup, docs and tests). The rebuild decision is recorded as RAG doc 12, dated 2026-11-18. The owner decisions of 2026-11-19 (RAG docs 13, 14 and 15) are recorded in this plan with the label "owner decision 2026-11-19". Those documents are not in this repository, so this plan cites them and does not restate them.

The plan is built only from the clean-room reports in `docs/controller/` and the repository documents listed in the ticket. It copies no code or pseudocode from `ace.jar` and contains no device or site data. Every fact keeps the OBSERVED, INFERRED or UNVERIFIED label of its source. "Equal to mfi" means the same device-facing functions and behaviour, not the same graphics.

## Feature parity table

Each row names one controller function, the clean-room document it comes from, the label copied from that document, the epic that delivers it, and the recording that closes it. Epic names are defined in section 6. Recording codes are defined in section 8. A row with "needs device test" in its label is closed only by the recording named in the last column; "—" means no recording is needed.

Network and Wi-Fi rows that build a risky function carry the owner decision of 2026-11-19 (section 3).

| Area | Function | Source doc | Label | Target epic | Closed by |
|---|---|---|---|---|---|
| Inform and devices | Adoption from the UI (adopt command, SSH set-adopt on port 22) | docs/controller/device-lifecycle.md (section 1) | OBSERVED | EPIC-02 Inform and devices | — |
| Inform and devices | Credentials used for UI adoption: factory credentials on a factory-default device, controller administrator after adoption; mfi-server tries the administrator first and retries once with the factory credentials on loginfailed | docs/controller/device-lifecycle.md (section 1); QSG-PRO-EU p. 16; QSG-MPORT-S p. 17; UG-V11 p. 7 | CONFIRMED (official guide) | EPIC-02 Inform and devices | — |
| Inform and devices | Decryption key order for a device that has a previous key: the controller tries a list of candidate keys one by one (InformServlet), first that decrypts wins; mfi-server tries every known key (x_prev_authkey, x_authkey, factory key) | docs/controller/device-lifecycle.md (section 1) | OBSERVED | EPIC-02 Inform and devices | — |
| Inform and devices | Device-side handling of a manual set-inform | docs/controller/device-lifecycle.md (section 1) | UNVERIFIED, needs device test | EPIC-02 Inform and devices | R-ADOPT |
| Inform and devices | Automatic re-adoption of an adopted device that informs with the default flag | docs/controller/device-lifecycle.md (section 2) | OBSERVED | EPIC-02 Inform and devices | — |
| Inform and devices | Inform URL pushed to a device with setparam (mgmt_cfg) | docs/controller/device-lifecycle.md (section 2) | OBSERVED | EPIC-02 Inform and devices | — |
| Inform and devices | Condition under which a changed inform URL is pushed to an adopted device | docs/controller/device-lifecycle.md (section 2) | UNVERIFIED, needs device test | EPIC-02 Inform and devices | R-ADOPT |
| Inform and devices | Forget a connected device: queued setdefault task, state 8 | docs/controller/device-lifecycle.md (section 3) | OBSERVED | EPIC-02 Inform and devices | — |
| Inform and devices | Forget removes device, alarm, event, token, task and ap statistics | docs/controller/device-lifecycle.md (section 3) | OBSERVED | EPIC-02 Inform and devices | — |
| Inform and devices | Forget also removes m2mgeneric, rollups and rule references (needs device test) | docs/controller/device-lifecycle.md (section 3) | UNVERIFIED, needs device test | EPIC-02 Inform and devices | R-FORGET |
| Inform and devices | Factory reset commanded by the controller (setdefault message, no confirmation) | docs/controller/device-lifecycle.md (section 4) | OBSERVED | EPIC-02 Inform and devices | — |
| Inform and devices | Device-side result of setdefault (saved authkey cleared, factory key used) | docs/controller/device-lifecycle.md (section 4) | INFERRED | EPIC-02 Inform and devices | R-RESET (confirms the label) |
| Inform and devices | Reboot command (queued reboot task, record reloaded in state 0) | docs/controller/device-lifecycle.md (section 6) | OBSERVED | EPIC-02 Inform and devices | — |
| Inform and devices | Locate command on a connected device | docs/controller/device-lifecycle.md (section 6) | OBSERVED | EPIC-02 Inform and devices | — |
| Inform and devices | Locate on a device in state 2 (discovery call with value 30, needs device test) | docs/controller/device-lifecycle.md (section 6) | UNVERIFIED, needs device test | EPIC-02 Inform and devices | R-POWER |
| Inform and devices | Reply to a device without work: noop with a 10 s interval | docs/PROTOCOL.md (Controller responses) | OBSERVED | EPIC-02 Inform and devices | — |
| Inform and devices | Heartbeat missed after 40 s (state 6), needs device test | docs/controller/device-lifecycle.md (section 6) | UNVERIFIED, needs device test | EPIC-02 Inform and devices | R-POWER |
| Inform and devices | Lost contact after 120 s in state 1 or 6: event, record reload, disconnected notice | docs/controller/device-lifecycle.md (section 6) | OBSERVED | EPIC-02 Inform and devices | — |
| Inform and devices | Unadopted device removed from memory after 120 s silent; state 2 after 60 s silent | docs/controller/device-lifecycle.md (section 6) | OBSERVED | EPIC-02 Inform and devices | — |
| Inform and devices | Command queue: task sent in the reply to the next inform, only if connected; newer task for the same port replaces the old one | docs/PROTOCOL.md (Commands to the device) | OBSERVED | EPIC-02 Inform and devices | — |
| Inform and devices | Firmware upgrade message with the bundles.json entry; state 4 for 180 s | docs/controller/firmware.md (sections 2 and 4) | OBSERVED | EPIC-02 Inform and devices | — |
| Inform and devices | Upgrade comparison rule ("differs" or "not older"), needs device test | docs/controller/firmware.md (section 1) | UNVERIFIED, needs device test | EPIC-02 Inform and devices | R-UPDATE |
| Inform and devices | Upgrade integrity check and retry behaviour, needs device test | docs/controller/firmware.md (sections 2 and 4) | UNVERIFIED, needs device test | EPIC-02 Inform and devices | R-UPDATE |
| Inform and devices | Auto-upgrade flag and any bulk upgrade, needs device test | docs/controller/firmware.md (section 5) | UNVERIFIED, needs device test | EPIC-02 Inform and devices | R-UPDATE |
| Inform and devices | Restored device comes back in state 0 with ports showing NONE | docs/controller/device-lifecycle.md (section 5) | OBSERVED | EPIC-02 Inform and devices | — |
| Inform and devices | Restored device returns to state 1 at its next inform with the stored key | docs/controller/device-lifecycle.md (sections 1 and 5) | INFERRED | EPIC-02 Inform and devices | — |
| Discovery | UDP discovery on port 10001 with TLV announcements and replies, needs device test | docs/PROTOCOL.md (Discovery), docs/controller/network-tools.md | UNVERIFIED, needs device test | EPIC-03 Discovery | R-DISC (captured passively by the REG 2 recorder, owner decision 2026-11-19) |
| Discovery | TLV type 3 (version string) and type 22 (firmware version) in the discovery reply | docs/controller/firmware.md (section 1); docs/PROTOCOL.md (Discovery) | OBSERVED | EPIC-03 Discovery | — |
| Discovery | Discovery reply of an mPower mini without type 22; firmware derived from type 3 (other models: needs device test) | docs/controller/firmware.md (section 1) | OBSERVED | EPIC-03 Discovery | — |
| Discovery | Devices managed by another controller are ignored (default flag false) | docs/controller/device-lifecycle.md (section 1) | OBSERVED | EPIC-03 Discovery | — |
| Discovery | New device found: pending record in memory, event EVT_AP_DiscoveredPending | docs/controller/alarms.md (section 1) | OBSERVED | EPIC-03 Discovery | — |
| Sensors and mPort | Sensor model table: MSW, MSC, CS, DS, THS, Counter, Input Digital, Input Analog, RTD, Output 5v, Output 12v, Output 24v, UVC PRO, Serial | docs/controller/mport.md (section 1) | OBSERVED | EPIC-04 Sensors and mPort | — |
| Sensors and mPort | Spelling "Output  5v" with two spaces versus "Output 5v" (needs device test) | docs/controller/mport.md (section 1) | UNVERIFIED, needs device test | EPIC-04 Sensors and mPort | R-MPORT |
| Sensors and mPort | Assign a sensor type to a port; a sensor already on that port is unlinked | docs/controller/mport.md (section 2) | OBSERVED | EPIC-04 Sensors and mPort | — |
| Sensors and mPort | Port configuration lines of an mPort (port, AI, DI, DO) | docs/controller/mport.md (section 2); docs/PROTOCOL.md (mPort and sensors) | OBSERVED | EPIC-04 Sensors and mPort | — |
| Sensors and mPort | Sensor removal in a background thread: alarms, events, labels, readings, then the record | docs/controller/mport.md (section 2) | OBSERVED | EPIC-04 Sensors and mPort | — |
| Sensors and mPort | Per-sensor calibration string, default identity; changing it sends the configuration again | docs/controller/mport.md (section 3) | OBSERVED | EPIC-04 Sensors and mPort | — |
| Sensors and mPort | CustomSensors merged from dl/custom.json into the customSensors setting; built-in name takes precedence | docs/controller/mport.md (section 3) | OBSERVED | EPIC-04 Sensors and mPort | — |
| Sensors and mPort | Keys of a custom sensor definition and whether it reaches the device (needs device test) | docs/controller/mport.md (section 3) | UNVERIFIED, needs device test | EPIC-04 Sensors and mPort | R-MPORT |
| Sensors and mPort | Output command (mfi-output) on an mPort output port; port mapping (needs device test) | docs/controller/mport.md (section 4) | UNVERIFIED, needs device test | EPIC-04 Sensors and mPort | R-MPORT |
| Sensors and mPort | Output with output_lock 1 does not receive the output command | docs/controller/mport.md (section 4) | OBSERVED | EPIC-04 Sensors and mPort | — |
| Sensors and mPort | Output power-on state after power loss (model text says last state, needs device test) | docs/controller/mport.md (section 4) | UNVERIFIED, needs device test | EPIC-04 Sensors and mPort | R-MPORT |
| Sensors and mPort | Serial settings sent as ser2net_cfg (enable, baudRate, parity, uartMode, termination, antenna) | docs/controller/mport-serial.md (section 1) | OBSERVED | EPIC-04 Sensors and mPort | — |
| Sensors and mPort | Serial flow control, data bits and stop bits effect (needs device test) | docs/controller/mport-serial.md (section 1) | UNVERIFIED, needs device test | EPIC-04 Sensors and mPort | R-SERIAL |
| Sensors and mPort | kick-serial command and event EVT_mFi_SerialKick (device effect needs device test) | docs/controller/mport-serial.md (section 3) | OBSERVED | EPIC-04 Sensors and mPort | — |
| Sensors and mPort | Serial data channel (TCP port and who opens it, needs device test) | docs/controller/mport-serial.md (section 2) | UNVERIFIED, needs device test | EPIC-04 Sensors and mPort | R-SERIAL |
| Sensors and mPort | Measurements of an mPort M2S beyond the Serial sensor (needs device test) | docs/controller/mport-serial.md (section 4) | UNVERIFIED, needs device test | EPIC-04 Sensors and mPort | R-SERIAL |
| Sensors and mPort | mPower outlet on/off with mfi-output (val 1 on, 0 off, timer in seconds) | docs/controller/mpower.md (section 2) | OBSERVED | EPIC-04 Sensors and mPort | — |
| Sensors and mPort | mPower outlet measures: output, pf, energy_sum, v_rms, i_rms, active_pwr | docs/controller/mpower.md (section 4) | OBSERVED | EPIC-04 Sensors and mPort | — |
| Sensors and mPort | Outlet energy counter base kept by the controller across counter resets | docs/controller/mpower.md (section 4) | OBSERVED | EPIC-04 Sensors and mPort | — |
| Sensors and mPort | Manual energy counter reset for outlets (needs device test) | docs/controller/mpower.md (section 4) | UNVERIFIED, needs device test | EPIC-04 Sensors and mPort | R-MPOWER |
| Sensors and mPort | Outlet lock (output_lock sent as lock in port_cfg) | docs/controller/mpower.md (section 3) | OBSERVED | EPIC-04 Sensors and mPort | — |
| Sensors and mPort | Outlet power-on state from configed_val, then output_val | docs/controller/mpower.md (section 3) | INFERRED | EPIC-04 Sensors and mPort | — |
| Sensors and mPort | Outlet timer field meaning (delay, pulse or cycle, needs device test) | docs/controller/mpower.md (section 2) | UNVERIFIED, needs device test | EPIC-04 Sensors and mPort | R-MPOWER |
| Sensors and mPort | Cycle command (off then on in one step, needs device test) | docs/controller/mpower.md (section 2) | UNVERIFIED, needs device test | EPIC-04 Sensors and mPort | R-MPOWER |
| Sensors and mPort | Model codes P1U, P1E, P3U, P3E, P6E, P8U and their outlet counts | docs/controller/mpower.md (section 1) | OBSERVED | EPIC-04 Sensors and mPort | — |
| Sensors and mPort | Power measurement of P1U, P3U and P8U (needs device test) | docs/controller/mpower.md (section 1) | UNVERIFIED, needs device test | EPIC-04 Sensors and mPort | R-MPOWER |
| Sensors and mPort | In-wall outlet IWO2U: two outlets, measures and mfi-output | docs/controller/in-wall.md (section 1) | OBSERVED | EPIC-04 Sensors and mPort | — |
| Sensors and mPort | In-wall dimmer IWD1U: dimmer_mode, dimmer_lock_setting, dimmer_level in mfi-output | docs/controller/in-wall.md (sections 2 and 3) | OBSERVED | EPIC-04 Sensors and mPort | — |
| Sensors and mPort | Dimmer level scale, step, ramp unit, minimum and maximum (needs device test) | docs/controller/in-wall.md (sections 2 and 3) | UNVERIFIED, needs device test | EPIC-04 Sensors and mPort | documents only |
| Sensors and mPort | In-wall switch IWS1U functions and physical button event (needs device test) | docs/controller/in-wall.md (section 4) | UNVERIFIED, needs device test | EPIC-04 Sensors and mPort | documents only |
| Sensors and mPort | LED settings and effect of locate on P models (needs device test) | docs/controller/mpower.md (section 5) | UNVERIFIED, needs device test | EPIC-04 Sensors and mPort | R-MPOWER |
| Sensors and mPort | Sensor and port API: list sensors, add to port, move, edit fields, label | docs/controller/mport.md (section 6) | OBSERVED | EPIC-04 Sensors and mPort | — |
| Rules and scenes | Ruleset conditions on a sensor: compare, limit, duration in minutes, all or any, edge or level | docs/PROTOCOL.md (Rules and scenes) | OBSERVED | EPIC-05 Rules and scenes | — |
| Rules and scenes | Rule actions: email, event, relaySwitch, script, state, url, scene, rule | docs/PROTOCOL.md (Rules and scenes) | OBSERVED | EPIC-05 Rules and scenes | — |
| Rules and scenes | Rule queue limit of 30 requests | docs/controller/mport.md (section 5) | OBSERVED | EPIC-05 Rules and scenes | — |
| Rules and scenes | Sensor threshold implemented as a ruleset, not as an alarm definition | docs/controller/alarms.md (section 5) | OBSERVED | EPIC-05 Rules and scenes | — |
| Rules and scenes | Time rules with weekly intervals in the server time zone and calendars | docs/PROTOCOL.md (Rules and scenes) | OBSERVED | EPIC-05 Rules and scenes | — |
| Rules and scenes | Scenes group relaySwitch, script and url actions and raise EVT_mFi_Action | docs/PROTOCOL.md (Rules and scenes, Events) | OBSERVED | EPIC-05 Rules and scenes | — |
| Rules and scenes | Script action: a block of text sent to the serial port of the corresponding mPort Serial (off by default with a risk warning, see section 3) | docs/controller/INVENTORY.md (Classes, class_27); UG-V11 p. 23 | CONFIRMED (official guide) | EPIC-05 Rules and scenes | — |
| Rules and scenes | relaySwitch action skips a port whose output_lock is 1 and records an error | docs/controller/in-wall.md (section 4) | OBSERVED | EPIC-05 Rules and scenes | — |
| Rules and scenes | URL action: POST with rule, sensor and value fields to the addr list | docs/PROTOCOL.md (Rules and scenes) | OBSERVED | EPIC-05 Rules and scenes | — |
| Events | Save device events to the event collection with key and message | docs/PROTOCOL.md (Events) | OBSERVED | EPIC-06 Events | — |
| Events | Save rule and scene actions to the actionevent collection | docs/PROTOCOL.md (Events) | OBSERVED | EPIC-06 Events | — |
| Events | Event message text from the messages resource, with curly-bracket substitution | docs/controller/alarms.md (section 3) | OBSERVED | EPIC-06 Events | — |
| Events | Text of the messages resource (not readable, needs device test) | docs/controller/alarms.md (section 3) | UNVERIFIED, needs device test | EPIC-06 Events | R-WEB |
| Events | E-mail notification: email action, addr list, minute throttle, last_time | docs/controller/alarms.md (section 3) | OBSERVED | EPIC-06 Events | — |
| Events | Mail-server settings (SMTP host, port, authentication, sender; needs device test) | docs/controller/alarms.md (section 3) | UNVERIFIED, needs device test | EPIC-06 Events | R-WEB |
| Events | Event and actionevent retention through ttl_time indexes (needs device test) | docs/controller/alarms.md (section 4) | UNVERIFIED, needs device test | EPIC-06 Events | R-WEB |
| Statistics | Aggregates per minute, quarter hour, hour and day: max, min, ave, size, last_val | docs/PROTOCOL.md (Statistics) | OBSERVED | EPIC-07 Statistics | — |
| Statistics | Read interval chooses the aggregate; intervals capped at 3 years | docs/controller/mpower.md (section 6) | OBSERVED | EPIC-07 Statistics | — |
| Statistics | Raw measurements in m2mgeneric; collection name case needs check | docs/controller/system.md (section 3) | UNVERIFIED, needs device test | EPIC-07 Statistics | R-WEB |
| Statistics | Pattern stat.type.period for Wi-Fi, user and device statistics | docs/controller/system.md (section 3) | OBSERVED | EPIC-07 Statistics | — |
| Statistics | Type and period values of stat collections (needs device test) | docs/controller/system.md (section 3) | UNVERIFIED, needs device test | EPIC-07 Statistics | R-WEB |
| Statistics | storage.ttl_time default 13 and its unit (needs device test) | docs/controller/system.md (section 4) | UNVERIFIED, needs device test | EPIC-07 Statistics | R-WEB |
| Statistics | Deletion job of documents without ttl_time (needs device test) | docs/controller/system.md (section 3) | UNVERIFIED, needs device test | EPIC-07 Statistics | R-WEB |
| Alarms | Startup alarm definitions: DiscoveredPending, RediscoveredPending, Lost_Contact, WU and WG AssocPending, AD_UpdateAvailable | docs/controller/alarms.md (section 1) | OBSERVED | EPIC-08 Alarms | — |
| Alarms | Lost contact alarm raised after 120 s without inform, with repeat | docs/controller/alarms.md (sections 1 and 2) | OBSERVED | EPIC-08 Alarms | — |
| Alarms | Trigger of EVT_AD_UpdateAvailable (needs device test) | docs/controller/alarms.md (section 1) | UNVERIFIED, needs device test | EPIC-08 Alarms | R-UPDATE |
| Alarms | Monitor timers: 40 s and 60 s check, 120 s lost contact | docs/controller/alarms.md (section 2) | OBSERVED | EPIC-08 Alarms | — |
| Alarms | Monitor class fields and link to the contact check (needs device test) | docs/controller/alarms.md (section 2) | INFERRED | EPIC-08 Alarms | — |
| Alarms | Alarm record fields archived, occurs and handled_* | docs/controller/alarms.md (section 4) | OBSERVED | EPIC-08 Alarms | — |
| Alarms | Meaning of archived, occurs and handled_* (needs device test) | docs/controller/alarms.md (section 4) | INFERRED | EPIC-08 Alarms | — |
| Alarms | Acknowledge, archive and delete routes for alarms (needs device test) | docs/controller/alarms.md (section 4) | UNVERIFIED, needs device test | EPIC-08 Alarms | R-WEB |
| Alarms | Alarm retention and removal job (needs device test) | docs/controller/alarms.md (section 4) | UNVERIFIED, needs device test | EPIC-08 Alarms | R-WEB |
| Users | Administrator account used for automatic re-adoption | docs/controller/users.md (section 1) | OBSERVED | EPIC-09 Users | — |
| Users | Groups, per-account permissions and access to devices or locations (needs device test) | docs/controller/users.md (section 1) | UNVERIFIED, needs device test | EPIC-09 Users | R-WEB |
| Users | Login filter that protects the web routes (AuthFilter) | docs/controller/users.md (section 2) | OBSERVED | EPIC-09 Users | — |
| Users | Session, token and AuthServer roles in login (needs device test) | docs/controller/users.md (sections 2 and 4) | INFERRED | EPIC-09 Users | — |
| Users | Login route, session cookie and token expiry of the controller (needs device test) | docs/controller/users.md (section 2) | UNVERIFIED, needs device test | EPIC-09 Users | R-WEB |
| Users | Lockout after failed attempts on the controller (needs device test) | docs/controller/users.md (section 2) | UNVERIFIED, needs device test | EPIC-09 Users | R-WEB |
| Users | External authentication such as RADIUS or LDAP (needs device test) | docs/controller/users.md (section 4) | UNVERIFIED, needs device test | EPIC-09 Users | R-WEB |
| Users | Token created per device at adoption and removed at forget | docs/controller/users.md (section 3) | OBSERVED | EPIC-09 Users | — |
| Users | Standalone login: POST api/v1/login, session cookie, 401 and 429 limits | docs/controller/users.md (gaps section, from mfi-server/DOCS.md) | OBSERVED | EPIC-09 Users | — |
| Web API | Route family /api/v1.0/verb/object on the HTTPS port (port INFERRED) | docs/controller/web-api.md | INFERRED | EPIC-17 Controller-compatible API | — |
| Web API | cmd/devmgr for mfi-output and kick-serial | docs/controller/web-api.md; docs/PROTOCOL.md (Commands to the device) | OBSERVED | EPIC-17 Controller-compatible API | — |
| Web API | upd/sensor for sensor updates | docs/controller/web-api.md | OBSERVED | EPIC-17 Controller-compatible API | — |
| Web API | Comet long-poll live updates backed by the cometmessage capped collection (buffer) | docs/controller/web-api.md | OBSERVED | EPIC-11 Web API | — |
| Web API | Comet route name and message format (needs device test) | docs/controller/web-api.md | UNVERIFIED, needs device test | EPIC-17 Controller-compatible API | R-WEB |
| Web API | Statistics, rule, event and alarm routes (names needs device test) | docs/controller/web-api.md | UNVERIFIED, needs device test | EPIC-17 Controller-compatible API | R-WEB |
| Maps and dashboard | Location class and location collection (fields needs device test) | docs/controller/ui.md (section 1) | INFERRED | EPIC-12 Maps and dashboard | — |
| Maps and dashboard | Geofence class with markers and label (fields needs device test) | docs/controller/ui.md (section 2) | INFERRED | EPIC-12 Maps and dashboard | — |
| Maps and dashboard | Geofence entries per device, at most 11 (needs device test) | docs/controller/ui.md (section 2) | UNVERIFIED, needs device test | EPIC-12 Maps and dashboard | R-WEB |
| Maps and dashboard | LiveView and Widget classes (widget types needs device test) | docs/controller/ui.md (section 3) | INFERRED | EPIC-12 Maps and dashboard | — |
| Maps and dashboard | Template and ConfigTemplate classes (application to devices needs device test) | docs/controller/ui.md (section 4) | INFERRED | EPIC-12 Maps and dashboard | — |
| Maps and dashboard | Maps stay in the controller and are not sent to devices | docs/PROTOCOL.md (Device configuration) | OBSERVED | EPIC-12 Maps and dashboard | — |
| Maps and dashboard | Map upload form and map image route (needs device test) | docs/controller/system.md (section 5) | UNVERIFIED, needs device test | EPIC-12 Maps and dashboard | R-WEB |
| System | Backup file format: ZIP with db.gz, format, timestamp and version | docs/PROTOCOL.md (Controller backups) | OBSERVED | EPIC-10 System | — |
| System | Backup restore check of the version and timestamp entries | docs/controller/device-lifecycle.md (section 5); docs/controller/system.md (section 2) | OBSERVED | EPIC-10 System | — |
| System | Restore body: whole database dropped before reading the file (needs device test) | docs/controller/system.md (section 2) | UNVERIFIED, needs device test | EPIC-10 System | R-WEB |
| System | Excluded collections in a backup (cometmessage, system indexes, profile; statistics without a full backup) | docs/controller/device-lifecycle.md (section 5) | OBSERVED | EPIC-10 System | — |
| System | Database migration on version change (DbMigrator class exists; steps need device test) | docs/controller/system.md (section 3) | UNVERIFIED, needs device test | EPIC-10 System | not in REG 1 (needs a version change) |
| System | Default settings written at first start (needs device test) | docs/controller/system.md (section 4) | UNVERIFIED, needs device test | EPIC-10 System | not in REG 1 (first start) |
| System | outputTimer default 0 and timezone setting with default PST | docs/PROTOCOL.md (Device configuration); docs/PROTOCOL.md (Rules and scenes) | OBSERVED | EPIC-10 System | — |
| System | Launcher and Java 7 runtime (not carried over; replaced by the standalone program) | docs/controller/system.md (section 6); AGENTS.md (facts) | OBSERVED | EPIC-10 System | — |
| System | Update check that contacts a vendor address (needs device test) | docs/controller/system.md (section 6) | UNVERIFIED, needs device test | EPIC-10 System | R-WEB |
| System | Status servlet response fields (needs device test) | docs/controller/system.md (section 5) | UNVERIFIED, needs device test | EPIC-10 System | R-WEB |
| Network and Wi-Fi | SSH from the controller web interface (SshServlet): implement, off by default, risk warning (owner decision 2026-11-19) | docs/controller/network-tools.md (section 1) | INFERRED | EPIC-13 Network and Wi-Fi | — |
| Network and Wi-Fi | Web shell (WebshellServlet and input): implement, off by default, risk warning (owner decision 2026-11-19) | docs/controller/network-tools.md (section 1) | INFERRED | EPIC-13 Network and Wi-Fi | — |
| Network and Wi-Fi | UPnP service announcements (UpnpServlet), needs device test: implement, off by default, risk warning (owner decision 2026-11-19) | docs/controller/network-tools.md (section 2) | UNVERIFIED, needs device test | EPIC-13 Network and Wi-Fi | R-DISC (UDP, not recorded by REG 1) |
| Network and Wi-Fi | Guest access page (GuestServlet), needs device test: implement, off by default, risk warning (owner decision 2026-11-19) | docs/controller/network-tools.md (section 3) | UNVERIFIED, needs device test | EPIC-13 Network and Wi-Fi | R-WEB |
| Network and Wi-Fi | Wi-Fi setup form for devices in setup mode: essid, security, WEP and WPA fields, no channel field | docs/PROTOCOL.md (Wi-Fi setup mode); docs/WIFI-SETUP.md | OBSERVED | Not in mfi-server: stays in mfi-wifi-setup (section 5) | — |
| Network and Wi-Fi | WLAN settings change the configuration version and are sent with setparam | docs/PROTOCOL.md (Device configuration); docs/controller/network-tools.md (section 4) | OBSERVED | EPIC-13 Network and Wi-Fi | — |
| Network and Wi-Fi | Wi-Fi block format sent to devices and the vap_table conflict (needs device test) | docs/controller/network-tools.md (section 4) | UNVERIFIED, needs device test | EPIC-13 Network and Wi-Fi | R-WEB |
| Rules and scenes | Vacation mode; the port is switched off when vacation mode ends | REL-2.1.8 | OFFICIAL GUIDE ONLY | EPIC-05 Rules and scenes | R-WEB |
| System | NTP client control in the UI; time zone pushed to the devices | REL-2.1.8 | OFFICIAL GUIDE ONLY (time zone push: CONFIRMED, PROTOCOL.md system_cfg) | EPIC-10 System | R-WEB |
| Network and Wi-Fi | RADIUS (WPA Enterprise) authentication of the device Wi-Fi | REL-2.1.11 | OFFICIAL GUIDE ONLY | EPIC-13 Network and Wi-Fi | R-WEB |
| Events | Email action with "hold additional email alerts for N minutes" and SMS through a mail-to-SMS gateway address | UG-V11 p. 23 | CONFIRMED (official guide) | EPIC-06 Events | R-WEB |
| Events | Generate event with "don't create an event again for N minutes"; Create System Alert | UG-V11 p. 23 | OFFICIAL GUIDE ONLY | EPIC-06 Events | R-WEB |
| Rules and scenes | Copy a rule; enable or disable a rule with an On/Off button | UG-V11 p. 24 | OFFICIAL GUIDE ONLY | EPIC-05 Rules and scenes | R-WEB |
| Rules and scenes | Condition sets nested with Any/All; a schedule alone fires at its start and switches the output off at its end; a schedule with other conditions is an activity window | UG-V11 p. 22 | CONFIRMED (official guide) | EPIC-05 Rules and scenes | R-WEB |
| Rules and scenes | Output action with a duration in seconds, minutes or hours | UG-V11 p. 23 | CONFIRMED (official guide) | EPIC-05 Rules and scenes | R-MPOWER |
| Statistics | Energy price per kWh and currency symbol; monthly power and monthly cost of an outlet over 30 days | UG-V11 p. 10, p. 31 | OFFICIAL GUIDE ONLY | EPIC-07 Statistics | R-WEB |
| Web page | Auto refresh: manual, 5 s, 15 s, 30 s, 1 min, 2 min (default), 5 min | UG-V11 p. 9 | OFFICIAL GUIDE ONLY | EPIC-16 Web page | - |
| Web page | Data tab: saved views built by drag and drop, timeline zoom, outlet charts Power, Output, Power Factor, Total Energy, Voltage, Current | UG-V11 p. 16-18 | OFFICIAL GUIDE ONLY | EPIC-16 Web page | R-WEB |
| Web page | Events tab: filter, date range, temporal distribution (2-hour bars over 24 h) and device distribution (pie) | UG-V11 p. 19-20 | OFFICIAL GUIDE ONLY | EPIC-16 Web page | R-WEB |
| Maps and dashboard | Map scale in metres or feet; motion sensor field drawn on the map; lock an icon; topology view | UG-V11 p. 11-15 | OFFICIAL GUIDE ONLY | EPIC-12 Maps and dashboard | R-WEB |
| System | Backup limited to a chosen time period of data; Support Info download | UG-V11 p. 10 | OFFICIAL GUIDE ONLY | EPIC-10 System | R-WEB |
| Sensors and mPort | Move a machine to another outlet keeping its data and rules ("Move Device") | UG-V11 p. 31 | CONFIRMED (official guide) | EPIC-04 Sensors and mPort | R-MPOWER |

## Architecture

The new server is one standard-library Python package, `mfi-server/mfi_server_next/`, run as a Home Assistant add-on and as a standalone program (decisions of 2026-11-15 and 2026-11-18). It is built next to the current package `mfi-server/mfi_server/`, which stays intact and working until EPIC-15. The tests of the new package are in `mfi-server/tests_next/`.

Standalone: mfi-server runs with all of its functions without Home Assistant. Home Assistant is one client of the server, not a requirement. MQTT stays optional (decision of 2026-11-15).

### Current modules

The 30 files of `mfi-server/mfi_server/` (directory listing of 2026-11-19), and the module of `mfi_server_next/` that replaces each one. Files that this plan did not read in full (for example `bridge.py`, `server.py`, `packet.py`, `states.py`) are mapped by name only; the mapping is checked in EPIC-00.

| Current file in mfi_server/ | Replaced by in mfi_server_next/ | Epic | Note |
|---|---|---|---|
| `__init__.py` | `__init__.py` | EPIC-00 | Package marker and `__version__`; a package marker is not a name clash |
| `__main__.py` | `__main__.py` | EPIC-15 | Entry point of the standalone program and of the add-on |
| `adoption.py` | `devices.py` | EPIC-02 | Adopt and re-point; the SSH call of adoption stays in `devices.py` |
| `aes.py` | `crypto.py` | EPIC-01 | AES-128 for the inform payload |
| `api.py` | `page_api.py` (EPIC-11) and `compat_api.py` (EPIC-17) | EPIC-11, EPIC-17 | Two route families, see Web API routes |
| `auth.py` | `auth.py` | EPIC-09 | Accounts, roles, lockout |
| `automation_engine.py` | `rules.py` | EPIC-05 | Automation engine |
| `automation_model.py` | `rules.py` | EPIC-05 | Format and validation of automations |
| `automation_store.py` | `rules.py` | EPIC-05 | automations.json archive |
| `bridge.py` | `mqtt.py` | EPIC-14 | States and output commands over MQTT |
| `bson.py` | `bson.py` | EPIC-01 | BSON reader for backups |
| `commands.py` | `tasks.py` | EPIC-02 | Command queue |
| `config.py` | `config.py` | EPIC-01 | Settings, same file name, new package |
| `control.py` | `tasks.py` | EPIC-02 | Output command and wake-up |
| `discovery.py` | `mqtt_discovery.py` | EPIC-14 | Renamed: this file is the MQTT discovery of Home Assistant |
| `firmware.py` | `firmware.py` | EPIC-02 | Firmware table and upgrade message |
| `history.py` | `stats.py` | EPIC-07 | Aggregates and history |
| `measurements.py` | `stats.py` | EPIC-07 | Latest values |
| `messages.py` | `events.py` | EPIC-06 | Event messages |
| `mqtt.py` | `mqtt.py` | EPIC-14 | MQTT client |
| `packet.py` | `inform.py` | EPIC-02 | Inform packet format |
| `server.py` | `inform.py` | EPIC-02 | Inform HTTP server on port 6080 |
| `ssh_adopt.py` | `devices.py` | EPIC-02 | ssh set-adopt call |
| `states.py` | `devices.py` | EPIC-02 | Device state machine |
| `store.py` | `store.py` | EPIC-01 | sqlite3 and JSON persistence, same file name, new package |
| `ubnt_discovery.py` | `udp_discovery.py` | EPIC-03 | Renamed: UDP discovery on port 10001 (UNVERIFIED on a device) |
| `unf.py` | `migrate.py` | EPIC-10 | Controller backup reader |
| `upgrade.py` | `firmware.py` | EPIC-02 | Upgrade of devices |
| `wakeup.py` | `tasks.py` | EPIC-02 | Wake-up packet |
| `yaml_lite.py` | `editor.py` | EPIC-18 | YAML reader of the automation editor |

Same-name modules (`config.py`, `store.py`, `bson.py`, `firmware.py`, `auth.py`, `mqtt.py`) are new modules in a separate package that replace the old module of the same name in EPIC-15. They do not share code with the old package while both exist.

### Server modules

The new package `mfi-server/mfi_server_next/`. Module names are proposals; EPIC-00 creates the stubs.

| File under mfi-server/mfi_server_next/ | Responsibility | Public interface (proposed names) |
|---|---|---|
| `__init__.py` | Package version | `__version__` |
| `__main__.py` | Standalone entry point and add-on entry point | `main(argv)` |
| `config.py` | Settings from environment, then settings.json, then defaults | `load_settings(data_dir)` |
| `store.py` | sqlite3 and JSON persistence, temp file then rename, transactions | `Store.open()`, `Store.transaction()` |
| `crypto.py` | Own AES-128 for the inform payload; PBKDF2 hash for passwords | `aes128_decrypt()`, `pbkdf2_hash()`, `pbkdf2_verify()` |
| `bson.py` | BSON reader for controller backups | `read_bson_stream(fileobj)` |
| `inform.py` | Inform handling and the reply (noop, setparam, upgrade, cmd) | `handle_inform(payload, registry)` |
| `devices.py` | Device records, state machine, adoption, forget, factory reset | `DeviceRegistry` |
| `tasks.py` | Command queue delivered on the next inform | `TaskQueue.enqueue()`, `TaskQueue.pop_for_mac()` |
| `firmware.py` | Firmware table per model and upgrade message | `firmware_for_model(model)` |
| `udp_discovery.py` | UDP discovery on port 10001 (needs device test) | `UdpDiscovery` |
| `sensors.py` | Sensor models, port configuration, outlets, calibration, custom sensors, Wi-Fi block | `build_port_config()`, `SensorRegistry` |
| `serial.py` | mPort Serial settings and kick-serial | `build_ser2net_cfg()`, `kick_serial()` |
| `rules.py` | Automations in the Home Assistant format, rulesets, scenes, time rules | `AutomationEngine.tick()`, `AutomationStore` |
| `events.py` | Events, e-mail notice and their message text | `EventLog.record()` |
| `alarms.py` | Alarm definitions and alarm lifecycle | `AlarmStore.raise_alarm()` |
| `stats.py` | Aggregates per minute, quarter hour, hour and day | `Aggregator.add()`, `Aggregator.read()` |
| `auth.py` | Users, roles, sessions and login with PBKDF2 hashes | `login()`, `check_session()` |
| `page_api.py` | HTTP API of the web page (`api/v1/...`) | `make_handler()` |
| `comet.py` | Live update buffer for the long poll | `CometBuffer` |
| `compat_api.py` | Controller-compatible API (`api/v1.0/<verb>/<object>`) | `make_compat_handler()` |
| `maps.py` | Maps, locations, geofences, dashboards | `MapStore` |
| `mqtt.py` | MQTT client, state and output command bridge | `MqttBridge` |
| `mqtt_discovery.py` | MQTT discovery and state messages for Home Assistant | `discovery_messages()`, `state_messages()` |
| `migrate.py` | Data migration and backup import | `migrate_all(data_dir)`, `import_backup(path)` |
| `rules_import.py` | Conversion of old rules, rulesets, rule actions and scenes of a backup | `convert_rules(backup_docs)` |
| `editor.py` | YAML round trip for the automation editor | `to_yaml()`, `from_yaml()` |
| `web/` | Web page files: `index.html`, `style.css`, `app.js`, `i18n/en.json`, `i18n/it.json` | (static files) |

The package folder is `web/` and the page API module is `page_api.py`, so the names do not clash.

### Automations: one model

There is one automation model: the Home Assistant format, extended where the controller needs more (in `rules.py`, EPIC-05). Every old controller rule is converted to this format on import (EPIC-19). The editor (EPIC-18) edits this format, both visually and as YAML. The engine is our own code, written clean room (decision of 2026-11-16 in `docs/ARCHITECTURE.md`); the Home Assistant code is not copied.

"In mfi-server today" means the value in `mfi_server/automation_model.py` and `automation_engine.py` (checked 2026-11-19).

| Old rule (controller) | New automation (Home Assistant format) | In mfi-server today | Epic |
|---|---|---|---|
| Sensor threshold with a duration | `numeric_state` trigger with `for` | Yes (trigger with `for`) | EPIC-05 |
| Edge or level | Trigger (edge) or condition (level) | Yes: trigger for edge, condition for level | EPIC-05 |
| all / any | `and` / `or` conditions | Yes (`and`, `or`) | EPIC-05 |
| Weekly time intervals | `time` trigger or condition with `weekday` | Partly: `weekday` in conditions only; trigger form needs EPIC-05 | EPIC-05 |
| Calendars | New `calendar` trigger | No | EPIC-05 |
| relaySwitch | `switch.turn_on` / `switch.turn_off` | Yes (`switch.turn_on`, `switch.turn_off`) | EPIC-05 |
| Dimmer | `light.turn_on` with `brightness` | No | EPIC-05 |
| Scene | `scene.turn_on` | No | EPIC-05 |
| E-mail | `notify.email` | No | EPIC-06 |
| URL | HTTP POST action | No | EPIC-05 |
| Event | Event log entry (`events.py`) | No | EPIC-06 |
| Rule | `automation.trigger` | No | EPIC-05 |
| State | `automation.turn_on` / `automation.turn_off` | No | EPIC-05 |
| Script | Script action, off by default with a risk warning (section 3) | No | EPIC-05 |

### Data model

The controller stores its data in MongoDB collections. The new server uses sqlite3 tables or JSON files from the standard library. The stores are proposals; the collection names come from `docs/controller/system.md` (section 3) and `docs/controller/INVENTORY.md`.

| Controller collection | Proposed store | Notes |
|---|---|---|
| device | `devices.json` in the data folder (existing) | Written by temp file then rename |
| task | `state.sqlite3`, table `task` (new) | Queue needs transactional updates |
| sensor | `state.sqlite3`, table `sensor` (new) | Port links and calibration |
| rule, ruleset, ruleaction, rulestate, rulestatecalendar, ruleschedule, rulecondition | `automations.json` (existing automations file) | Home Assistant format; state fields kept in the same file; rulestate write frequency not yet measured (measure in EPIC-05) |
| scene, sceneaction, script | `automations.json` (existing automations file) | Script fields UNVERIFIED, needs device test |
| event, actionevent | `state.sqlite3`, tables `event` and `actionevent` (new) | Retention by age, needs device test |
| alarm, alarmdef | `state.sqlite3`, tables `alarm` and `alarmdef` (new) | Definitions created at startup |
| minute, quarterhour, hour, day | `history.sqlite3` (existing) | 30-day retention (ARCHITECTURE) |
| m2mgeneric (raw measurements) | `history.sqlite3`, table `raw` (new) | 30-day retention; raw table volume for 50+ devices not yet measured (measure in EPIC-07) |
| setting | `settings.json` (existing, optional) | Environment variables take precedence |
| cometmessage | `comet.py` ring buffer in memory | Not persisted; size limit set by the owner |
| map (and GridFS image) | `maps.json` plus image files in `maps/` in the data folder (new) | Image size limit to be set |
| user, admin, session | `users.json` with PBKDF2 hashes (new) | Sessions in memory |
| location, geofence, liveview, widget, template, configtemplate | `maps.json` (EPIC-12) | Fields UNVERIFIED, needs device test |

### Web API routes

Two route families, both under the same host and port, and both in the same server process:

1. **Page API** (`api/v1/...`, module `page_api.py`, EPIC-11): the API of the new web page. The current routes stay while the current page exists (until EPIC-15).
2. **Controller-compatible API** (`api/v1.0/<verb>/<object>`, module `compat_api.py`, EPIC-17): the route family of `docs/controller/web-api.md`, so that the Home Assistant `mfi` integration (library `mficlient`) works when it points to mfi-server. The prefix `api/v1/` used by `api.py` does not match `api/v1.0/`, so `compat_api.py` has its own route marker.

| Path | Family | Method | Purpose | Status |
|---|---|---|---|---|
| `/api/v1/login` | Page | POST | Password login; sets the session cookie | OBSERVED (mfi-server) |
| `/api/v1/logout` | Page | POST | End the session (route name needs device test) | UNVERIFIED, needs device test |
| `/api/v1/devices/<mac>/ports/<port>/output` | Page | POST | Output command of one port | OBSERVED (mfi-server) |
| `/api/v1/upload/backup` | Page | POST | Import a controller backup (mirrors `/upload/backup`) | OBSERVED (controller route) |
| `/api/v1/comet` | Page | GET | Live updates long poll (route name needs device test) | UNVERIFIED, needs device test |
| `/api/v1/stat/<interval>` | Page | GET | Read aggregates by interval (route name needs device test) | UNVERIFIED, needs device test |
| `/api/v1/rules` | Page | GET, POST | Automations and scenes (route name needs device test) | UNVERIFIED, needs device test |
| `/api/v1/events` and `/api/v1/alarms` | Page | GET | Events and alarms (route names need device test) | UNVERIFIED, needs device test |
| `/api/v1/maps` | Page | GET, POST | Maps and images | UNVERIFIED, needs device test |
| `/api/v1.0/cmd/devmgr` | Compatible | POST | Device commands: mfi-output, kick-serial | OBSERVED (controller route name) |
| `/api/v1.0/upd/sensor` | Compatible | POST | Update sensor fields, calibration, label | OBSERVED (controller route name) |
| `/api/v1.0/<verb>/<object>` for the other routes | Compatible | GET, POST | Statistics, rule, event and alarm routes (names need device test) | UNVERIFIED, needs device test |
| `/dl/firmware/<path>` | Both | GET | Firmware files from the own table; 404 for any other path | OBSERVED (mfi-server) |

### Web page in style A

The page follows style A of `docs/design/DESIGN.md` for its look. This plan defines no CSS and no colours. The views mirror the controller interface areas, and every view is built in EPIC-16. Which controller screens exist is UNVERIFIED, needs device test.

- Devices: list, state, adopt, forget, reboot, locate, firmware.
- Ports and outlets: outlet switches, dimmer level, lock, timer, mPort port assignment, calibration.
- Measurements: chart by interval from the aggregates.
- Rules and scenes: automations, scenes, and the editor of section 2 (EPIC-18); import of old rules (EPIC-19).
- Alarms and events: lists, archive and acknowledge.
- Users: accounts, roles and password (EPIC-09).
- Maps and dashboard: maps, locations, geofences and dashboards (EPIC-12).
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

Each entry gives the risk and the decision. The risks come from AGENTS.md rule 8 and the clean-room reports. No attack steps are given.

The owner decided the entries of 2026-11-19 (owner decision 2026-11-19): the five risky functions below are implemented, off by default, with a risk warning on the page and in DOCS.md. Their epics include abuse tests and need the owner's approval before merge. Users and permissions are implemented.

### Webshell

- Purpose: the web shell is a command line toward a serial-based device connected to an mPort Serial, not a shell on the controller. UG-V11 p. 13 says the Shell icon is "only available for serial-based devices" and that TCP port 2323 must be open on the controller firewall; UG-V11 p. 28 shows the IP address, port and protocol of the serial device and a "Web Shell" button. CONFIRMED (official guide) for the serial purpose (`docs/controller/network-tools.md`, section 1).
- Code check (REA, class `com.ubnt.ace.view.WebshellServlet`): the request carries `host`, `port` and `protocol` (`ssh` or `telnet`) and the servlet requires a logged-in admin session (`api.err.LoginRequired` otherwise). OBSERVED.
- Risk: the host and port come from the request and the code read shows no check that they belong to an adopted device, so the web shell can open a connection to any host and port reachable from the controller. OBSERVED for the parameters, UNVERIFIED for the absence of a check.
- Decision: implement, off by default, with a risk warning on the page and in DOCS.md (owner decision 2026-11-19). The new server allows the web shell only toward the host and port of an adopted mPort Serial.
- Built in EPIC-13; abuse tests; owner approval before merge.

### SSH from the browser

- Risk: an SSH session opened from the web interface gives the same exposure as the webshell. The SSH connection has no host key check and uses old SSH ciphers on the device side (`docs/controller/network-tools.md`, section 5; `docs/controller/device-lifecycle.md`, section 1).
- Decision: implement, off by default, with a risk warning on the page and in DOCS.md (owner decision 2026-11-19). The adoption SSH call stays in mfi-server as it is today; it is separate from the browser session and is not offered to the browser.
- Built in EPIC-13; abuse tests; owner approval before merge.

### UPnP

- Risk: service announcements on the local network may reveal the product and version. Their use by mFi devices is UNVERIFIED, needs device test. No repository document says the devices use UPnP (`docs/controller/network-tools.md`, section 2).
- Decision: implement, off by default, with a risk warning on the page and in DOCS.md (owner decision 2026-11-19).
- Built in EPIC-13; abuse tests; owner approval before merge.

### Guest access page

- Risk: a guest page can open network access to clients that were never authorised. The page is most likely inherited from UniFi, and its use with mFi devices is UNVERIFIED, needs device test (`docs/controller/network-tools.md`, section 3).
- Decision: implement, off by default, with a risk warning on the page and in DOCS.md (owner decision 2026-11-19).
- Built in EPIC-13; abuse tests; owner approval before merge.

### Script action over telnet

- What it is: a rule or scene script action is a block of text sent to the serial port of the corresponding mPort Serial, not a root shell on the device. UG-V11 p. 23: "A script is a block of text that is sent out to the serial port of the corresponding mPort Serial"; QSG-MPORT-S p. 4: the terminal block port is "for automation, such as script execution from the mFi Controller software". CONFIRMED (official guide) (`docs/controller/INVENTORY.md`, Classes, class_27).
- Risk: the commands are sent in clear text over telnet to the serial line of a device; it is not a root shell on the device, and the device side of the action is UNVERIFIED, needs device test.
- Decision: implement, off by default, with a risk warning on the page and in DOCS.md (owner decision 2026-11-19).
- Built in EPIC-05; abuse tests; owner approval before merge.

### Users and permissions

- Risk: the controller keeps the administrator password in clear text and sends it to every device as a DES-based crypt, which is weak by modern standards (`docs/controller/users.md`, section 5). mfi-server has a single password today, with no roles, no external authentication and no per-device token (`docs/controller/users.md`, gaps section). Groups and external authentication are UNVERIFIED, needs device test.
- Decision: implement (owner decision 2026-11-19). Add accounts with PBKDF2 hashes, two roles (administrator and read-only), the existing lockout (401 and 429 limits), and no external authentication until the owner asks for it. The administrator password is never sent to devices; only the device key is used.
- Built in EPIC-09; abuse tests; owner approval before merge.

## Data migration

The migration runs at start, is idempotent, and makes a timestamped backup of every file before it changes anything. Old data stays readable: every new reader falls back to the old form. The migration never drops or rewrites user data without a backup.

- devices.json: the existing file keeps its keys and records. The migration adds the new fields with defaults and keeps the old keys. A second run changes nothing.
- history.sqlite3: the existing tables stay. The migration adds the new raw table (m2mgeneric) if it is missing. Retention stays at 30 days.
- Automations: the existing automations file is read in its current form. The migration only adds new fields with defaults. Script fields are UNVERIFIED, needs device test.
- Password hashes: salted PBKDF2 hashes stay as they are. Migration keeps the stored iteration count and salt and only adds a user record when none exists.
- Imported .unf backup: the device keys imported from a backup stay in devices.json, as today. A backup is only read; the migration never writes a backup back. The restore of the controller database (drop and rebuild) is not carried over (system area, `docs/controller/system.md`, section 2).

Each step writes a copy named with the date and time before the change. Because devices.json holds device keys, every timestamped copy is written with file permissions 0600 (owner read and write only), and only the most recent copies are kept (the number is a setting, default 5); older copies are deleted. If a step fails, the copy is restored and the start stops with a message that names the file.

## mfi-controller and mfi-wifi-setup

- mfi-controller: keep (owner decision 2026-11-19). It is Phase 1, the original 2.1.11 controller in a container. It is the reference for comparing traffic and for the recordings of section 8 that the rebuild needs (`docs/ARCHITECTURE.md`, Phase 1). Rewriting it would replace the reference.
- mfi-wifi-setup: keep as a separate Windows helper (owner decision 2026-11-19). It is the helper for the TLS 1.0 setup page of Wi-Fi devices, decided on 2026-11-17 (`docs/ARCHITECTURE.md`, decisions). mfi-server does not serve that page and does not replace the helper, so the helper stays as it is. Its spec stays in `docs/WIFI-SETUP.md`.

## Epic plan

Rules for every epic: at most 10 subtasks, each with at most 10 files. The numbers are identifiers; execution follows the dependencies, and EPIC-15 always runs last. The DevAgentAi test rule for `mfi-server/tests_next` is set in the chat before EPIC-00 (a setting, not a manual step). The area epics map one-to-one to the target names of section 1 (EPIC-02 to EPIC-13). The other epics are cross-cutting.

1. **EPIC-00 Skeleton of the new server.** Files: the stubs of `mfi-server/mfi_server_next/` with their docstrings, and the skeleton tests in `mfi-server/tests_next/`. Dependencies: none. Expected version: mfi-server minor; the new package is not wired in, and the old code keeps running.
2. **EPIC-01 Shared interfaces.** Files: `mfi_server_next/config.py`, `store.py`, `crypto.py`, `bson.py` and their tests. Dependencies: EPIC-00. Expected version: mfi-server minor.
3. **EPIC-01b Compatibility fixtures and replay tests.** Files: `tests_next/fixtures/compat/` (anonymised recordings of section 8), `tests_next/test_compat_replay.py`. Dependencies: EPIC-01, and the recordings of the MANUAL STEP of section 8 (the REG 1 recorder already exists). For each recorded exchange the new server must give an equivalent answer. The replay test of an exchange is enabled by the epic that owns its route; until then it is listed as pending, never skipped in silence. Expected version: mfi-server minor.
4. **EPIC-02 Inform and devices.** Files: `inform.py`, `devices.py`, `tasks.py`, `firmware.py` and their tests. Dependencies: EPIC-01, EPIC-01b. Expected version: mfi-server minor.
5. **EPIC-03 Discovery.** Files: `udp_discovery.py` and its tests. Dependencies: EPIC-02. Expected version: mfi-server minor. UDP discovery is not recorded by REG 1 (section 8, R-DISC).
6. **EPIC-04 Sensors and mPort.** Files: `sensors.py`, `serial.py` and their tests. Dependencies: EPIC-02. Expected version: mfi-server minor.
7. **EPIC-05 Rules and scenes.** Files: `rules.py`, `rules_import.py` placeholder is not in this epic, and the tests of `rules.py`. Includes the script action over telnet, off by default, with abuse tests. Dependencies: EPIC-04. Expected version: mfi-server minor. Owner approval before merge for the telnet action.
8. **EPIC-06 Events.** Files: `events.py` (event log, e-mail notice through `notify.email`) and its tests. Dependencies: EPIC-05, EPIC-01. Expected version: mfi-server minor.
9. **EPIC-07 Statistics.** Files: `stats.py` and its tests. Dependencies: EPIC-01, EPIC-04. Expected version: mfi-server minor.
10. **EPIC-08 Alarms.** Files: `alarms.py` and its tests. Dependencies: EPIC-06, EPIC-02. Expected version: mfi-server minor.
11. **EPIC-09 Users.** Files: `auth.py` and its tests (accounts, roles, lockout). Dependencies: EPIC-01. Expected version: mfi-server minor. Abuse tests; owner approval before merge.
12. **EPIC-10 System.** Files: `migrate.py` and its tests. Dependencies: EPIC-01, EPIC-07, EPIC-02. Expected version: mfi-server minor.
13. **EPIC-11 Web API.** Files: `page_api.py`, `comet.py` (buffer) and their tests. The page API exposes the events, alarms and backup-import routes, so it depends on the modules that own them. Dependencies: EPIC-02, EPIC-04, EPIC-05, EPIC-06, EPIC-07, EPIC-08, EPIC-09, EPIC-10. Expected version: mfi-server minor.
14. **EPIC-12 Maps and dashboard.** Files: `maps.py` and its tests. Dependencies: EPIC-11. Expected version: mfi-server minor.
15. **EPIC-13 Network and Wi-Fi.** Files: the Wi-Fi block in `sensors.py`; the webshell, SSH from the browser, UPnP and guest page, each off by default with a risk warning on the page and in DOCS.md; with tests, including abuse tests. The web shell is allowed only toward the host and port of an adopted mPort Serial (serial line over telnet, see Security review). The Wi-Fi setup form for devices in setup mode stays in mfi-wifi-setup (section 5). Dependencies: EPIC-02, EPIC-09, EPIC-11. Expected version: mfi-server minor. Owner approval before merge.
16. **EPIC-14 MQTT.** Files: `mqtt.py`, `mqtt_discovery.py` and their tests. Dependencies: EPIC-02, EPIC-04, EPIC-05, EPIC-07, EPIC-08. Expected version: mfi-server minor.
17. **EPIC-15 Migration and 1.0.0 switch.** Files: `__main__.py`, the add-on entry point, `config.yaml`, `Dockerfile`, `CHANGELOG.md`, `mfi_server/__init__.py`, and the switch of the package name in the add-on. Dependencies: EPIC-00 to EPIC-14 and EPIC-16 to EPIC-19 (all approved epics). Runs last. Expected version: mfi-server 1.0.0 (major).
18. **EPIC-16 Web page (style A).** Files: `mfi_server_next/web/` (`index.html`, `style.css`, `app.js`, `i18n/en.json`, `i18n/it.json`) and their tests. Views: devices, ports and outlets, measurements, rules and scenes, alarms and events, users, maps and dashboard, system. Dependencies: EPIC-11. Expected version: mfi-server minor.
19. **EPIC-17 Controller-compatible API.** Files: `compat_api.py` and its tests, run against the fixtures of EPIC-01b. Routes of `docs/controller/web-api.md` under `api/v1.0/<verb>/<object>`. Dependencies: EPIC-11, EPIC-01b, and the R-WEB route checks of section 8 (before this epic starts). Expected version: mfi-server minor.
20. **EPIC-18 Automation editor.** Files: `editor.py` (YAML round trip) and the editor part of `web/`, with tests. Visual editor like Home Assistant: "When / And if / Then do", "+ Add" with the list of types, guided choice of device and port, switch to YAML, and traces. Clean room: the way of working of Home Assistant is imitated, no Home Assistant code is copied (decision of 2026-11-16). Dependencies: EPIC-05, EPIC-16. Expected version: mfi-server minor.
21. **EPIC-19 Import of old rules.** Files: `rules_import.py` and its tests. Converts `rule`, `ruleset`, `ruleaction` and `scene` of the `.unf` backup to the automations of section 2 (table "Old rule → new automation"). Dependencies: EPIC-05, EPIC-16. Expected version: mfi-server minor.

## Version strategy

The new server ships as mfi-server 1.0.0, a major version, because everything changes. It keeps the same add-on slug so Home Assistant upgrades it in place. Until EPIC-15, today's code stays and keeps working; each epic raises mfi-server by one minor version through `tools/bump_version.py`. The switch to 1.0.0 is one bump of the major version in the same commit as the code switch, and the changelog says what changed for users.

## Compatibility test bench

The device tests of section 1 need real traffic. The bench is the recorder of the controller add-on and the offline decoder that already exist; no new tool is needed for the recording. The official sources used in this plan are listed in docs/OFFICIAL-SOURCES.md.

- **Recorder**: `mfi-controller/recorder.py` (ticket REG 1, repository 0.23.0). It records the exchanges on the inform port 6080 and on the web port 6443 of the original controller. Files are written to `/share/mfi-recordings/` in the add-on share.
- **Decoder**: `tools/decode_recording.py --anonymize` (offline, standard library). The anonymised output contains no real MAC address, IP address, host name or authkey. The anonymised files are checked before commit.
- **Fixtures**: the anonymised recordings become fixtures in `mfi-server/tests_next/fixtures/compat/` (EPIC-01b).
- **Replay**: each recorded exchange must get an equivalent answer from the new server: the same status code and the same JSON keys and value types. Per-device values (MAC, key, time) are compared by the replay test, not copied.

Recording codes and the rows of section 1 they close:

| Code | What is recorded | Closes (rows marked "needs device test" in section 1) |
|---|---|---|
| R-ADOPT | Adoption of a factory-default device from the controller UI; re-adoption; change of the inform URL | Credentials for UI adoption, decryption key order, manual set-inform, inform URL condition |
| R-POWER | Power off and on; reboot; locate; a device that stops informing (heartbeat, lost contact) | Locate in state 2, missed heartbeat |
| R-FORGET | Forget of a connected device | Removal of m2mgeneric, rollups and rule references |
| R-RESET | Factory reset ordered by the controller | Confirms the INFERRED device-side result of setdefault |
| R-UPDATE | Firmware update of one device | Upgrade comparison rule, integrity check, auto-upgrade flag, EVT_AD_UpdateAvailable |
| R-MPORT | mPort with sensors: assign, calibration, custom sensor, output port | Spelling "Output  5v", custom sensor keys, output command, output power-on state |
| R-SERIAL | mPort M2S with the Serial sensor | Flow control, serial data channel, M2S measurements |
| R-MPOWER | mPower outlets: on/off, timer, cycle, lock, energy counter, LED | Timer field, cycle command, manual energy reset, power of P1U, P3U and P8U, LED and locate |
| R-INWALL | not recorded: the owner has no in-wall device; documents only (owner decision 2026-11-19) | Dimmer scale, IWS1U functions |
| R-WEB | Controller web UI: login, users, rules and scenes, maps, alarms, events, statistics, backup download and restore, WLAN settings, guest page | Every row marked R-WEB in section 1 (users, events, statistics, alarms, web API routes, maps, system, network) |
| R-DISC | Recorded by REG 2 (owner decision 2026-11-19): the recorder of mfi-controller also captures passively the UDP traffic of port 10001 (discovery) and port 3478 (wake-up), in the same daily file as the TCP lines; TCP ports 6080 and 6443 stay with REG 1. A run with real devices is still needed (see the MANUAL STEP of this section) | UDP discovery on port 10001 and wake-up on port 3478 |

MANUAL STEP (owner): run the controller add-on with real devices and record, one session per item: adoption, power on and off, firmware update, forget, factory reset, mPort sensors, mPort M2S serial, and mPower outlets (timer, cycle, lock). In the same sessions, use the controller web UI for the R-WEB actions. In-wall models only if the owner has them (not verified). The owner copies the recordings out of the add-on share, anonymises them with `tools/decode_recording.py --anonymize`, and reviews them before they are committed to `mfi-server/tests_next/fixtures/compat/`. The agent does not run the recordings.

## Open questions for the owner

- Device-test gaps that block parts of the plan: the discovery port 10001 (not recorded by REG 1; decide whether a separate UDP capture is added), the manual set-inform, the upgrade comparison rule and integrity check, the outlet timer and cycle command, the dimmer scale, the mPort port mapping for outputs, the custom sensor keys, and the serial data channel.
- UNVERIFIED routes: the Comet route, the statistics, rule, event and alarm routes, logout, and the map upload. Each needs a route check through R-WEB against a running controller before EPIC-17 starts; the page routes of EPIC-11 are checked the same way.
- Settings and retention: the unit of `storage.ttl_time`, whether a removal job runs by itself, and the size limit of the live update buffer and of map images.
- Restore body: whether a failed backup read leaves a partial database in the controller. This must be tested on a copy of a controller before the migration design is final.
- Firmware fallback table: the measured table (10 models, 2.1.11.1309) against the 13-model table at 2.0.7 that the report mentions. Which one applies is UNVERIFIED, needs device test.
- Future work after parity (not an open question, not one of the epics above): new firmware for the devices.
