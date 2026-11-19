# Maps, locations, geofences, live view, widgets and templates of the mFi Controller 2.1.11 (clean room report)

This is a clean-room report of the maps and dashboard area of the mFi Controller 2.1.11 (`ace.jar`). It is built only from the repository documents `docs/controller/INVENTORY.md` (INV), `docs/PROTOCOL.md` (PROTO), `docs/ARCHITECTURE.md` (ARCH), `mfi-server/DOCS.md` (DOCS) and `AGENTS.md` (AGENTS). It also uses the reverse engineering report quoted in the ticket (REA). REA is an input to this report, not a repository document. The report contains no code from `ace.jar`, no pseudocode and no decompiler output. In this report OBSERVED means stated in the repository documents. Nothing here was verified on a device. A REA finding that no repository document confirms is marked UNVERIFIED. No GPS coordinate, IP address, MAC address or other real identifier is reproduced.

## 1. Location: what it represents, its fields, its links

- INV lists a class `Location` in the Maps and dashboard area. The whole area has status INFERRED, and no class of it was read one by one. INFERRED. Source: INV "Areas" (Maps and dashboard row) and INV Classes table.
- What a Location represents (a house, a room, or a map with a background image) is not in the repository documents. A search of PROTO, ARCH, DOCS and AGENTS found no description of locations. UNVERIFIED. Source: INV "Areas" (Maps and dashboard row).
- REA gives the MongoDB collection `location` for this class and one field path `loc`. The name `loc` probably refers to coordinates, but that is only the name. The collection and the field are not in the repository documents. UNVERIFIED. Source: REA report, class Location.
- INV lists the collection `map` for the whole area, not `location`. Which collection name is correct is UNVERIFIED. Source: INV "Areas" (Maps and dashboard row) compared with REA report, class Location.
- Whether a Location is linked to devices or sensors is not stated. REA found no such field. UNVERIFIED. Source: REA report, class Location.
- PROTO says that maps stay in the controller and are not sent to devices. OBSERVED. Source: PROTO "Device configuration (setparam)" ("Tags, maps and sensor.tags stay in the controller").

## 2. Geofence: what it does, what data it uses, its links

- INV lists `Geofence` with the class location `service.A.class_38` in package `com.ubnt.service`, status INFERRED. Source: INV "Areas" (Maps and dashboard row) and INV Classes table.
- REA places the class in package `com.ubnt.data`. This differs from INV, so the package of the class is UNVERIFIED. Source: REA report, class Geofence; INV Classes table.
- REA reports five fields for a geofence: an identifier (`geoid`), a label, a color, notes and a list of markers. The marker list accepts indexes 0 to 100, which gives at most 101 entries. REA reads the markers as polygon points, which is INFERRED from the name. All of these fields are UNVERIFIED in the repository documents. Source: REA report, class Geofence.
- REA reports that a device record accepts geofence entries with indexes 0 to 10, so at most 11 per device. UNVERIFIED. Source: REA report, class Device.
- What a geofence does (presence detection, alerts, automation) is not in the repository documents. REA found no link to rules or to users. The INV Rules and scenes row does not list a geofence class. UNVERIFIED. Source: REA report; INV "Areas" (Rules and scenes row).

## 3. LiveView and Widget

- INV lists the classes `LiveView` and `Widget` in the Maps and dashboard area, status INFERRED from the names. Source: INV "Areas" (Maps and dashboard row).
- REA gives the collections `liveview` and `widget` for these classes, and reports that neither class declares a field. The collection names are not in INV, which lists only `map`. UNVERIFIED. Source: REA report, classes LiveView and Widget; INV "Areas" (Maps and dashboard row).
- The widget types and the content they show are not in the repository documents. UNVERIFIED. Source: INV "Areas" (Maps and dashboard row).
- How widgets are saved for each user is not in the repository documents. The users report (`docs/controller/users.md`) does not describe per-user dashboard settings. UNVERIFIED. Source: INV "Areas" (Users row); docs/controller/users.md.

## 4. Template and ConfigTemplate

