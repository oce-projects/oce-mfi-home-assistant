# Device lifecycle of the mFi Controller 2.1.11 (clean room)

This is a clean-room report of the device lifecycle in mFi Controller 2.1.11 (`ace.jar`). It is built from the reverse-engineering report of ticket T-MWMRR0PZ (REA below). It contains no code and no pseudocode. Java class, method, field and MongoDB collection names are cited as names only. Every fact line ends with a status tag (OBSERVED, INFERRED or UNVERIFIED) and a source.

Source abbreviations: **REA n.X** is output number X of the REA run, with the class or report section it names. **PROTO** is `docs/PROTOCOL.md`, **INV** is `docs/controller/INVENTORY.md` (Device lifecycle table). Where the REA report names no method, the source gives the report section instead.

## 1. Adoption

- A new device that informs with the factory key is created in memory only, with state 2 (discovered, pending adoption), and raises `EVT_AP_DiscoveredPending`. It is not written to the database. OBSERVED. Source: REA n.3 DeviceManager, discovery; PROTO "Adoption" step 1.
- A device that reports it is managed by another controller (default flag false) is ignored. OBSERVED. Source: REA n.3 DeviceManager, discovery; PROTO "Adoption" step 1.
- If the inform carries a cloud name and password that match a controller administrator, adoption starts without the UI. Otherwise the controller answers `setdefault` to devices that are not in the default state. The code path is OBSERVED. Source: REA section "Flusso", 1. Adozione. Whether these two fields really travel in a real inform is UNVERIFIED on a device. Source: PROTO open questions 10 and 16.
- The UI calls the adopt command with one or more MAC addresses. OBSERVED. Source: REA section "Flusso", 1. Adozione; INV "Device lifecycle", Adoption row.
- At adoption a device record is created with `adopted` true, a random `x_authkey`, `cfgversion` and `portversion`, and an empty `port_cfg` with the port count of its model (table in PROTO "Devices"). OBSERVED. Source: REA "Formati" (record Device, n.3 DeviceManager).
- The record is inserted in the collection `device`. The authkey is stored there in the field `x_authkey`. OBSERVED. Source: REA "Formati" (record Device, collection `device`, n.3).
- The authkey is 32 characters from `0123456789abcdef`, generated with `java.util.Random`. It is not cryptographic. OBSERVED. Source: PROTO "Adoption", authkey generation; REA "Costanti".
- The device state is set to 7 (adopting) with a 120 s expiry. OBSERVED. Source: REA n.3 state table; PROTO "Device states in the controller".
- A Token record is created in the collection `token` for the MAC if none exists. OBSERVED. Source: REA "Formati" (Token) and "Flusso", 1. Adozione.
- The discovery alarm is archived and `EVT_AP_Adopted` is raised. OBSERVED. Source: REA section "Flusso", 1. Adozione.
- SSH adoption: the controller opens an SSH session through `com.ubnt.net.UbntDiscoveryServer` on port 22, with a 3000 ms timeout and no host key check. It runs `/usr/bin/syswrapper.sh set-adopt <url> <authkey>` with the inform URL and the new key. The command result is not read. OBSERVED. Source: REA "Costanti" (n.5 class_18, n.6 class_20); PROTO "Adoption" item 3.
- Default SSH credentials for the discovery method are `ubnt` / `ubnt`. OBSERVED. Source: REA "Costanti"; PROTO "Adoption" item 4.
- Conflict on UI adoption credentials: REA "Costanti" says UI adoption uses the controller administrator name and password, while PROTO "Adoption" item 4 says `ubnt` / `ubnt` for a normal adoption and the administrator credentials only for automatic re-adoption. Which one applies to UI adoption is UNVERIFIED. Source: REA "Costanti"; PROTO "Adoption" item 4.
- Manual `set-inform` from the device side is not handled by the controller. The code has no `set-inform` and no `mca-cli`. The absence is OBSERVED. Source: PROTO "Adoption" ("Not used"); REA section "Flusso", 1. Adozione. What the device does with a manual `set-inform` is UNVERIFIED (not in the source).
- The first inform after adoption is still signed with the factory key. The controller answers `setparam` with `mgmt_cfg` containing `mgmt.authkey`, `cfgversion` and `portversion`. The `authkey` line is sent only when the key the device used differs from `x_authkey`. OBSERVED. Source: REA n.3 DeviceManager, inform handling; REA n.9 ConfigService, `mgmt_cfg`; PROTO "Controller responses", row 5.
- From the second inform the device signs with `x_authkey` and reaches state 1, and `EVT_AP_Connected` is raised. OBSERVED. Source: REA section "Flusso", 1. Adozione, step 3.
- Decryption key order: REA says `x_prev_authkey`, then `x_authkey`, then the factory key. PROTO says that for a device with `x_prev_authkey` the order is `x_prev_authkey`, then `x_authkey`, with no factory key. Which order is right is UNVERIFIED. Source: REA section "Flusso", 1. Adozione (n.8 and n.3); PROTO "Encryption" table.
- Where the device keeps the authkey: the controller sends it as `mgmt.authkey` in `mgmt_cfg`. The file on the device that holds it is not in the code read. OBSERVED for the field name; device-side storage UNVERIFIED. Source: PROTO "Controller responses"; REA "Costanti" (device file `/etc/persistent/cfg/mgmt` is written by a `sed` command, n.5 class_18).

