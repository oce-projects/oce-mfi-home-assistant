# ace.jar 2.1.11 inventory (clean room)

This is a clean-room inventory of `ace.jar` 2.1.11, built from the reverse-engineering report of epic T-MWMRQZYG. It records behaviour, class names, method names, field names and MongoDB collection names only. It contains no code and no pseudocode. Classes that were not opened have their area INFERRED from the name. The report lists 140 class names as counts per package (ace 22, discovery 18, data 48, net 12, service 40), not 141, and gives service as 40 where the dossier gives 41. It does not list the classes one by one, so the Classes table below names only the classes the report mentions. The other classes are missing here and stay UNVERIFIED until a full list is available.

## Areas

| Area | What it does | Classes | MongoDB collections | In mfi-server | Detail doc | Status |
|---|---|---|---|---|---|---|
| Inform e dispositivi | Receives inform packets, chooses the response, keeps device state and the command queue | InformServlet, DeviceManager, ConfigService, Device, Task, class_6, class_39 (wake-up request), net.class_3/4/5/63/69 | device (OBSERVED from the PROTOCOL device collection); task (UNVERIFIED name) | partial | device-lifecycle.md | INFERRED |
| Discovery | UDP discovery on port 10001: TLV announcements and replies | com.ubiquiti.discovery.* (18), UbntDiscoveryServer, DatagramQueryServer, LiteStationQueryServer | none found | yes | network-tools.md | OBSERVED |
| Sensori e mPort | Reads measurements and new sensors from the inform, sensor model table | sensor service (ooOO.class_13), class_46, CustomSensors, M2mgeneric, TagMapping, SensorTagMapping | sensor, m2mgeneric | no | mport.md | INFERRED |
| Regole e scene | Rules engine: triggers, conditions, actions, time rules, scenes, scripts | service.D class_31, class_32, class_33, class_34, class_35, class_30, class_27, class_15 | rule, ruleset, ruleaction, rulestate, rulestatecalendar, ruleschedule, rulecondition, scene, sceneaction, script | partial | ../PROTOCOL.md | OBSERVED |
| Eventi | Saves device events and rule actions, sends e-mail | EventManager, event.class_26 (e-mail) | event, actionevent, alarmdef | no | ../PROTOCOL.md | OBSERVED |
| Statistiche | Minute, quarter-hour, hour and day aggregates, read by interval length | Minute, Quarterhour, Hour, Stat, Rawdata | minute, quarterhour, hour, day, m2mgeneric | partial | ../PROTOCOL.md | INFERRED |
| API web | HTTP API under /api/v1.0/<verb>/<object>, long-poll messages | ApiServlet, CometServlet, CometMessage, api.class_46, api.class_47, api.class_50, O0OO, oOOO | cometmessage (capped at 1,000,000 bytes) | partial | web-api.md | OBSERVED |
| Allarmi | Alarm records and their definitions, monitor thread | Alarm, AlarmDef, Monitor | alarm, alarmdef | no | alarms.md | INFERRED |
| Utenti | Administrators, sessions, tokens, login filter, groups | User, Admin, Session, Token, AuthServer, Groups, AuthFilter | UNVERIFIED | partial | users.md | INFERRED |
| Mappe e dashboard | Locations, geofences, live view, widgets, templates | Location, Geofence (service.A.class_38), LiveView, Widget, Template, ConfigTemplate | map | no | ui.md | INFERRED |
| Sistema | Service start, database and migration, backup and restore, upgrade check, settings | SystemService, DbService, DbMigrator, Setting, UploadServlet, DownloadServlet, StatusServlet, Launcher, LauncherUI, JspUtils, ServiceLocator, AppContext, class_12, class_8 | setting (UNVERIFIED name) | partial | system.md | OBSERVED |
| Rete e Wi-Fi | SSH and web shell, UPnP, guest access, Wi-Fi configuration | SshServlet, WebshellServlet, WebshellInputServlet, UpnpServlet, GuestServlet, WlanConf | none found | no | network-tools.md | INFERRED |

## Products

