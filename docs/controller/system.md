# Backup, restore, database, settings, upload and download, and startup of the mFi Controller 2.1.11 (clean room report)

This is a clean-room report of the system area of the mFi Controller 2.1.11 (`ace.jar`): backup and restore, database and migrations, settings, upload and download, and startup. It is built only from the repository documents `docs/controller/INVENTORY.md` (INV), `docs/PROTOCOL.md` (PROTO), `docs/ARCHITECTURE.md` (ARCH), `mfi-server/DOCS.md` (DOCS) and `AGENTS.md` (AGENTS). It also uses the reverse engineering report quoted in the ticket (REA). REA is an input to this report, not a repository document. The report contains no code from `ace.jar`, no pseudocode and no decompiler output. In this report OBSERVED means stated in the source documents, not read directly from `ace.jar`. Nothing here was verified on a device. A REA finding that no repository document confirms is marked UNVERIFIED. Keys, passwords, authentication keys and backup contents are not reproduced here, and no real MAC address, e-mail address or private IP address is included.

## 1. Backup: contents, format, automatic copies

- A backup is a file named after the controller version with the `.unf` extension. The file name pattern comes from REA. Whether this is the exact name written by the controller is not in the repository documents. UNVERIFIED. Source: REA report, backup section.
- The `.unf` format is a ZIP archive with the entries `db.gz`, `format`, `timestamp` and `version`, encrypted as a whole. Its details are in PROTO, section "Controller backups (.unf)". OBSERVED. Source: PROTO "Controller backups (.unf)".
- The outer encryption is AES-128 in CBC mode with a fixed key and IV. The key and IV are not reproduced here. OBSERVED. Source: PROTO "Controller backups (.unf)".
- The padding mode used for the outer encryption is not in the repository documents. REA reports no padding. UNVERIFIED. Source: REA report, backup section.
- The `format` entry carries a format marker. REA reads its value as a fixed text. The value is not in the repository documents. UNVERIFIED. Source: REA report, backup section; PROTO "Controller backups (.unf)".
- The `timestamp` entry holds the backup time in milliseconds since 1970, as text. UNVERIFIED. Source: REA report, backup section.
- The `version` entry holds the controller version that wrote the backup. OBSERVED. Source: PROTO "Controller backups (.unf)".
- The `db.gz` entry is a gzip stream of MongoDB BSON documents. Each collection starts with a marker document that names the collection, followed by the documents of that collection. OBSERVED. Source: PROTO "Controller backups (.unf)".
- After the documents of a collection, REA reports one document per index of that collection. The index documents are not described in the repository documents. UNVERIFIED. Source: REA report, backup section.
- REA reports that the message collection with a fixed size (`cometmessage`) and the system index and profile collections are always left out of a backup. The repository documents do not confirm this. UNVERIFIED. Source: REA report, backup section; INV "Areas" (Web API row, `cometmessage` capped collection).
- REA reports that a backup started less than 60 seconds after the previous start time skips the high-volume statistics and alarm collections, and that otherwise the time-indexed statistics collections export only records newer than the start time. The repository documents do not confirm this. UNVERIFIED. Source: REA report, backup section.
- REA reports a second backup format, a copy of the database folder, that is disabled for writing by a constant. The repository documents do not mention it. UNVERIFIED. Source: REA report, backup section.
- REA reports that a backup file is not stored with system settings, the keystore or firmware files. The repository documents do not confirm this. UNVERIFIED. Source: REA report, backup section.
- REA reports that the backup metadata has one entry per controller version, and that a second backup of the same version overwrites the first. The repository documents do not confirm this. UNVERIFIED. Source: REA report, backup section.
- Automatic backups: REA found no scheduled backup in the classes it read. Its timers are an update check every 60 seconds and a daily monitor. The number of automatic backups kept is not in the repository documents. UNVERIFIED. Source: REA report, backup section; INV "Areas" (System row).
- The backup file contains device keys. Backups never enter the repository. OBSERVED. Source: PROTO "Controller backups (.unf)"; AGENTS hard rule 2.

## 2. Restore: steps, what is overwritten, adopted devices