## 2. Re-adoption and controller change

- A device adopted by another controller is reset to factory settings if it talks to this controller. OBSERVED. Source: PROTO "Adoption" item 2; PROTO "Controller responses", row 1 (a non-adopted device with a non-default key gets `setdefault`).
- A device "managed by another AC" that is not in the default state is ignored, not adopted. OBSERVED. Source: REA n.3 DeviceManager, discovery; PROTO "Adoption" item 1.
- Automatic re-adoption: if an adopted device informs with the default flag true, the controller re-adopts it by itself. The flag `autoReadopt` is always true. OBSERVED. Source: REA section "Flusso", 2. Ri-adozione; REA n.11 SystemService.
- Re-adoption raises `EVT_AP_AutoReadopted`, reuses `x_authkey` and the existing record, and only re-runs the SSH `set-adopt` command with the computed inform URL and the existing authkey. OBSERVED. Source: REA section "Flusso", 2. Ri-adozione.
- If the device is adopted but not in the default state, the controller does not use SSH and sends the current configuration instead. OBSERVED. Source: REA section "Flusso", 2. Ri-adozione.
- Re-adoption SSH credentials: PROTO says the administrator name and password. This is consistent with item 4 of PROTO "Adoption" and the conflict noted in section 1. OBSERVED for the PROTO statement; the report does not repeat it. Source: PROTO "Adoption" item 4.
- The inform URL has the form `http://<host>:<port>/inform`. If the customized inform setting is true, host and port come from that setting. Otherwise the host comes from the inform URL already stored on the device, and failing that from the controller address in the device's subnet. The default port is the controller's HTTP port. OBSERVED. Source: REA "Costanti" (n.9 ConfigService).
- The method that builds the inform URL is not named in the REA report. Its name is UNVERIFIED. Source: REA n.9 ConfigService (no method name given).
- `ConfigService` writes `mgmt.servers.1.url=http://<host>:<port>/inform` in `mgmt_cfg` of a `setparam` message. OBSERVED. Source: REA n.9 ConfigService; PROTO "Controller responses" (`mgmt_cfg`).
- The controller compares the `inform_url` received in the inform with the stored one and updates the record when they differ. OBSERVED. Source: REA section "Flusso", 2. Ri-adozione (no method name given).
- The condition under which a changed inform URL is pushed to an adopted device (which `setparam` row applies) is not stated in the code read. UNVERIFIED. Source: PROTO "Controller responses" (rows 4 and 8 carry `mgmt_cfg`, row 5 applies to the factory key only).
- Behaviour when the device is managed by another controller and a change of controller occurs: the REA report found no further code. UNVERIFIED. Source: REA section "Flusso", 2. Ri-adozione.

## 3. Forget (delete from the server)