- INV lists the classes `Template` and `ConfigTemplate` in the Maps and dashboard area, status INFERRED. Source: INV "Areas" (Maps and dashboard row).
- INV also lists `class_15 (template)` in the Rules and scenes area, status INFERRED. Whether it is the same kind of object as the `Template` of this area is UNVERIFIED, because the names overlap. Source: INV Classes table (class_15 row, Rules and scenes) and INV Classes table (Template row, Maps and dashboard).
- REA reports that `ConfigTemplate` has three fields: `geoid`, `label` and `action`. Since `geoid` is the same identifier as in Geofence, a ConfigTemplate may be an action tied to a geofence. This is INFERRED from the shared field name. UNVERIFIED in the repository documents. Source: REA report, class ConfigTemplate.
- REA found no field path for `Template` and says it might be a generic model. Whether it is a configuration template or a page template is UNVERIFIED. Source: REA report, class Template.
- How a template is applied to a device is not in the repository documents. PROTO "Device configuration (setparam)" lists what the controller sends to a device, and it names no geofence or template field. It also says that outlet thresholds stay in the rulesets and do not reach the device. The application path of templates is UNVERIFIED. Source: PROTO "Device configuration (setparam)".

## 5. What the controller interface shows that the mfi-server page does not

- The area holds data for locations, geofences, live views, widgets and templates. INV marks the area as not present in mfi-server ("In mfi-server: no"). OBSERVED. Source: INV "Areas" (Maps and dashboard row).
- Which screens of the controller web interface show these data is UNVERIFIED. No repository document describes the controller web pages of this area. Source: INV "Areas" (Maps and dashboard row); DOCS "Web page".
- Whether a location map shows a background image is UNVERIFIED. No repository document describes it. Source: INV "Areas" (Maps and dashboard row).
- The detailed comparison with the mfi-server page is in the section below.

## Gaps in mfi-server

The mfi-server code was not read for this report. The comparison uses DOCS, INV and ARCH only.

- Location maps (with or without a background image): the controller has the class Location (INFERRED). mfi-server has no map view. OBSERVED. Source: DOCS "Web page" (list of what the page shows); INV "Areas" (Maps and dashboard row, "In mfi-server: no").
- Geofences: the controller has the class Geofence (INFERRED). mfi-server shows no geofence. OBSERVED. Source: DOCS "Web page"; INV "Areas" (Maps and dashboard row).
- Live view: the controller has the class LiveView (INFERRED). mfi-server has no live view page. OBSERVED. Source: DOCS "Web page"; INV "Areas" (Maps and dashboard row).
- Widgets that a user configures on a dashboard: the controller has the class Widget (INFERRED), and how widgets are saved per user is UNVERIFIED. mfi-server has one fixed page with a fixed list of items and no dashboard. OBSERVED. Source: DOCS "Web page" (the list of what the page shows); INV "Areas" (Maps and dashboard row).
- Configuration or page templates: the controller has the classes Template and ConfigTemplate (INFERRED). mfi-server has no template feature. The only rule-like feature of mfi-server is the automation engine, which is not a template. OBSERVED. Source: DOCS "Automations"; DOCS "Web page".
- Planned maps or dashboards: ARCH has no decision about maps, locations or dashboards. Its decision table has no such entry. OBSERVED. Source: ARCH "Decisions".
- Home Assistant entities come through MQTT discovery, so Home Assistant may provide the dashboards. This is INFERRED from ARCH and DOCS, not a recorded decision. Source: ARCH "Decisions" (2026-11-15, MQTT discovery row); DOCS "MQTT and Home Assistant".

## Open points

- Confirm the collection names (`location`, `geofence`, `liveview`, `widget`, `template`, `configtemplate` in REA; `map` in INV).
- Confirm the package and the class location of Geofence (`com.ubnt.data` in REA; `service.A.class_38` in INV).
- Confirm whether `Template` and `class_15 (template)` are the same kind of object.
- Confirm the meaning of each field and how widgets and templates are saved and applied. This needs a full read of the classes in a separate REA run, which this report does not do.