| Product | How the controller recognises the model | Functions (commands, settings, measures) | Status |
|---|---|---|---|
| mPower mini, codes P1U and P1E | The model field of the inform is looked up in the firmware table; discovery sets mfi=true | 1 outlet created at adoption; outlet measures output, pf, energy_sum, v_rms, i_rms, active_pwr; mfi-output | OBSERVED (codes); INFERRED (commercial name) |
| mPower, codes P3U, P3E | Same as above | 3 outlets created at adoption; same measures and commands | OBSERVED (codes); INFERRED (commercial name) |
| mPower PRO, codes P8U and P6E | Same as above | 8 outlets (P8U) or 6 outlets (P6E) at adoption; same measures and commands | OBSERVED (codes); INFERRED (commercial name) |
| EM3 | Model code in the table of accepted models; 3 ports created at adoption | Product and functions not identified in the report | UNVERIFIED |
| EM24, THERM | Accepted models; no ports created at adoption; no firmware entry | Functions not read in the report | UNVERIFIED |
| mPort, code M2M | Model code; 3 ports created at adoption; firmware entry present | Sensor ports through port lines PWR, AI, DI and DO; mfi-output with port 2*(port-1) plus the output port | OBSERVED |
| mPort Serial, code M2S | Model code; 1 port created at adoption | Ports as M2M; serial configuration ser2net_cfg; kick-serial command | OBSERVED |
| In-wall outlet, code IWO2U | Model code; 2 ports created at adoption | Outlet measures; mfi-output | OBSERVED |
| In-wall dimmer, code IWD1U | Model code; 1 port created at adoption, dimmer_mode switch, dimmer_lock 0, led_brightness 255 | dimmer_lock_setting command, dimmer_level in mfi-output; measures as the outlet | OBSERVED |
| In-wall switch, code IWS1U | Accepted model; no ports at adoption; listed only in the port configuration list, not with mfi=true in discovery | Functions not read in the report | UNVERIFIED |
| mFi-MSW (wall motion) | Sensor model name in the sensor table of the system service | motion and tamper tags | OBSERVED |
| mFi-MSC (ceiling motion) | Sensor model name in the sensor table | motion and tamper tags | OBSERVED |
| mFi-CS (current) | Sensor model name in the sensor table | amps and ampHours tags; conversion xyz*100, maximum 120 | OBSERVED |
| mFi-DS (door or window) | Sensor model name in the sensor table | magnetic tag, inversion applied | OBSERVED |
| mFi-THS (temperature and humidity) | Sensor model name in the sensor table | temperature and degreeHours tags (conversion xyz*30 - 10); humidity tag (conversion xyz*50) | OBSERVED |
| Counter | Sensor name in the sensor table | counter tag | OBSERVED |
| Input Digital | Sensor name in the sensor table | input tag | OBSERVED |
| Input Analog | Sensor name in the sensor table | volts and voltSum tags, range -2 V to +2 V | OBSERVED |
| RTD (PT-100) | Sensor name in the sensor table | temperature tag | OBSERVED |
| Output 5v, Output 12v, Output 24v | Sensor names in the sensor table | output tag; the mapping of a port to these models is UNVERIFIED | OBSERVED |
| UVC PRO (to camera) | Sensor name in the sensor table | output tag | OBSERVED |
| Serial | Sensor name in the sensor table | no tags | OBSERVED |

## Device lifecycle

| Step | Class and method | Status |
|---|---|---|
| Adoption | DeviceManager, adopt command: opens an SSH session through UbntDiscoveryServer, runs the set-adopt syswrapper command, creates the Device, Token and ports, sets state 7 | OBSERVED |
| Firmware update | DeviceManager, inform response upgrade (firmware table); SystemService and Launcher for the controller itself | OBSERVED |
| Forget | DeviceManager, delete-ap command: sends setdefault to a connected device, then removes Device, Alarm, Event, Token, Task and the ap statistics | OBSERVED |
| Factory reset | DeviceManager, setdefault message for a device; SystemService.restoreFactory for the controller (DbService clears and rebuilds the database on start) | OBSERVED |
| Data restore | UploadServlet, route /upload/backup, checks the version and timestamp files; SystemService backup command creates the file; the restore body is UNVERIFIED | OBSERVED |
| Inform URL change | ConfigService writes the server URL key in the management configuration; the device receives it with setparam; the URL builder method is UNVERIFIED | OBSERVED |

