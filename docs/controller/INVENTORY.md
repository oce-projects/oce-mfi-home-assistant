# ace.jar 2.1.11 inventory (clean room)

This is a clean-room inventory of `ace.jar` 2.1.11, built from the reverse-engineering report of epic T-MWMRQZYG. It records behaviour, class names, method names, field names and MongoDB collection names only. It contains no code and no pseudocode. Classes that were not opened have their area INFERRED from the name.

Counts: the report gives class counts per package that add up to 141 (com.ubnt.data 48, com.ubnt.service 41, com.ubnt.ace 22, com.ubiquiti.discovery 18, com.ubnt.net 12). The report does not list every obfuscated class one by one, so the Classes table below lists only the classes the report names. The other classes stay UNVERIFIED until the per-area epics open them with classi_java.

## Areas

| Area | What it does | Classes | MongoDB collections | In mfi-server | Detail doc | Status |
|---|---|---|---|---|---|---|
| Inform and devices | Receives inform packets, chooses the response, keeps device state and the command queue | InformServlet, DeviceManager, ConfigService, Device record, Task, class_6, class_39, net.class_3/5/63/69 | device (OBSERVED from the PROTOCOL device collection); task (name confirmed by REA, see device-lifecycle.md §3) | partial | device-lifecycle.md | OBSERVED |
| Discovery | UDP discovery on port 10001: TLV announcements and replies | com.ubiquiti.discovery.* (18), UbntDiscoveryServer, DatagramQueryServer, LiteStationQueryServer, class_4 | none found | yes | network-tools.md | OBSERVED |
| Sensors and mPort | Reads measurements and new sensors from the inform, sensor model table | sensor service (ooOO.class_13), class_46, Sensor, CustomSensors, M2mgeneric, TagMapping, SensorTagMapping | sensor, m2mgeneric | no | mport.md | OBSERVED |
| Rules and scenes | Rules engine: triggers, conditions, actions, time rules, scenes, scripts | service.D class_31, class_32, class_33, class_34, class_35, class_30, class_27, class_15, Ruleset, Scene, Script | rule, ruleset, ruleaction, rulestate, rulestatecalendar, ruleschedule, rulecondition, scene, sceneaction, script | partial | ../PROTOCOL.md | OBSERVED |
| Events | Saves device events and rule actions, sends e-mail | EventManager, event.class_26 (e-mail), Event, ActionEvent | event, actionevent, alarmdef | no | ../PROTOCOL.md | OBSERVED |
| Statistics | Minute, quarter-hour, hour and day aggregates, read by interval length | Minute, Quarterhour, Hour, Stat, Rawdata | minute, quarterhour, hour, day, m2mgeneric | partial | ../PROTOCOL.md | INFERRED |
| Web API | HTTPS API (port 6443 INFERRED) under /api/v1.0/<verb>/<object> (cmd/devmgr for mfi-output and kick-serial, upd/sensor); login and session through AuthFilter (route and token UNVERIFIED); Comet long-poll live updates backed by the cometmessage capped collection; full report in web-api.md | ApiServlet, CometServlet, CometMessage, api.class_46, api.class_47, api.class_50, O0OO, oOOO | cometmessage (capped at 1,000,000 bytes) | partial | web-api.md | OBSERVED |
| Alarms | Alarm records and their definitions, monitor thread | Alarm, AlarmDef, Monitor | alarm, alarmdef | no | alarms.md | INFERRED |
| Users | Administrators, sessions, tokens, login filter, groups | User, Admin, Session, Token, AuthServer, Groups, AuthFilter | UNVERIFIED | partial | users.md | INFERRED |
| Maps and dashboard | Locations, geofences, live view, widgets, templates | Location, Geofence (service.A.class_38), LiveView, Widget, Template, ConfigTemplate | map | no | ui.md | INFERRED |
| System | Service start, database and migration, backup and restore, upgrade check, settings | SystemService, DbService, DbMigrator, Setting, UploadServlet, DownloadServlet, StatusServlet, Launcher, LauncherUI, JspUtils, ServiceLocator, AppContext, class_12 (properties file), class_8 | setting (UNVERIFIED name) | partial | system.md | OBSERVED |
| Network and Wi-Fi | SSH and web shell, UPnP, guest access, Wi-Fi configuration | SshServlet, WebshellServlet, WebshellInputServlet, UpnpServlet, GuestServlet, WlanConf | none found | no | network-tools.md | INFERRED |