- A backup is restored by uploading it to the route `/upload/backup`, which the controller handles in the upload servlet. The upload servlet checks the `version` and `timestamp` entries. OBSERVED. Source: INV "Areas" (System row, UploadServlet class) and INV "Device lifecycle" (Data restore row).
- The restore body, that is the steps after the check, is not described in the repository documents. UNVERIFIED. Source: INV "Device lifecycle" (Data restore row, "the restore body is UNVERIFIED").
- REA reports two error names for a backup that fails the check, one for an invalid backup and one for an invalid version. The repository documents do not confirm them. UNVERIFIED. Source: REA report, restore section.
- REA reports that a backup is accepted when its version equals the running version or appears in a list of migratable versions in the product properties file. The content of that list was not read. UNVERIFIED. Source: REA report, restore section.
- REA reports that the restore deletes the whole database before it reads the backup file, and that a read error is only logged. A damaged backup could therefore leave a partial database. This finding is not confirmed by the repository documents and must not be relied on until a test on a copy of the controller. UNVERIFIED. Source: REA report, restore section.
- REA reports that the restore rebuilds each collection from the file: it empties each collection, recreates each index and inserts the documents. The repository documents do not confirm this. UNVERIFIED. Source: REA report, restore section.
- REA reports that the default-state flag of the controller is cleared when the system was in the default state before the restore. UNVERIFIED. Source: REA report, restore section.
- REA reports that the restore writes a restart marker, after which the launcher stops the server, waits five seconds and starts it again. The launcher class is in the repository documents; the restart sequence is not. UNVERIFIED for the sequence; the launcher class `com.ubnt.ace.Launcher` is OBSERVED. Source: REA report, restore section; AGENTS "Facts you can rely on" (classes row).
- REA reports that the system properties file, the keystore, the controller identifier and the ports are not changed by a restore. UNVERIFIED. Source: REA report, restore section.
- Devices adopted at the time of the backup come back as they were in the backup, including their authentication keys. Keys are stored in the backup database, as PROTO states. The restore of keys into devices is UNVERIFIED. Source: REA report, restore section; PROTO "Controller backups (.unf)".
- A device adopted after the backup is not in the restored data. UNVERIFIED. Source: REA report, restore section.
- A device adopted by another controller is reset to factory settings when it talks to a controller that did not adopt it. OBSERVED. Source: PROTO "Adoption", item 2.
- Automatic re-adoption uses the controller administrator name and password. OBSERVED. Source: PROTO "Adoption", item 4.
- REA reports that the function that decides automatic re-adoption always returns true, and that its use was not read. UNVERIFIED. Source: REA report, restore section.

## 3. Database: collections, fields and migrations

