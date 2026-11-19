# mPower outlets in the mFi Controller 2.1.11 (clean room report)

This is a clean-room report of the mPower family (codes P1U, P1E, P3U, P3E, P6E, P8U) in the mFi Controller 2.1.11 (`ace.jar`). It is built only from the repository documents `docs/PROTOCOL.md` (PROTO), `docs/controller/INVENTORY.md` (INV) and `docs/controller/device-lifecycle.md` (LIFE). It contains no controller code, no pseudocode and no decompiler output. Every fact has a status (OBSERVED, INFERRED or UNVERIFIED) and a source given by section, table or row name. Anything the documents do not state is UNVERIFIED. The `ace.jar` file and the `mfi-server` code were not read for this report, and nothing was verified on a device.

## 1. mPower models (variants)

- OBSERVED: the controller accepts the model codes P1U, P1E, P3U, P3E, P6E and P8U as mFi models. Source: PROTO "Devices" (accepted models list).
- OBSERVED: ports created at adoption: P1U and P1E 1; P3U and P3E 3; P6E 6; P8U 8. Source: PROTO "Devices" (model code table); INV "Products" (rows mPower mini, mPower and mPower PRO).
- INFERRED: P1E is the mPower mini EU and P3E is the mPower EU with 3 outlets, from device names in real backups. Source: PROTO "Devices" (commercial names paragraph).
- INFERRED: P6E is the mPower PRO EU (6 outlets) and P8U is the mPower PRO US (8 outlets), because the outlet counts match the official Quick Start Guides. Source: PROTO "Devices" (family table and commercial names paragraph).
- UNVERIFIED: the commercial name and region of P1U and P3U. The documents give only the codes. Source: PROTO "Devices"; INV "Products" (mPower mini and mPower rows, commercial name INFERRED).
- OBSERVED: every P model has an entry in the firmware archive table. Source: PROTO "Firmware archive" (10 models list).
- OBSERVED: every outlet of every P model is the same sensor type, "Outlet", with the same six measured quantities. The documents show no different outlet type per model. Source: PROTO "mPort and sensors (from ace.jar 2.1.11)", section 2 (row Outlet); INV "Products" (measures column).
- OBSERVED: the P models receive the outlet form of `port_cfg` (`vpower` lines), not the mPort lines. Source: PROTO "mPort and sensors (from ace.jar 2.1.11)", section 3; PROTO "Controller responses" (port_cfg for mPower).
- INFERRED: the P models use the network interface `eth1` in the system configuration, the other models `eth0`. The list is approximate in the source. Source: PROTO "Controller responses" (system_cfg paragraph).
- UNVERIFIED: whether P1U, P3U and P8U (without the E suffix) measure power on the device. The controller treats them like the E models, but no document shows a device test. Source: PROTO "Devices"; PROTO "Measurements".

## 2. Commands to an outlet (on/off, cycle)

- OBSERVED: the on/off command is `mfi-output`. It is queued as a task for the device. A new command for the same port replaces the old one. Source: PROTO "Commands to the device".
- OBSERVED: the command carries the MAC address, the outlet number `port`, the sensor id `sId`, the value `val` (1 = on, 0 = off) and the `timer` in seconds. Source: PROTO "Commands to the device" (fields list).
- INFERRED: the command may also carry `volt`, `off_volt`, `dimmer_level`, `dimmer_ramp`, `_id`, `device_id` and `datetime`, because the documents list them from the construction of the message. Source: PROTO "Commands to the device" (fields list, INFERRED from construction); PROTO "Open questions" item 3.
- OBSERVED: the command is delivered as the response to the next inform, and only if the device was already connected (state 1). Source: PROTO "Commands to the device"; PROTO "Device states in the controller".
- OBSERVED: the command is deleted after it is sent, with no acknowledgement. The wanted value stays in `configed_val` until a later inform reports the same value in the alarm list. Source: PROTO "Commands to the device".
- UNVERIFIED: whether the controller resends a command whose value the device never confirms. No document describes a retry. Source: PROTO "Commands to the device".
- OBSERVED: for M2M the port number becomes 2*(port-1) plus the output port. The documents give no port mapping for P models. Source: PROTO "Commands to the device" (M2M rule).
- UNVERIFIED: the port number used for a P model outlet in the command. Source: PROTO "Commands to the device".
- UNVERIFIED: a cycle command (switch off and on in one step). The documents list no such command. The command table lists only `mfi-output` for switching, and the report found no new command to the device. Source: PROTO "Commands to the device"; PROTO "Device configuration (setparam)" (last paragraph).
- UNVERIFIED: what the `timer` field does: a delay before the switch, a timed pulse, or a cycle. The documents say only that it is in seconds and defaults to 0. Source: PROTO "Device configuration (setparam)" (timer paragraph).

## 3. Per-outlet settings (lock, power-on state, timer, thresholds)

For each setting the status says whether the value goes to the device (setparam or command) or stays in the controller.