## Products

| Product | How the controller recognises the model | Functions (commands, settings, measures) | Status |
|---|---|---|---|
| mPower mini, codes P1U and P1E | The model field of the inform is looked up in the firmware table; discovery sets mfi=true | 1 outlet created at adoption; outlet measures output, pf, energy_sum, v_rms, i_rms, active_pwr; mfi-output | OBSERVED (codes); INFERRED (commercial name); See [mpower.md](mpower.md): full report available |
| mPower, codes P3U, P3E | Same as above | 3 outlets created at adoption; same measures and commands | OBSERVED (codes); INFERRED (commercial name); See [mpower.md](mpower.md): full report available |
| mPower PRO, codes P8U and P6E | Same as above | 8 outlets (P8U) or 6 outlets (P6E) at adoption; same measures and commands | OBSERVED (codes); INFERRED (commercial name); See [mpower.md](mpower.md): full report available |
| EM3 | Model code in the table of accepted models; 3 ports created at adoption | Product and functions not identified in the report | UNVERIFIED |
| EM24, THERM | Accepted models; no ports created at adoption; no firmware entry | Functions not read in the report | UNVERIFIED |
| mPort, code M2M | Model code; 3 ports created at adoption; firmware entry present | Sensor ports through port lines PWR, AI, DI and DO; mfi-output with port 2*(port-1) plus the output port | OBSERVED; See [mport.md](mport.md): full report available |
| mPort Serial, code M2S | Model code; 1 port created at adoption | Ports as M2M; serial configuration ser2net_cfg; kick-serial command | OBSERVED; See [mport-serial.md](mport-serial.md): full report available |
| In-wall outlet, code IWO2U | Model code; 2 ports created at adoption | Outlet measures; mfi-output | OBSERVED; See [in-wall.md](in-wall.md): full report available |
| In-wall dimmer, code IWD1U | Model code; 1 port created at adoption, dimmer_mode switch, dimmer_lock 0, led_brightness 255 | dimmer_lock_setting command, dimmer_level in mfi-output; measures as the outlet | OBSERVED; See [in-wall.md](in-wall.md): full report available |
| In-wall switch, code IWS1U | Accepted model; no ports at adoption; listed only in the port configuration list, not with mfi=true in discovery | Functions not read in the report | UNVERIFIED (functions not read); See [in-wall.md](in-wall.md): report available |
| mFi-MSW (wall motion) | Sensor model name in the sensor table of the system service | motion and tamper tags | OBSERVED; See [mport.md](mport.md): full report available |
| mFi-MSC (ceiling motion) | Sensor model name in the sensor table | motion and tamper tags | OBSERVED; See [mport.md](mport.md): full report available |
| mFi-CS (current) | Sensor model name in the sensor table | amps and ampHours tags; conversion xyz*100, maximum 120 | OBSERVED; See [mport.md](mport.md): full report available |
| mFi-DS (door or window) | Sensor model name in the sensor table | magnetic tag, inversion applied | OBSERVED; See [mport.md](mport.md): full report available |
| mFi-THS (temperature and humidity) | Sensor model name in the sensor table | temperature and degreeHours tags (conversion xyz*30 - 10); humidity tag (conversion xyz*50) | OBSERVED; See [mport.md](mport.md): full report available |
| Counter | Sensor name in the sensor table | counter tag | OBSERVED; See [mport.md](mport.md): full report available |
| Input Digital | Sensor name in the sensor table | input tag | OBSERVED; See [mport.md](mport.md): full report available |
| Input Analog | Sensor name in the sensor table | volts and voltSum tags, range -2 V to +2 V | OBSERVED; See [mport.md](mport.md): full report available |
| RTD (PT-100) | Sensor name in the sensor table | temperature tag | OBSERVED; See [mport.md](mport.md): full report available |
| Output 5v, Output 12v, Output 24v | Sensor names in the sensor table | output tag; the mapping of a port to these models is UNVERIFIED | OBSERVED; See [mport.md](mport.md): full report available |
| UVC PRO (to camera) | Sensor name in the sensor table | output tag | OBSERVED; See [mport.md](mport.md): full report available |
| Serial | Sensor name in the sensor table | no tags | OBSERVED; See [mport.md](mport.md): full report available |