- The controller stores its data in MongoDB, listening on 127.0.0.1 port 37017 only. OBSERVED. Source: AGENTS "Facts you can rely on" (MongoDB row).
- The MongoDB version is 2.4.10 in the tested container. Other versions are not verified. OBSERVED. Source: AGENTS "Facts you can rely on" (MongoDB row and "Not verified" line).
- The database name `ace` is given by REA. The repository documents do not name the database. UNVERIFIED. Source: REA report, database section.
- `device`: adopted devices, one record per device, with its name and its keys. The collection exists. OBSERVED. Source: INV "Areas" (Inform and devices row, `device` collection).
- `task`: commands queued for devices. OBSERVED. Source: INV "Areas" (Inform and devices row, `task` collection).
- `sensor`: sensor records of mPort ports, with `mac`, `port`, `model`, `label`, `calibration`, `output_val`, `configed_val`, `output_lock` and `tags`. OBSERVED. Source: PROTO "mPort and sensors (from ace.jar 2.1.11)", section 2.
- `m2mgeneric`: raw measurements, with `sId`, `tag`, `type`, `val`, `time` and `ttl_time`. OBSERVED. Source: PROTO "Statistics" (first bullet) and PROTO "mPort and sensors", section 1. PROTO writes the name with a capital letter; INV writes it in lower case. Which name the database uses is UNVERIFIED. Source: INV "Areas" (Sensors and mPort row); PROTO "mPort and sensors", section 1.
- `minute`, `quarterhour`, `hour`, `day`: aggregates for 60 s, 900 s, 3600 s and 86400 s, with `sId`, `tag`, `type`, `time`, `max`, `min`, `ave`, `size`, `last_val`, `last_val_time` and `ttl_time`. OBSERVED. Source: PROTO "Statistics" (second and fourth bullets).
- `event`: saved events, with `datetime`, `ttl_time`, `key` and `msg`. OBSERVED. Source: PROTO "Events" (second bullet).
- `actionevent`: actions of rules and scenes. OBSERVED. Source: PROTO "Events" (first bullet).
- `alarm`: alarm records with `archived`, `occurs` and `handled_*`. OBSERVED. Source: PROTO "Events" (third bullet).
- `alarmdef`: alarm definitions, created at startup for six event keys. OBSERVED. Source: PROTO "Events" (sixth bullet, alarm definitions).
- `rule`: rules, with `label`, `val` and `type`. OBSERVED. Source: PROTO "Rules and scenes" (first bullet).
- `ruleset`: conditions of a rule, with `rulesetId`, `trigger`, `sId`, `type`, `compare`, `limit`, `duration`, `enable`, `allorany`, `edgeorlevel` and `conditionset`. OBSERVED. Source: PROTO "Rules and scenes" (third bullet).
- `ruleaction`: actions of a rule, with `rulesetId`, `type`, `sId`, `val`, `timer`, `minute`, `addr`, `scriptId` and `stateId`. OBSERVED. Source: PROTO "Rules and scenes" (fifth bullet).
- `rulestate`: state of a time rule, with `val` and `lastRunTime`. OBSERVED. Source: PROTO "Rules and scenes" (time rules bullet).
- `rulestatecalendar`: time intervals of a time rule, with `trigger`, `stateId`, `start` and `end`. OBSERVED. Source: PROTO "Rules and scenes" (time rules bullet).
- `ruleschedule`: scheduled rules. The collection exists. OBSERVED. Source: PROTO "Rules and scenes" (first bullet). Its fields `stateId`, `time` and `tTag` come from REA only. UNVERIFIED. Source: REA report, database section.
- `rulecondition`: rule conditions. The collection exists. OBSERVED. Source: PROTO "Rules and scenes" (first bullet).
- `scene`, `sceneaction`: scenes and their actions. OBSERVED. Source: PROTO "Rules and scenes" (scene bullet).
- `script`: scripts run on devices. The collection exists. OBSERVED. Source: PROTO "Rules and scenes" (first bullet). Its fields are UNVERIFIED. Source: REA report, database section.
- `cometmessage`: capped collection of at most 1,000,000 bytes, used for live updates. OBSERVED. Source: INV "Areas" (Web API row).
- REA reports that `cometmessage` is emptied at every start of the controller. The repository documents do not confirm this. UNVERIFIED. Source: REA report, database section.
- `setting`: settings collection. Its name is UNVERIFIED. Source: INV "Areas" (System row, "setting (UNVERIFIED name)").
- `stat.<type>.<period>`: the pattern of the statistics collections for Wi-Fi, users and devices. The pattern is OBSERVED; the type and period values given by REA (delta, current, life; minute, hourly, daily, monthly) are UNVERIFIED. Source: PROTO "Statistics" (Stato bullet); REA report, database section.
- `action`: REA names a collection `action`. The repository documents do not name it. UNVERIFIED. Source: REA report, database section.
- `map`: the map collection. INV gives the name for the Maps area; REA reports a GridFS bucket named `map`. The GridFS form is UNVERIFIED. Source: INV "Areas" (Maps and dashboard row, INFERRED); REA report, database section.
- Other collections named by the data classes (`user`, `admin`, `session`, `token`, `widget`, `monitor`, `wlanconf`, `authserver`, `location`, `geofence`, `rawdata`, `groups`, `configtemplate`, `liveview`, `customsensors`): the names are the class names in lower case, as REA reports. INFERRED. Source: INV "Classes" table; REA report, database section.
- The indexes on the database: REA lists the key fields of event, alarm, device, user, session, setting, widget, token, monitor, the time-series collections and the schedule collections. The repository documents do not confirm these fields. UNVERIFIED. Source: REA report, database section.
- The indexes on `ttl_time` exist for `day`, `hour`, `quarterhour`, `minute`, `m2mgeneric`, `event`, `actionevent` and `alarm`, without an expiry time. OBSERVED. Source: PROTO "Statistics" (indexes bullet and the deletion-job bullet).
- DbMigrator: the class exists. OBSERVED. Source: INV "Classes" table (DbMigrator row).
- DbMigrator: REA reports that a version file in the database folder records the version written last. When it differs from the running version, the migration runs and the file is rewritten. A missing file is created without migration. UNVERIFIED. Source: REA report, migrations section.
- DbMigrator: REA reports one migration step, for stored versions 1.0.3 to 1.0.8, which removes the byte counters of user documents. REA found no migration for later versions. UNVERIFIED. Source: REA report, migrations section.
- Schema changes between the official versions 2.1.1 and 2.1.11 are not described in the repository documents. UNVERIFIED. Source: INV "Areas" (System row); AGENTS "Facts you can rely on" (versions row).
- Old data removal: PROTO found no deletion job in the classes it read. REA reports a command that deletes the documents without `ttl_time` in the collections listed above. How the command is run, and whether it runs by itself, is not confirmed. UNVERIFIED. Source: PROTO "Statistics" (deletion-job bullet); REA report, database section.

