# Alarms and monitors of the mFi Controller 2.1.11 (clean room report)

This is a clean-room report of the alarms, monitors and notifications of the mFi Controller 2.1.11 (`ace.jar`). It is built only from the repository documents `docs/PROTOCOL.md` (PROTO, sections "Events" and "Rules and scenes"), `docs/controller/INVENTORY.md` (INV) and `docs/ARCHITECTURE.md` (ARCH), plus the platform facts of `AGENTS.md`. It contains no code from `ace.jar`, no pseudocode and no decompiler output. Every fact has a status (OBSERVED, INFERRED or UNVERIFIED) and a source. Nothing in this report was verified on a device. Field names in backticks (for example `alarm`, `addr`) are data field names quoted from PROTO, not code.

## 1. Alarm types (`AlarmDef`): list, fields, who raises them

- OBSERVED: alarm records live in the MongoDB collection `alarm`; their definitions live in `alarmdef`. Source: PROTO "Events"; INV "Areas" (Events and Alarms rows).
- OBSERVED: when an event's `key` has a matching definition in `alarmdef`, the event creates or updates an `alarm` record. The alarm record fields named by the report are `archived`, `occurs` and `handled_*`. Source: PROTO "Events" (`DbService`).
- OBSERVED: the alarm definitions the controller creates at startup are `EVT_AP_DiscoveredPending`, `EVT_AP_RediscoveredPending`, `EVT_AP_Lost_Contact` (with a repeat set), `EVT_WU_AssocPending`, `EVT_WG_AssocPending` and `EVT_AD_UpdateAvailable`. Source: PROTO "Events" (`DbService`).
- OBSERVED: who raises each one. A new device found raises `EVT_AP_DiscoveredPending`; an adopted device informing again raises `EVT_AP_RediscoveredPending`; more than 120 seconds without an inform raises `EVT_AP_Lost_Contact`; a pending Wi-Fi association raises `EVT_WU_AssocPending` or `EVT_WG_AssocPending`. Source: PROTO "Events".
- UNVERIFIED: when `EVT_AD_UpdateAvailable` (firmware update available) is raised; its trigger is not in the classes the report read. Source: PROTO "Events".
- INFERRED: the four trigger categories -- device disconnected, sensor threshold, rule and system -- map as follows: device disconnected -> `EVT_AP_Lost_Contact`; sensor threshold -> handled by rules, not by an `alarmdef` (see section 5); rule -> a rule "event" action, saved in `actionevent` (see section 3); system -> discovery and firmware definitions (`DiscoveredPending`, `RediscoveredPending`, `AD_UpdateAvailable`). Source: PROTO "Events" and "Rules and scenes".
- UNVERIFIED: the complete field list of an `alarmdef` record (a repeat flag is OBSERVED only on `EVT_AP_Lost_Contact`; a level or text field is not in the repository documents). Source: PROTO "Events".

## 2. `Monitor`: what it watches, interval and fields

- INFERRED: INV lists a `Monitor` class in the Alarms area, described as a "monitor thread"; the whole Alarms area has status INFERRED in INV and no class of it was opened one by one. Source: INV "Areas" (Alarms row) and INV Classes table (`Monitor` INFERRED).
- OBSERVED (the documented contact-monitoring behaviour, which may or may not be the `Monitor` class): a device with no inform for more than 40 seconds is set to state 6; after more than 120 seconds the controller raises `EVT_AP_Lost_Contact`; the check timer runs every 60 seconds. Source: PROTO "Events" (`DeviceManager`).
- OBSERVED (the rule and time scheduler, a second periodic watcher): the time-rule job starts 20 seconds after startup and then runs every 5 seconds; a second job starts after 600 seconds and then runs every 60 seconds, checking the sensor rulesets whose `compare` is 2 and whose `duration` is above 0. Source: PROTO "Rules and scenes" (scheduler, inner class 35).
- UNVERIFIED: what the `Monitor` class itself watches, its exact interval and its fields; the Alarms area was not opened class by class in INV. Source: INV "Areas".

## 3. Notifications: channels, mail-server settings, message text, recipients