- `delete-ap` on a connected device (state 1): a Task of type `setdefault` is queued and the device moves to state 8 (being deleted). When the device executes the task, the controller deletes the data and reloads the device list. OBSERVED. Source: REA section "Flusso", 3. Cancellazione; REA n.3 DeviceManager.
- `delete-ap` on a device that is not connected: the deletion happens at once. OBSERVED. Source: REA section "Flusso", 3. Cancellazione.
- Removed from the database by the MAC or the `ap` field: documents of `device`; documents of `alarm` and `event` with `ap` set to the MAC; documents of `token` and `task` with the MAC; and the statistics collections named `stat.<granularity>.ap.<mac>`. OBSERVED. Source: REA "Flusso", 3 (n.3 DeviceManager, deletion method); REA "Formati" (collection `task`).
- The collection name `task` is UNVERIFIED in INV (table "Inform and devices"). REA "Formati" names it. OBSERVED here from REA. Source: REA "Formati" (Task, collection `task`); INV "Inform and devices".
- Left in the database, according to REA: the per-sensor statistics, the `sensor` records and the client (`user`) data. OBSERVED. Source: REA section "Flusso", 3 ("Restano").
- Not named in REA, so UNVERIFIED: whether the device's `m2mgeneric` records, its minute, quarter-hour, hour and day aggregates, and rule or scene references to the device are removed. Source: REA section "Flusso", 3; REA n.3.
- The command raises `EVT_AP_Deleted`. OBSERVED. Source: REA section "Flusso", 3; REA n.3 event list.
- A deleted connected device receives no further command after the `setdefault` task. The device-side outcome of `setdefault` is covered in section 4. INFERRED from the queue behaviour. Source: REA section "Flusso", 3 and 4.

## 4. Factory reset commanded by the controller

- The `setdefault` task makes the controller send the `setdefault` message to the device. OBSERVED. Source: REA n.3 DeviceManager; PROTO "Commands to the device" (`_type: setdefault`, no fields).
- The device returns to its factory state and its saved configuration, including `x_authkey`, is cleared. INFERRED from the report's wording ("the device zeroes its configuration and therefore the saved authkey"); the device side is not in the code read. Source: REA section "Flusso", 4. Ripristino di fabbrica.
- After reset the device signs with the factory key, which is the same for every reset device. INFERRED from PROTO "Encryption" (factory constant). The key is not reproduced here. Source: PROTO "Encryption"; REA "Costanti".
- The controller does not ask the device for confirmation. OBSERVED. Source: REA section "Flusso", 4. Ripristino di fabbrica.
- The record is removed "when the first inform after the reset arrives". This is the report's wording. It does not match the immediate removal of section 3 for a disconnected device, so which path applies is UNVERIFIED. Source: REA section "Flusso", 4 and 3.
- SSH path: `/usr/bin/syswrapper.sh restore-default`. OBSERVED. Source: REA "Costanti" (n.5 class_18); PROTO "Adoption" ("Other SSH commands present").
- Which UI action uses the SSH `restore-default` path is UNVERIFIED. Source: REA section "Non verificato".
- Controller-side reset: when `is_default` is set in `system.properties`, the controller clears its database at start and rebuilds it with initial settings. OBSERVED. Source: REA section "Flusso", 4 (n.19 DbService).
- `SystemService.restoreFactory` is named in INV ("Device lifecycle", Factory reset row) as OBSERVED. The REA text does not name it, so the name is taken from INV only. OBSERVED (INV). Source: INV "Device lifecycle".
- A confirmation step in the UI for the controller-side reset is UNVERIFIED. Source: REA section "Non verificato".

## 5. Data restore (`.unf` backup import)