## 4. Settings

- The `setting` collection holds one document per setting key. The class `Setting` is INFERRED from its name, and its package is not confirmed. INFERRED. Source: INV "Classes" table (Setting row); INV "Areas" (System row).
- REA reports that the controller writes default settings at first start: identity name, UPnP, automatic upgrade (off), update check (on), syslog (off, port 514), background scan (interval 30), guest access, speed unit, temperature unit, e-mail (empty server and port), storage, six alarm definitions and a sample map. The repository documents do not confirm any of these defaults. UNVERIFIED. Source: REA report, settings section.
- `outputTimer` has the default 0. OBSERVED. Source: PROTO "Device configuration (setparam)" (the `mfi-output` timer bullet).
- `storage` has `enable` set to true and `ttl_time` set to 13. The default is OBSERVED. The unit of `ttl_time` is UNVERIFIED: the repository found no code that reads it. Source: PROTO "Statistics" (storage bullets).
- `timezone` is read by the time rules, with the field `zone` and the default `PST`. OBSERVED. Source: PROTO "Rules and scenes" (time rules bullet).
- The inform interval setting, if it exists, is not in the classes REA read. The interval the controller sends to devices in a no-operation response is 10 seconds, OBSERVED as a response rule; whether it is a setting is UNVERIFIED. Source: REA report, settings section; PROTO "Controller responses" (noop row).
- The inform port is the property `unifi.http.port` with the default 6080. OBSERVED. Source: PROTO "Transport" (first bullet).
- The HTTP port 6080 (inform), the HTTPS port 6443 (web interface) and the MongoDB port 37017 are configurable in `<mFi>/data/system.properties`. OBSERVED. Source: AGENTS "Facts you can rely on" (ports row and MongoDB row).
- A command in the controller writes any key into the system properties file. UNVERIFIED. Source: REA report, settings section.
- Changing timezone, syslog, country, guest access or WLAN settings changes the configuration version sent to devices. OBSERVED. Source: PROTO "Device configuration (setparam)" (change listener bullet).
- The e-mail settings are used by the e-mail event action; their keys and the server details are not in the repository documents. OBSERVED that e-mail is sent by an event action; the settings are UNVERIFIED. Source: PROTO "Events" (sixth bullet and the event table); INV "Areas" (Events row).
- Settings that concern devices, such as the inform interval, the ports seen by devices and the network settings, are not all named in the repository documents. The keys named by REA for device management (`mgmt.*`) are device configuration keys, not controller settings. UNVERIFIED. Source: REA report, settings section; PROTO "Device configuration (setparam)".

## 5. Upload and download