- OBSERVED: the lock is the field `output_lock` of the outlet's sensor record. It goes to the device as `lock` in the outlet's entry of `port_cfg`, sent with setparam. Source: PROTO "Device configuration (setparam)" (lock comes from output_lock); PROTO "Controller responses" (port_cfg for mPower, lock key).
- INFERRED: a lock change changes `port_cfg`, which changes `portversion`, so the configuration is sent again. Source: PROTO "Device configuration (setparam)" (change listener: a change of port_cfg changes portversion).
- OBSERVED: the rule action `relaySwitch` does nothing when the sensor has `output_lock` equal to 1. This is a controller-side use of the lock. Source: PROTO "Rules and scenes" (rule action handler, relaySwitch).
- INFERRED: the power-on state. The relay and output values sent with setparam come from `configed_val` when it exists, otherwise from `output_val`. The documents show no field named for power-on, and this was not tested on a device. Goes to the device: yes. Source: PROTO "Device configuration (setparam)" (power-on paragraph, INFERRED).
- UNVERIFIED: whether the device keeps its own power-on setting after a power loss. Source: PROTO "Controller responses" (reboot row sends setparam again).
- OBSERVED: the `timer` field of `mfi-output`, in seconds, default 0. It goes to the device as part of the command. Source: PROTO "Device configuration (setparam)" (timer paragraph); PROTO "Commands to the device".
- UNVERIFIED: whether the global setting `outputTimer` (default 0) reaches the device or stays in the controller. Source: PROTO "Device configuration (setparam)".
- OBSERVED: thresholds are conditions in the controller's rulesets (compare greater, equal or less, duration in minutes). They stay in the controller and do not reach the device. Source: PROTO "Rules and scenes" (conditions); PROTO "Device configuration (setparam)" (last paragraph).
- OBSERVED: the energy base of an outlet (the total before a counter reset) is kept by the controller. Source: PROTO "Measurements" (energy_sum bullet, base).

## 4. Measurements

- OBSERVED: each outlet reports the tags `output` (0 or 1, relay state), `active_pwr` (W), `v_rms` (V), `i_rms` (A), `pf` (power factor, no unit given) and `energy_sum` (Wh, cumulative). Source: PROTO "Measurements" (tag table).
- OBSERVED: the controller sends the report flags `rep_output`, `rep_pf`, `rep_energy_sum`, `rep_v_rms`, `rep_i_rms` and `rep_active_pwr` for each outlet, and the device reports only the quantities whose flag is 1. Source: PROTO "Controller responses" (port_cfg for mPower); PROTO "Device configuration (setparam)".
- OBSERVED: measurements arrive in the alarm list with `sId`, `tag`, `type`, `val` and `time` (milliseconds; 0 means controller time). Source: PROTO "Measurements".
- OBSERVED: when a new `energy_sum` value is below 0.9 times the last one, the controller treats the counter as reset and adds the old value to a base. Source: PROTO "Measurements" (energy_sum bullet).
- OBSERVED: increases of `energy_sum` above 0.001 Wh per millisecond are discarded. Source: PROTO "Measurements" (energy_sum bullet).
- OBSERVED: `energy_sum` is saved twice, the second time as `raw_energy_sum`, and `output` is passed to the interface as `output_val`. Source: PROTO "mPort and sensors (from ace.jar 2.1.11)", section 1. The source describes general ingestion of alarm entries, so INFERRED for outlets.
- OBSERVED: aggregates of every numeric value are kept per minute, quarter hour, hour and day. Source: PROTO "Statistics" (aggregate collections).
- UNVERIFIED: how often an outlet sends its report. The noop interval of 10 s in PROTO "Controller responses" is the controller's reply interval, not a device report interval. Source: PROTO "Controller responses" (noop interval).
- UNVERIFIED: a manual counter reset for outlets. PROTO "Controller responses" names a `resetcounter` flag that makes the controller send `port_cfg`, but no document says which user action sets it or that it applies to outlets. Source: PROTO "Controller responses" (row 7).
- UNVERIFIED: a mains frequency measurement. The tag table has none. Source: PROTO "Measurements" (tag table).
- UNVERIFIED (third-party, not confirmed on our units): the energy counter of the mPower is kept in RAM and restarts from zero after a power loss. Source: PROTO "Measurements" (last bullet, public project).

## 5. LED and other device settings