## Device lifecycle

Full clean-room report: [device-lifecycle.md](device-lifecycle.md).

| Step | Class and method | Status |
|---|---|---|
| Adoption | DeviceManager, adopt command: opens an SSH session through UbntDiscoveryServer, runs the set-adopt syswrapper command, creates the Device, Token and ports, sets state 7 | OBSERVED |
| Firmware update | DeviceManager, inform response upgrade (firmware table); SystemService and Launcher for the controller itself; full report: [firmware.md](firmware.md) | OBSERVED |
| Forget | DeviceManager, delete-ap command: sends setdefault to a connected device, then removes Device, Alarm, Event, Token, Task and the ap statistics | OBSERVED |
| Factory reset | DeviceManager, setdefault message for a device; SystemService.restoreFactory for the controller (DbService clears and rebuilds the database on start) | OBSERVED |
| Data restore | UploadServlet, route /upload/backup, checks the version and timestamp files; SystemService backup command creates the file; the restore body is UNVERIFIED | OBSERVED |
| Inform URL change | ConfigService writes the server URL key in the management configuration; the device receives it with setparam; the URL builder method is UNVERIFIED | OBSERVED |

## Classes

The report does not list every class one by one. This table lists only the classes the report names, and the package counts above give the totals. The other classes of ace.jar are not in this table and stay UNVERIFIED until the per-area epics open them with classi_java. When they are opened, their area is INFERRED from the name.