- Upload of a backup: route `/upload/backup`. OBSERVED. Source: INV "Device lifecycle" (Data restore row).
- The upload accepts the raw body with the file name and size in request headers, or a multipart body. The headers and the multipart form are REA findings. UNVERIFIED. Source: REA report, upload section.
- Upload of a map: multipart form with the map name, identifier and file name. UNVERIFIED. Source: REA report, upload section.
- Upload of a firmware file: REA did not observe it. UNVERIFIED. Source: REA report, upload section.
- Download of firmware: the path `/dl/firmware/` serves files under the firmware folder. The address form `http://<host>:<port>/dl/firmware/<path>` is OBSERVED in the upgrade message. Source: PROTO "Firmware archive" (upgrade message bullet); PROTO "Commands to the device" (upgrade row).
- Download of firmware: REA reports that the handler removes parent-directory segments and double slashes from the requested path. The repository documents do not confirm this. UNVERIFIED. Source: REA report, download section.
- Firmware table: the repository measured the controller's firmware table in the 2.1.11 package. It has 10 models, all at version 2.1.11.1309. OBSERVED (measured). Source: PROTO "Firmware archive" (MEASURED bullets).
- Firmware table: REA reports a fallback table with 13 models, all at version 2.0.7, used when the firmware table file is missing. This conflicts with the measured table above, and the two are not reconciled. The REA fallback is UNVERIFIED. Source: REA report, download section; PROTO "Firmware archive".
- Download of a backup: route `/dl/backup/<name>`. UNVERIFIED. Source: REA report, download section.
- Download of a support bundle: route `/dl/support`, with a file name built from the date and time. UNVERIFIED. Source: REA report, download section.
- Download of a map image: route `/file/map/<id>`, served from the GridFS store, with 404 when missing. UNVERIFIED. Source: REA report, download section.
- The authentication filter that protects these routes was not read by REA. UNVERIFIED. Source: INV "Areas" (Users row, AuthFilter UNVERIFIED route and token); REA report, download section.
- A status servlet exists in the System area. Its response fields are reported by REA only. The class is INFERRED. Source: INV "Classes" table (StatusServlet row); REA report, startup section.

## 6. Startup

- The controller starts through the launcher class `com.ubnt.ace.Launcher`. OBSERVED. Source: AGENTS "Facts you can rely on" (archive row).
- The controller requires Java 7. Java 8 broke the web interface of version 2.1.4 in user reports. OBSERVED. Source: AGENTS "Facts you can rely on" (Java row).
- The `start` command runs the web server in the same process. The `ui` command starts a child process with a maximum heap of 1024 MB. UNVERIFIED. Source: REA report, startup section; INV "Classes" table (LauncherUI row, INFERRED).
- Startup marker files in the controller folder: an interface lock, an interface wake-up file, a server restart file, a server upgrade file, a server going-down file and a database repair file. The list comes from REA. UNVERIFIED. Source: REA report, startup section.
- Before startup the controller checks five ports, with three attempts three seconds apart. The check is REA only. UNVERIFIED. Source: REA report, startup section.
- HTTP port 6080 for inform: OBSERVED. Source: AGENTS "Facts you can rely on" (ports row).
- HTTPS port 6443 for the web interface, since version 1.1.0: OBSERVED. Source: AGENTS "Facts you can rely on" (ports row).
- Shutdown port 6081, and portal ports 6880 and 6843: REA reports them as defaults. The repository documents do not confirm them. UNVERIFIED. Source: REA report, startup section.
- The database listens on 127.0.0.1 port 37017 only. OBSERVED. Source: AGENTS "Facts you can rely on" (MongoDB row).
- The database process is started with its data folder, its port, a log file, no HTTP interface, the loopback address and a journal option; if a repair marker exists, it runs a repair first. The options are REA findings. UNVERIFIED. Source: REA report, startup section.
- The status probe waits 400 ms per request and reports "taking too long" after 120 seconds without a response. UNVERIFIED. Source: REA report, startup section.
- The first start generates a controller identifier and creates a self-signed RSA 2048-bit certificate in the keystore, valid 3650 days. The keystore password is fixed in the code and is not reproduced here. UNVERIFIED. Source: REA report, startup section.
- If the default-state flag is set, the controller deletes the existing database and recreates it with the default settings at start. This is a REA finding; the repository documents do not confirm it. UNVERIFIED. Source: REA report, startup section.
- The update check contacts a vendor address at most once every 86400 seconds, and sends the controller version, identifier, platform and device count per model. An isolated network blocks this request. UNVERIFIED. Source: REA report, startup section; AGENTS hard rule 8.
- The controller upgrades itself through the system service; the firmware path for the controller itself is in the device lifecycle table. OBSERVED. Source: INV "Device lifecycle" (Firmware update row).
- The data-removal command and the `ttl_time` indexes are described in section 3. Whether `storage.ttl_time` controls the removal is UNVERIFIED. Source: PROTO "Statistics"; REA report, startup section.

## Gaps in mfi-server

The mfi-server code was not read for this report. The comparison uses DOCS, INV and ARCH only.