- Upload route `/upload/backup` in `UploadServlet`. The file is unpacked into a temporary folder named `backup`. The entries `version` and `timestamp` must both exist; if one is missing the error is `api.err.InvalidBackup`. OBSERVED. Source: REA "Formati" (Upload del backup, n.13 UploadServlet).
- If the backup version differs from the controller version and is not listed in `migratable.versions`, the error is `api.err.InvalidBackupVersion`. The check is in `SystemService`, method `canMigrateFrom`. OBSERVED. Source: REA "Formati" (n.11 SystemService).
- The backup is a gzip archive with a stream of BSON documents. Each collection starts with a header document that has `__cmd` set to `select` and the collection name, then its documents, then one `__cmd` `index` document per index. OBSERVED. Source: REA "Formati" (Backup, n.19 DbService export and import); PROTO "Controller backups" (measured on real backups).
- Excluded from every backup: `cometmessage`, `system.indexes` and `system.profile`. Also excluded in a backup without statistics: `day`, `hour`, `quarterhour`, `minute`, `m2mgeneric`, `alarm` and `event`. OBSERVED. Source: REA "Formati" (Backup, n.19).
- The backup-creation command in `SystemService` is named in INV ("Device lifecycle", Data restore row) as OBSERVED. The method name is not in the REA text. OBSERVED (INV). Source: INV "Device lifecycle".
- The method that starts the restore after the upload is not found. UNVERIFIED. Source: REA section "Non verificato" and "Flusso", 5.
- The restore method in `DbService` drops the whole database, reads the BSON stream, empties each collection it lists, reinserts every document and then recreates the indexes. OBSERVED. Source: REA section "Flusso", 5 (n.19 DbService).
- The exact per-collection list restored is UNVERIFIED (the REA report did not check it). Source: REA section "Non verificato" (list of collections in the backup).
- Given the reinsert behaviour, a restored `device` record keeps its `name`, `x_authkey`, `port_cfg` and `device_cfg`, and the sensor and rule collections the backup contains come back too. INFERRED from the reinsert behaviour. Source: REA section "Flusso", 5.
- After start every loaded device has state 0 and `adopted` true, and its ports show as "NONE" until they are linked to sensors again. OBSERVED. Source: REA section "Flusso", 5 (n.3 DeviceManager, initialization).
- The next inform of a restored device, signed with the stored `x_authkey`, should bring it back to state 1. INFERRED from sections 1 and 6. Source: REA section "Flusso", 1 (step 3) and 6.
- When the stored database version differs from the controller version at start, the `DbMigrator` runs. OBSERVED. Source: REA "Rami di versione" (n.19 DbService, DbMigrator).

## 6. Reboot, locate, disconnected, heartbeat missed and isolated states

- The `restart` command queues a Task of type `reboot` (no fields) and raises `EVT_AP_Restarted`. When the task is done, the record is reloaded from the database with state 0. OBSERVED. Source: REA section "Flusso", 6; PROTO "Commands to the device" (`_type: reboot`, none).
- A reboot seen from the uptime: if the uptime is lower than expected and below 300 s, the controller raises `EVT_AP_RestartedUnknown` and sends `setparam` with `port_cfg` and `device_cfg`. OBSERVED. Source: REA section "Flusso", 6; PROTO "Controller responses", row 6.
- `locate` on a connected device (state 1) queues a `cmd` task with `cmd` set to `locate` (no fields). OBSERVED. Source: REA section "Flusso", 6; PROTO "Commands to the device" (`cmd: locate`).
- `locate` on a device in state 2 calls the discovery module with the value 30. Its unit and effect are UNVERIFIED. Source: REA section "Flusso", 6 and "Non verificato".
- `locate` in other states does nothing. OBSERVED. Source: REA section "Flusso", 6.
- Every reply to a device without work is `noop` with an interval of 10 s. OBSERVED. Source: PROTO "Controller responses" (BYTECODE note on the noop interval).
- The stored next-heartbeat time (now + 10 s) and the "considered lost" time (about 60 s later) are reported by REA. PROTO gives now + 20 s and now + 60 s and calls them UNVERIFIED. Which values the controller uses is UNVERIFIED. Source: REA section "Flusso", 6; PROTO "Controller responses" (UNVERIFIED note).
- A housekeeping task (inner class `class_101` of `DeviceManager`) starts 1 s after startup and runs every 60 s. OBSERVED. Source: REA n.3 DeviceManager (class_101).
- State 1 with no inform for more than 40 s moves to state 6 (heartbeat missed). OBSERVED as read in REA. PROTO keeps the 40 s value UNVERIFIED on a device. Source: REA section "Flusso", 6; PROTO "Device states in the controller".
- States 1 and 6 with no inform for more than 120 s: `EVT_AP_Lost_Contact` is raised, the record is reloaded, `connected` becomes false and a "disconnected" notification is sent. OBSERVED. Source: REA section "Flusso", 6; PROTO "Device states in the controller" (120 s, OBSERVED).
- A device not adopted and silent for more than 120 s is removed from memory. OBSERVED. Source: REA section "Flusso", 6 (class_101).
- A device in state 2 silent for more than 60 s is removed from memory. OBSERVED. Source: REA section "Flusso", 6 (class_101).
- A device in state 0 that is adopted and has informed less than 120 s ago goes back to state 1. OBSERVED. Source: REA section "Flusso", 6 (class_101).
- A `state_expire` time that has passed sets the state to 0. OBSERVED. Source: REA section "Flusso", 6 (class_101).
- Timeouts per state: 4 (firmware upgrade) 180 s, 5 (configuration sent) 120 s, 7 (adopting) 120 s; states 0, 1, 2, 6 and 8 have no fixed timeout in the table. OBSERVED. Source: REA n.3 state table; PROTO "Device states in the controller".
- The state "isolated" does not appear in `DeviceManager` in the REA report. It is UNVERIFIED. Source: REA section "Non verificato"; PROTO "Device states in the controller" (no isolated state).