| Class | Package | Area | Status |
|---|---|---|---|
| InformServlet | com.ubnt.net | Inform and devices | OBSERVED |
| DeviceManager | UNVERIFIED | Inform and devices | OBSERVED |
| ConfigService | UNVERIFIED | Inform and devices | OBSERVED |
| Device record | UNVERIFIED | Inform and devices | OBSERVED |
| Task | UNVERIFIED | Inform and devices | OBSERVED |
| class_6 (listener interface) | UNVERIFIED | Inform and devices | INFERRED |
| class_39 (wake-up request, JSTUN) | com.ubnt.net | Inform and devices | OBSERVED |
| net.class_3 | com.ubnt.net | Inform and devices | INFERRED |
| net.class_5 | com.ubnt.net | Inform and devices | INFERRED |
| net.class_63 | com.ubnt.net | Inform and devices | INFERRED |
| net.class_69 | com.ubnt.net | Inform and devices | INFERRED |
| com.ubiquiti.discovery.* (18 classes, not named one by one in the report) | com.ubiquiti.discovery | Discovery | INFERRED |
| UbntDiscoveryServer | com.ubnt.net | Discovery | OBSERVED |
| DatagramQueryServer | UNVERIFIED | Discovery | OBSERVED |
| LiteStationQueryServer | UNVERIFIED | Discovery | OBSERVED |
| class_4 (discovery interface; the report also mentions it under Inform) | com.ubnt.net | Discovery | INFERRED |
| sensor service (ooOO.class_13) | UNVERIFIED | Sensors and mPort | OBSERVED |
| class_46 (measurement ingestion) | UNVERIFIED | Sensors and mPort | OBSERVED |
| Sensor | UNVERIFIED | Sensors and mPort | INFERRED |
| CustomSensors | UNVERIFIED | Sensors and mPort | INFERRED |
| M2mgeneric | UNVERIFIED | Sensors and mPort | INFERRED |
| TagMapping | UNVERIFIED | Sensors and mPort | INFERRED |
| SensorTagMapping | UNVERIFIED | Sensors and mPort | INFERRED |
| service.D class_31 (rules engine) | com.ubnt.service | Rules and scenes | OBSERVED |
| class_32 (comparisons) | com.ubnt.service | Rules and scenes | OBSERVED |
| class_33 (rule actions) | com.ubnt.service | Rules and scenes | OBSERVED |
| class_34 (scenes) | com.ubnt.service | Rules and scenes | OBSERVED |
| class_35 (scheduler) | com.ubnt.service | Rules and scenes | OBSERVED |
| class_30 (URL action) | UNVERIFIED | Rules and scenes | OBSERVED |
| class_27 (script over telnet) | UNVERIFIED | Rules and scenes | OBSERVED |
| class_15 (template) | UNVERIFIED | Rules and scenes | INFERRED |
| Ruleset | UNVERIFIED | Rules and scenes | INFERRED |
| Scene | UNVERIFIED | Rules and scenes | INFERRED |
| Script | UNVERIFIED | Rules and scenes | INFERRED |
| EventManager | UNVERIFIED | Events | OBSERVED |
| event.class_26 (e-mail) | UNVERIFIED | Events | OBSERVED |
| Event | UNVERIFIED | Events | INFERRED |
| ActionEvent | UNVERIFIED | Events | INFERRED |
| Minute | UNVERIFIED | Statistics | INFERRED |
| Quarterhour | UNVERIFIED | Statistics | INFERRED |
| Hour | UNVERIFIED | Statistics | INFERRED |
| Stat | UNVERIFIED | Statistics | INFERRED |
| Rawdata | UNVERIFIED | Statistics | INFERRED |
| ApiServlet | UNVERIFIED | Web API | OBSERVED |
| CometServlet | UNVERIFIED | Web API | OBSERVED |
| CometMessage | UNVERIFIED | Web API | INFERRED |
| O0OO | UNVERIFIED | Web API | INFERRED |
| oOOO | UNVERIFIED | Web API | INFERRED |
| api.class_46 | UNVERIFIED | Web API | INFERRED |
| api.class_47 | UNVERIFIED | Web API | INFERRED |
| api.class_50 | UNVERIFIED | Web API | INFERRED |
| Alarm | UNVERIFIED | Alarms | INFERRED |
| AlarmDef | UNVERIFIED | Alarms | INFERRED |
| Monitor | UNVERIFIED | Alarms | INFERRED |
| User | UNVERIFIED | Users | INFERRED |
| Admin | UNVERIFIED | Users | INFERRED |
| Session | UNVERIFIED | Users | INFERRED |
| Token | UNVERIFIED | Users | INFERRED |
| AuthServer | UNVERIFIED | Users | INFERRED |
| Groups | UNVERIFIED | Users | INFERRED |
| AuthFilter | UNVERIFIED | Users | OBSERVED |
| Location | UNVERIFIED | Maps and dashboard | INFERRED |
| Geofence (service.A.class_38) | com.ubnt.service | Maps and dashboard | INFERRED |
| LiveView | UNVERIFIED | Maps and dashboard | INFERRED |
| Widget | UNVERIFIED | Maps and dashboard | INFERRED |
| Template | UNVERIFIED | Maps and dashboard | INFERRED |
| ConfigTemplate | UNVERIFIED | Maps and dashboard | INFERRED |
| SystemService | com.ubnt.service.system | System | OBSERVED |
| DbService | UNVERIFIED | System | OBSERVED |
| DbMigrator | UNVERIFIED | System | OBSERVED |
| Setting | UNVERIFIED | System | INFERRED |
| UploadServlet | UNVERIFIED | System | OBSERVED |
| DownloadServlet | UNVERIFIED | System | INFERRED |
| StatusServlet | UNVERIFIED | System | INFERRED |
| Launcher | com.ubnt.ace | System | OBSERVED |
| LauncherUI | com.ubnt.ace | System | INFERRED |
| JspUtils | UNVERIFIED | System | INFERRED |
| ServiceLocator | UNVERIFIED | System | INFERRED |
| AppContext | UNVERIFIED | System | INFERRED |
| class_12 (properties file) | UNVERIFIED | System | INFERRED |
| class_8 | UNVERIFIED | System | INFERRED |
| SshServlet | UNVERIFIED | Network and Wi-Fi | INFERRED |
| WebshellServlet | UNVERIFIED | Network and Wi-Fi | INFERRED |
| WebshellInputServlet | UNVERIFIED | Network and Wi-Fi | INFERRED |
| UpnpServlet | UNVERIFIED | Network and Wi-Fi | INFERRED |
| GuestServlet | UNVERIFIED | Network and Wi-Fi | INFERRED |
| WlanConf | UNVERIFIED | Network and Wi-Fi | INFERRED |
| class_37 | UNVERIFIED | unclassified: the report reads it but does not state its function | UNVERIFIED |