- OBSERVED: the e-mail channel is a rule action of `type` `email`. It is sent only when `enable` is true, to each valid address in `addr`, at most once per `minute` minutes (the time of the last send is kept in `last_time`). Source: PROTO "Rules and scenes".
- OBSERVED: a second outbound channel is the URL action, `type` `url`: with `enable` true it sends a POST whose body carries URL-encoded `rule`, `sensor` and `value` fields. Source: PROTO "Rules and scenes".
- OBSERVED: `addr` is a list of addresses used for the e-mail and URL actions. Source: PROTO "Rules and scenes".
- INFERRED: the Events class the report names as the e-mail sender is `event.class_26` ("sends e-mail"). Source: INV "Areas" (Events row).
- OBSERVED: the rule action `type` has eight values (`email`, `event`, `relaySwitch`, `script`, `state`, `url`, `scene`, `rule`). Source: PROTO "Rules and scenes".
- UNVERIFIED: no SMS or push channel was found; none of the eight `type` values is SMS or push. Source: PROTO "Rules and scenes".
- UNVERIFIED: the mail-server settings (SMTP host, port, authentication, sender address). INFERRED that a `Setting` record holds them (INV places `Setting` in the System area), but the repository documents do not name the fields. Source: INV "Areas" (System row, `Setting`).
- OBSERVED: the message text of an event comes from a resource file named `messages`, read in the system language under the event `key`; a name in curly brackets is replaced by the event field of the same name, and a missing key yields the key itself between two tildes. UNVERIFIED: the texts themselves, because the `messages` file is not in the code and could not be read. Source: PROTO "Events".
- OBSERVED: the recipients of the e-mail channel are the addresses in the `addr` list of the rule action. UNVERIFIED: whether administrators receive a copy by default; not in the repository documents. Source: PROTO "Rules and scenes".

## 4. Alarm lifecycle: creation, acknowledge (archive/ack), deletion, collection and retention

- OBSERVED: creation. An event whose `key` matches an `alarmdef` creates or updates an `alarm`. Source: PROTO "Events" (`DbService`).
- OBSERVED: the alarm record carries `archived`, `occurs` and `handled_*`. INFERRED from the names: `archived` marks the archive/acknowledge state, `occurs` counts occurrences, and `handled_*` records the handling (who or when). Source: PROTO "Events" (fields OBSERVED; meaning INFERRED).
- OBSERVED: the MongoDB collection is `alarm`. Source: PROTO "Events"; INV "Areas".
- OBSERVED: when a device is forgotten, its `Alarm` records are removed together with its `Device`, `Event`, `Token`, `Task` and the ap statistics. Source: INV "Device lifecycle" (Forget row).
- UNVERIFIED: an explicit delete-one or clear-all route for alarms; not named in the repository documents. Source: INV "Areas".
- UNVERIFIED: how long an alarm is kept. An index on `ttl_time` exists for `alarm` (one of eight collections with such an index), created without an explicit expiry time, and no deletion job was found in the classes the report read. So it is not verified that old alarms are removed. Source: PROTO "Statistics" (ttl index note) and "Rules and scenes".

## 5. Link with events and rules

The events and the rule engine are already documented. This section only points to them and states what this report adds; it does not duplicate them.

- Already in PROTO "Events": events saved to `event`, rule and scene actions to `actionevent`, alarms to `alarm`; the event fields (`datetime`, `ttl_time`, `key`, `msg`, and caller fields such as `ap`, `sId`, `admin`); the `alarmdef` mapping; the `EVT_*` key table; the `messages` localization. See PROTO "Events".
- Already in PROTO "Rules and scenes": the `ruleaction` type values (including `email` and `url`), the `minute` throttle, the `addr` list, scenes, time rules and the scheduler intervals. See PROTO "Rules and scenes".
- OBSERVED: a sensor threshold is a rule, not an `alarmdef`. A `ruleset` condition holds `trigger` (`sensor`, `state` or `time`), `compare`, `limit` and `duration`; a rule "event" action saves an event (level 2 when `alert` is true). No separate `alarmdef` for a sensor threshold was found. Source: PROTO "Rules and scenes" and "Events".
- What this report adds over PROTO: the alarm-record view of that data gathered in one place (the lifecycle fields `archived`/`occurs`/`handled_*`, the startup `alarmdef` set, the Monitor area and the notification channels).

## Gaps in mfi-server

The mfi-server code was not read for this report; the comparison is with INV and ARCH only.

- INFERRED: mfi-server has no alarm or alarmdef model; INV marks the Alarms area "In mfi-server: no". Source: INV "Areas".
- INFERRED: mfi-server automations use the Home Assistant format with its own clean-room engine; the controller's `email` and `url` rule actions and its `alarmdef` definitions are not implemented. Source: ARCH "Decisions" (2026-11-16); INV "Areas".
- INFERRED: mfi-server has no SMTP or push notification channel of its own; it exposes its data over MQTT and lets Home Assistant raise notifications. Source: ARCH "Decisions" (2026-11-15, MQTT discovery).
- UNVERIFIED: the behaviour of the Home Assistant core `mfi` integration (`mficlient`) against an alarm API; mfi-server does not expose the controller `alarm`/`alarmdef` collections or an archive/ack route, so the controller alarm UI is not reproduced. Source: INV "Areas"; AGENTS.md "Facts".