## Classes

Only the classes the report names are listed here. The other classes of ace.jar are not in the report; they are missing from this table and stay UNVERIFIED.

| Class | Package | Area | Status |
|---|---|---|---|
| InformServlet | com.ubnt.net | Inform e dispositivi | OBSERVED |
| DeviceManager | UNVERIFIED | Inform e dispositivi | OBSERVED |
| ConfigService | UNVERIFIED | Inform e dispositivi | OBSERVED |
| Device (record) | UNVERIFIED | Inform e dispositivi | OBSERVED |
| Task | UNVERIFIED | Inform e dispositivi | OBSERVED |
| class_6 (listener interface) | UNVERIFIED | Inform e dispositivi | INFERRED |
| class_39 (wake-up request, JSTUN) | com.ubnt.net (UNVERIFIED for this class) | Inform e dispositivi | OBSERVED |
| class_4 (discovery interface; the report also lists it under Inform) | UNVERIFIED | Discovery | UNVERIFIED |
| UbntDiscoveryServer | com.ubnt.net | Discovery | OBSERVED |
| DatagramQueryServer | UNVERIFIED | Discovery | OBSERVED |
| LiteStationQueryServer | UNVERIFIED | Discovery | OBSERVED |
| sensor service (ooOO.class_13) | UNVERIFIED | Sensori e mPort | OBSERVED |
| class_46 (measurement ingestion) | UNVERIFIED | Sensori e mPort | OBSERVED |
| M2mgeneric | UNVERIFIED | Sensori e mPort | INFERRED |
| service.D class_31 (rules engine) | com.ubnt.service (UNVERIFIED) | Regole e scene | OBSERVED |
| service.D class_32 (comparisons) | com.ubnt.service (UNVERIFIED) | Regole e scene | OBSERVED |
| service.D class_33 (rule actions) | com.ubnt.service (UNVERIFIED) | Regole e scene | OBSERVED |
| service.D class_34 (scenes) | com.ubnt.service (UNVERIFIED) | Regole e scene | OBSERVED |
| service.D class_35 (scheduler) | com.ubnt.service (UNVERIFIED) | Regole e scene | OBSERVED |
| class_30 (URL action) | UNVERIFIED | Regole e scene | OBSERVED |
| class_27 (script over telnet) | UNVERIFIED | Regole e scene | OBSERVED |
| class_15 (template) | UNVERIFIED | Regole e scene | INFERRED |
| class_37 | UNVERIFIED | unclassified: the report reads it but does not state its function | UNVERIFIED |
| EventManager | UNVERIFIED | Eventi | OBSERVED |
| event.class_26 (e-mail) | UNVERIFIED | Eventi | OBSERVED |
| Minute | UNVERIFIED | Statistiche | INFERRED |
| Quarterhour | UNVERIFIED | Statistiche | INFERRED |
| Hour | UNVERIFIED | Statistiche | INFERRED |
| ApiServlet | UNVERIFIED | API web | OBSERVED |
| CometServlet | UNVERIFIED | API web | OBSERVED |
| CometMessage | UNVERIFIED | API web | INFERRED |
| Alarm | UNVERIFIED | Allarmi | INFERRED |
| AlarmDef | UNVERIFIED | Allarmi | INFERRED |
| AuthFilter | UNVERIFIED | Utenti | OBSERVED |
| Token | UNVERIFIED | Utenti | INFERRED |
| Location | UNVERIFIED | Mappe e dashboard | INFERRED |
| Geofence (service.A.class_38) | com.ubnt.service (UNVERIFIED) | Mappe e dashboard | INFERRED |
| SystemService | com.ubnt.service.system | Sistema | OBSERVED |
| Launcher | com.ubnt.ace | Sistema | OBSERVED |
| DbService | UNVERIFIED | Sistema | OBSERVED |
| DbMigrator | UNVERIFIED | Sistema | OBSERVED |
| UploadServlet | UNVERIFIED | Sistema | OBSERVED |
| class_12 (properties file) | UNVERIFIED | Sistema | INFERRED |
| SshServlet | UNVERIFIED | Rete e Wi-Fi | INFERRED |
| UpnpServlet | UNVERIFIED | Rete e Wi-Fi | INFERRED |