## Gaps in mfi-server

Each point compares these findings with `docs/PROTOCOL.md`. No edit to PROTO is made here (out of scope). The mfi-server code was not read in this ticket, so statements about it cite CHANGELOG.md.

- **Adoption, sections "Adoption" and "Device states in the controller".** PROTO covers the steps, the authkey generation, the unused `set-inform` and the SSH command. Missing from PROTO: the adopt command of the UI, the device record fields, the Token creation and the `EVT_AP_Adopted` order. OBSERVED. Source: REA section "Flusso", 1; PROTO "Adoption".
- **Adoption, device-side handling of a manual `set-inform`.** This is UNVERIFIED in both sources. Source: REA section "Non verificato"; PROTO "Adoption".
- **Authkey decryption order.** REA and PROTO disagree on the keys tried for a device with `x_prev_authkey` (see section 1). For mfi-server this remains UNVERIFIED until a device test. Source: REA section "Flusso", 1; PROTO "Encryption".
- **Re-adoption and cloud fields.** PROTO does not cover automatic re-adoption (`EVT_AP_AutoReadopted`), the cloud-field path, or the rule that builds the inform host. REA gives these as OBSERVED. Whether the fields reach the controller in a real inform is UNVERIFIED (PROTO open questions 10 and 16). Source: REA section "Flusso", 2; REA "Costanti" (n.9).
- **Re-pointing in mfi-server.** CHANGELOG 0.11.0 says mfi-server re-points adopted devices through the system `ssh` program. Whether it sends the same URL and the same command as the controller is UNVERIFIED in this ticket. Source: CHANGELOG.md (0.11.0); REA section "Flusso", 2.
- **Forget.** PROTO has the state 8 entry only, with no delete flow and no removal list. Missing: the queued `setdefault` for a connected device and the list of removed records. What mfi-server does on delete is not in the files read here: UNVERIFIED. Source: REA section "Flusso", 3; PROTO "Device states in the controller".
- **Factory reset, sections "Factory state" and "Commands to the device".** PROTO covers the factory credentials, the IP address and the reset button, and lists `setdefault`. Missing: the effect of `setdefault` on the device, the SSH `restore-default` path, and the timing conflict of the removal record (UNVERIFIED). Source: REA section "Flusso", 4; PROTO "Factory state".
- **mfi-server policy.** CHANGELOG 0.3.0 states that mfi-server never sends a factory reset. This ticket does not change that. Source: CHANGELOG.md (0.3.0).
- **Restore, section "Controller backups".** PROTO covers the format and the key and does not describe the restore body. Missing: the collections excluded from a backup without statistics, the reinsert behaviour, and the state after restore (state 0, ports "NONE"). Whether mfi-server handles the missing `alarm` and `event` collections is UNVERIFIED. Source: REA "Formati" (Backup); REA section "Flusso", 5; CHANGELOG.md (0.3.0, `.unf` key import).
- **Reboot and locate, section "Commands to the device".** PROTO covers the `reboot` and `locate` commands. Missing: the 300 s reboot detection rule, the `EVT_AP_RestartedUnknown` event and the state reload after restart. Source: REA section "Flusso", 6; PROTO "Commands to the device".
- **Heartbeat values, section "Device states in the controller".** PROTO gives the 120 s rule as OBSERVED and calls the 40 s value UNVERIFIED. REA gives a 10 s noop interval, a 10 s next-heartbeat value and a 60 s lost value, which conflict with PROTO's 20 s and 60 s values. For mfi-server only the 120 s rule is OBSERVED. Source: REA section "Flusso", 6; PROTO "Controller responses" and "Device states in the controller".
- **States 2 and not-adopted devices.** A discovered device is kept in memory only, is removed after 60 s silent in state 2, and an unadopted device is removed after 120 s silent. None of this is in PROTO. Source: REA n.3 DeviceManager; REA section "Flusso", 6.
- **Isolated state.** Not confirmed in the controller code: UNVERIFIED. PROTO does not list it either. Source: REA section "Non verificato"; PROTO "Device states in the controller".