- OBSERVED: the outlet label is the field `label` of the sensor record, sent as `port.N.label` in `port_cfg`. The default is "Outlet", the last 6 characters of the MAC without colons, and the port number. Source: PROTO "Device configuration (setparam)" (label bullet).
- OBSERVED: the device name is the field `name` of the device record. In `system_cfg` it becomes a host name with non-alphanumeric characters removed and at most 31 characters. Source: PROTO "Device configuration (setparam)" (ConfigService bullet).
- UNVERIFIED: an LED setting for the P models. The documents list no LED field for the outlet type. Searched: PROTO "Device configuration (setparam)", "Measurements", "Controller responses" and INV "Products". The only LED field in the documents is `led_brightness` of the in-wall dimmer IWD1U, which is not a P model. Source: INV "Products" (IWD1U row).
- UNVERIFIED: a report interval setting per model. Searched the same sections as above. Source: PROTO "Device configuration (setparam)"; PROTO "Measurements".
- OBSERVED: `dimmer_mode` is sent in `device_cfg` only for the IWD1U dimmer, not for P models. Source: PROTO "Device configuration (setparam)"; PROTO "mPort and sensors (from ace.jar 2.1.11)", section 3.
- OBSERVED: the `locate` command exists for every device and carries no fields. Source: PROTO "Commands to the device" (`cmd: locate`).
- UNVERIFIED: whether `locate` makes the LED of a P model blink. Source: PROTO "Commands to the device".
- OBSERVED: `reboot` is a separate command with no fields, and the upgrade command is separate too. Source: PROTO "Commands to the device".

## 6. What the controller UI shows or allows that mfi-server does not

The web interface of the 2.1.11 controller was not read for this report. The points below come from the functions the repository documents describe. Items the documents do not confirm are UNVERIFIED. The mfi-server code was not read either, so the comparison is with the documents only.

- OBSERVED: rulesets on a sensor value: a condition compares the value with a limit (greater, equal or less), for a duration in minutes, combined with all or any, on edge or level. Source: PROTO "Rules and scenes" (conditions).
- OBSERVED: rule actions have eight types: email, event, relaySwitch, script, state, url, scene and rule. Source: PROTO "Rules and scenes" (rule action handler).
- OBSERVED: time rules work on weekly intervals in the server time zone. Source: PROTO "Rules and scenes" (scheduler).
- OBSERVED: scenes group relaySwitch, script and url actions, and starting a scene raises `EVT_mFi_Action`. Source: PROTO "Rules and scenes" (scene); PROTO "Events".
- OBSERVED: a sensor rule raises the event `EVT_mFi_SensorRuleset`. Source: PROTO "Events" (rules table, SensorRuleset row).
- OBSERVED: e-mail is sent by the controller. Source: INV "Areas" (Events row); PROTO "Rules and scenes" (email action).
- OBSERVED: the statistics read chooses the aggregate by interval length, with intervals capped at 3 years. Source: PROTO "Statistics".
- UNVERIFIED: whether the UI exposes the per-outlet `timer` and the global `outputTimer`. The documents name the fields, not the screens. Source: PROTO "Device configuration (setparam)"; INV "Areas" (Maps and dashboard, ui.md, INFERRED).
- UNVERIFIED: whether the UI shows the energy base and offers a manual reset. Source: PROTO "Measurements".
- UNVERIFIED: whether the UI can set an explicit power-on state. No field is documented. Source: PROTO "Device configuration (setparam)".

## Gaps in mfi-server

Each point compares these findings with PROTO "Devices", "Commands to the device", "Measurements" and "Device configuration (setparam)", as firmware.md does. No edit to PROTO is made here (out of scope).

- UNVERIFIED: a cycle command (switch off and on in one step). No document names one. Source: PROTO "Commands to the device".
- UNVERIFIED: the meaning of `timer` (delay, pulse or cycle), and whether the global `outputTimer` reaches the device. Source: PROTO "Device configuration (setparam)".
- UNVERIFIED: the power-on state rule (`configed_val`, then `output_val`), which is INFERRED and not tested on a device. Source: PROTO "Device configuration (setparam)".
- UNVERIFIED: the report interval of an outlet. Source: PROTO "Controller responses" (noop interval is controller side).
- UNVERIFIED: a device-side energy counter reset, and whether a manual reset exists for outlets; the meaning of the `resetcounter` flag. Source: PROTO "Controller responses" (row 7); PROTO "Measurements".
- UNVERIFIED: LED control and the effect of `locate` on P models. Source: PROTO "Device configuration (setparam)"; INV "Products".
- UNVERIFIED: whether P1U, P3U and P8U measure power on the device. Source: PROTO "Devices"; PROTO "Measurements".
- UNVERIFIED: the port number of P model outlets in `mfi-output`; only the M2M mapping is documented. Source: PROTO "Commands to the device".
- UNVERIFIED: the optional fields of `mfi-output` (`volt`, `off_volt`, `_id`, `datetime`) for an outlet, and whether the device accepts them. Source: PROTO "Commands to the device"; PROTO "Open questions" item 3.
- UNVERIFIED: whether an unconfirmed command is resent. The documents describe no acknowledgement and no retry. Source: PROTO "Commands to the device".
- UNVERIFIED: the local control paths of the mPower (HTTP login and SSH relay path), taken from public projects and not confirmed on our units. Source: PROTO "Local control without a controller (mPower)".

Nothing in this report was verified on a device. Every statement comes from the three repository documents, and the controller code was not reread for it.