- Backup creation: mfi-server creates no backup of its own data. The routes table in DOCS lists no backup or restore route. OBSERVED. Source: DOCS "Web API" (routes table).
- Backup import: mfi-server only imports the device keys from a controller backup, at each start, and idempotently, with the `backup_file` option or the `import-backup` command. The import reads the file and keeps the keys in `devices.json` in the data folder. OBSERVED. Source: DOCS "Options" (backup_file row) and "Import the keys from a controller backup".
- Restore: mfi-server has no restore of its own data and no database drop-and-rebuild. OBSERVED. Source: DOCS "Web API" (routes table); DOCS "Options".
- Re-pointing: mfi-server re-points an adopted device over SSH and keeps the device key, so a device does not have to be reset. The controller restore path is different. OBSERVED. Source: DOCS "Adopting and re-pointing devices".
- Factory reset: mfi-server never sends a factory reset to a device. OBSERVED. Source: DOCS "Security" (list of rules: the server never sends a factory reset).
- Database: mfi-server stores history in sqlite3 for 30 days, and its devices, automations and settings in JSON files in the data folder. It does not use MongoDB. OBSERVED. Source: ARCH "Decisions" (2026-11-15 web API row); DOCS "Web API" (history paragraph) and "Automations".
- Retention: mfi-server keeps history for `history_days`, default 30. The controller's `storage.ttl_time` default is 13 with an unknown unit. The two are not comparable. OBSERVED. Source: DOCS "Run as a standalone program" (MFI_HISTORY_DAYS row); PROTO "Statistics" (storage bullets).
- Schema migrations: neither DOCS nor ARCH describes a database schema version or a migration. OBSERVED. Source: DOCS "Options" and "Run as a standalone program"; ARCH "Decisions".
- Settings: mfi-server reads its settings from environment variables, then from an optional `settings.json` file in the data folder, then from defaults. The controller uses a `setting` collection plus a system properties file. OBSERVED. Source: DOCS "Run as a standalone program" (variables table and precedence line); PROTO "Statistics" (storage bullets); AGENTS "Facts you can rely on" (ports row).
- Upload: mfi-server has no upload route in DOCS, and the backup file is read from the `/share` folder or from a path set in an option. OBSERVED. Source: DOCS "Options" (backup_file row); DOCS "Web API" (routes table).
- Download of firmware: mfi-server serves only the firmware paths of its own table, and returns 404 for any other path. OBSERVED. Source: DOCS "Firmware" (inform server paragraph).
- Firmware table: the mfi-server table covers the same 10 models at version 2.1.11.1309 that PROTO measured for the controller package. The REA fallback table with 13 models at 2.0.7 is not used by mfi-server. OBSERVED. Source: DOCS "Firmware" (table paragraph); PROTO "Firmware archive" (MEASURED bullets).
- Startup: mfi-server starts without a Java runtime, a database process or a system properties file. Its ports are set by environment variables or settings. OBSERVED. Source: DOCS "Run as a standalone program" (variables table); DOCS "Network" (ports table).
- HTTPS: mfi-server has no built-in HTTPS; remote access needs a reverse proxy with TLS. The controller serves its web interface over HTTPS on 6443. OBSERVED. Source: DOCS "Web API" (security warning); AGENTS "Facts you can rely on" (ports row).
- Update check: mfi-server does not contact a vendor update address according to DOCS. OBSERVED that DOCS does not describe such a request; the absence in the code is not checked. Source: DOCS (no update-check section); REA report, startup section.
- Architecture: ARCH has no decision about backup format, restore, database migrations or startup of the controller. OBSERVED. Source: ARCH "Decisions" (table).

## Open points

- Confirm the name and the case of the `m2mgeneric` collection (`m2mgeneric` in INV and REA; `M2mgeneric` in PROTO).
- Confirm the name of the settings collection (`setting` in REA; UNVERIFIED in INV).
- Confirm the unit of `storage.ttl_time` and whether the removal command runs on its own.
- Confirm the firmware fallback table: the measured table (10 models, 2.1.11.1309) against the REA fallback (13 models, 2.0.7).
- Confirm the restore body, including whether a failed read leaves a partial database.
- Confirm the list of migratable versions in the product properties file.
- Confirm the default-state behaviour at start, which can delete the database.
