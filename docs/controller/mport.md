# mPort M2M and sensors in the mFi Controller 2.1.11 (clean room report)

This is a clean-room report of the mPort M2M product (model code M2M) and of the sensor models of the mFi Controller 2.1.11 (`ace.jar`). It is built only from the repository documents `docs/PROTOCOL.md` (PROTO), `docs/controller/INVENTORY.md` (INV) and `docs/controller/device-lifecycle.md` (LIFE), and from the reverse-engineering report of ticket T-MWMRR4K2 (REA). REA cites controller classes by the output numbers of its run (U10, U12, U13, U15, U17, U19, U20). The report contains no code from `ace.jar`, no pseudocode and no decompiler output. Every fact has a status (OBSERVED, INFERRED or UNVERIFIED) and a source. Facts already stated in PROTO section "mPort and sensors (from ace.jar 2.1.11)" are referenced by section and are not copied. Nothing in this report was verified on a device.

## 1. Sensor types (code, tag, unit)

The tag, unit and conversion of each model are in PROTO section 2 (model table) and are not repeated here. This list gives the model names and their kind.

- OBSERVED: the sensor models are MSW (wall motion), MSC (ceiling motion), CS (current), DS (door or window), THS (temperature), THS Humidity (humidity), Counter, Input Digital, Input Analog, RTD (PT-100), Output 5v, Output 12v, Output 24v, UVC PRO (to camera) and Serial. Source: PROTO "mPort and sensors (from ace.jar 2.1.11)", section 2; REA, SystemService (U12).
- OBSERVED: the model names of the mPower outlets ("Outlet", "Dimmer Switch", "Dimmer") are not mPort sensors and are covered in mpower.md. Source: PROTO "mPort and sensors (from ace.jar 2.1.11)", section 2 (last row); INV "Products".
- INFERRED: the full name is the Ubiquiti prefix plus the product name, and REA reads the default product name as "mFi". The assignment of the prefix is not confirmed on the device side (PROTO keeps it UNVERIFIED). Source: REA, SystemService (U12); PROTO "mPort and sensors (from ace.jar 2.1.11)", section 2.
- OBSERVED: the model table gives the digital power of the inputs: the Input Digital model drives a 24 V output on its first channel and a 5 V output on its second channel. Source: REA, SystemService (U12).
- OBSERVED: the MSW model is powered at 12 V and has a 24 V output. The report gives no power value for MSC. Source: REA, SystemService (U12).
- OBSERVED: the precision values in the model table are CS 4, THS 2, Counter 0 and Input Analog 4. Source: REA, SystemService (U12).
- OBSERVED: the four output models (Output 5v, Output 12v, Output 24v and UVC PRO) have tag output, unit on/off and no inversion. Source: REA, SystemService (U12); PROTO "mPort and sensors (from ace.jar 2.1.11)", section 2.
- OBSERVED: the Serial model exists only for the M2S variant (serial mPort). Source: REA, SystemService (U12); INV "Products" (mPort Serial row).
- UNVERIFIED: the spelling "Output  5v" with two spaces in the REA text. INV writes "Output 5v" with one space. The report does not say which one the controller uses. Source: REA, SystemService (U12); INV "Products".
- UNVERIFIED: the power value of the MSC model. Searched: the model table of SystemService (U12). Source: REA, SystemService (U12).
- CONFIRMED (official guide): an mPort M2M gets 3 ports at adoption = 2 mFi RJ45 ports + 1 terminal block port. Source: QSG-MPORT specifications.
- CONFIRMED (official guide): the THS temperature conversion is V x 30 - 10. Source: UG-V11 p. 29.
- CONFIRMED (official guide): the CS current sensor reads 1 V = 100 A and is not TrueRMS. Source: UG-V11 p. 29; QSG-SENSORS.
- CONFIRMED (official guide): the RTD model is a PT-100 from -50 to +250 C. Source: UG-V11 p. 29.
- CONFIRMED (official guide): the Input Analog range is -2 to +2 V. Source: UG-V11 p. 29.
- CONFIRMED (official guide): the Output 5v, 12v and 24v models show an on/off button and can be a rule output. Source: UG-V11 p. 29.
- CONFIRMED (official guide): Ubiquiti sensors on the RJ45 ports are detected ("unconfigured sensor (detected)"); terminal block and third-party devices are not. Source: UG-V11 p. 29.

## 2. Sensor lifecycle (detected, type assignment, port_cfg, removal)

Detection, the 20 second removal of a detected sensor and the "unconfigured sensor" label are in PROTO section 7 and are not repeated.

- OBSERVED: at adoption an M2M device gets ports 1 to 3, each with model, label and mac set to NONE. Source: REA, DeviceManager (U15); PROTO "Devices" (model code table, 3 ports).
- OBSERVED: a detected sensor on a port is replaced when the user assigns a type to that port (add sensor). The user sends port, model and label. Source: PROTO "mPort and sensors (from ace.jar 2.1.11)", section 7; REA, sensor service (U13), step 4.
- OBSERVED: if another sensor is already linked to the same port, the controller unlinks it: its mac and port become NONE. Source: REA, sensor service (U13), step 4. This is not in PROTO section 7.
- OBSERVED: a model with an output gets output_val 1 when the sensor is created. Source: REA, sensor service (U13), step 5.
- OBSERVED: after an assignment the controller rewrites the port configuration of the device and sets new_config, so the configuration is sent again. Source: PROTO "mPort and sensors (from ace.jar 2.1.11)", section 7 (sets new_config); REA, sensor service (U13), step 6.
- OBSERVED: the port configuration of an mPort is written as the lines described in PROTO "mPort and sensors (from ace.jar 2.1.11)", section 3. REA adds that each used port gets the keys model, label and sensorId, and that the analog and digital keys include a func key. Source: PROTO "mPort and sensors (from ace.jar 2.1.11)", section 3; REA, ConfigService (U10), step 8 and step 9.
- OBSERVED: an empty port gets mode off. On the second channel of ports 1 and 2 the configuration sends a 5 V line. Source: REA, ConfigService (U10), step 9.
- OBSERVED: the cases that send a configuration to the device (cfgversion, portversion, reboot, new_config, counter reset) are listed in PROTO "mPort and sensors (from ace.jar 2.1.11)", section 3. Source: PROTO "mPort and sensors (from ace.jar 2.1.11)", section 3; REA, DeviceManager (U15).
- OBSERVED: removing a sensor runs in a background thread. It deletes the alarms, the events and the label mappings of the sensor, then the readings at minute, quarter hour, hour and day level, and finally the sensor record. Source: REA, sensor service (U13), step 10; LIFE section 3 (sensor records are kept after a device is forgotten).
- UNVERIFIED: whether the port configuration is rewritten after a sensor is removed. The report does not say. Searched: the sensor service (U13) and the configuration generator (U10). Source: REA, sensor service (U13), step 10.
- OBSERVED: a restored device starts with its ports showing NONE until the sensors are linked again. Source: LIFE section 5 (after restore); REA, DeviceManager (U15).

## 3. Calibration (offset, scale, CustomSensors)

- OBSERVED: each sensor has one calibration string. Its default is the identity placeholder. The string is written in the AI and DI sections of the port configuration. Source: PROTO "mPort and sensors (from ace.jar 2.1.11)", section 4; REA, ConfigService (U10) and sensor service (U13).
- OBSERVED: changing the calibration through the API saves the field, sets new_config and sends the configuration again. Source: PROTO "mPort and sensors (from ace.jar 2.1.11)", section 4 (upd/sensor action); REA, sensor service (U13).
- INFERRED: there are no separate offset and scale fields. The report read only the expression string of the calibration. Source: PROTO "mPort and sensors (from ace.jar 2.1.11)", section 4 (INFERRED); REA, sensor service (U13).
- OBSERVED: the conversion strings of the models (for example for CS and THS) are fixed in the model table and are not changed by the user. Source: PROTO "mPort and sensors (from ace.jar 2.1.11)", section 4; REA, SystemService (U12).
- OBSERVED: CustomSensors is a JSON text stored in the setting customSensors. The CustomSensors class itself has no fields. Source: REA, SystemService (U12).
- OBSERVED: at startup the controller reads the file dl/custom.json, renames it with the date and merges it into the customSensors setting. If the file cannot be read, the controller stops. Source: REA, SystemService (U12).
- OBSERVED: a custom sensor with the same name as a built-in model takes precedence over the built-in model. Source: REA, SystemService (U12).
- UNVERIFIED: the keys of a custom sensor definition. The report does not list them. Searched: SystemService (U12) and the CustomSensors class (U12). Source: REA, SystemService (U12).
- UNVERIFIED: whether a custom sensor definition reaches the port configuration of the device. The report does not say. Searched: the configuration generator (U10). Source: REA, ConfigService (U10).
- INFERRED: the conversion is applied by the device, not by the controller, because the controller stores the value as it arrives. Source: PROTO "mPort and sensors (from ace.jar 2.1.11)", section 4 (INFERRED).

## 4. 12 V outputs (command, power-on state, rules)

- OBSERVED: the output command is a task of type mfi-output for a port. The REA report lists the fields port, val, timer, volt and off_volt, and for a dimmer the level and ramp. Source: REA, class_33 (U20); PROTO "Commands to the device" (field list).
- UNVERIFIED: whether volt and off_volt are sent for an mPort output. PROTO "mPort and sensors (from ace.jar 2.1.11)", section 5, found only cmd, port and timer in the send path, while REA U20 lists volt and off_volt. The conflict is not resolved. Searched: the command construction (U20) and the send path (PROTO section 5).
- OBSERVED: if the model has the inversion flag, val and volt are swapped. Source: REA, class_33 (U20).
- INFERRED: the swap does not apply to the four output models, because they have no inversion flag. Source: REA, SystemService (U12); REA, class_33 (U20).
- OBSERVED: an output with output_lock equal to 1 does not receive the command. Source: REA, class_33 (U20); PROTO "Rules and scenes" (relaySwitch action).
- OBSERVED: the expected value configed_val is kept and is cleared when a later inform reports it. Source: PROTO "Commands to the device" (configed_val cleared when reported); REA, sensor service (U13).
- OBSERVED: the model description of the output models reads "Defaults to last configured state on power reset". Source: REA, SystemService (U12).
- UNVERIFIED: whether the device applies this default after a power loss. The description is text; no device test exists. Source: REA, SystemService (U12); PROTO "Controller responses" (reboot row).
- INFERRED: the state sent in the configuration is configed_val when it exists, otherwise output_val, and the lock value is sent with it. This matches the model description. Source: PROTO "Device configuration (setparam)" (power-on state, INFERRED); REA, ConfigService (U10).
- OBSERVED: the relaySwitch rule action sends the same output command. Source: REA, class_33 (U20); PROTO "Rules and scenes" (relaySwitch action).
- UNVERIFIED: the port number of an mPort output in the command. PROTO section 5 gives the M2M formula, but no code read links an mPort port to an output model. Searched: the model table and the port generator. Source: PROTO "mPort and sensors (from ace.jar 2.1.11)", section 5.

## 5. Per-port thresholds and alarms

- OBSERVED: there are no thresholds at port level. A threshold is a ruleset tied to one sensor, with the fields sId, tag, compare, limit, duration, enable and violation. Source: PROTO "Rules and scenes" (conditions); REA, class_31 (U19).
- OBSERVED: a violation fires when the condition lasts longer than duration minutes. In edge mode a repeat is skipped, in level mode it is not. Source: PROTO "Rules and scenes" (edge or level); REA, class_31 (U19).
- OBSERVED: a temperature value is converted to the unit chosen in the setting temperature (degrees Celsius or Fahrenheit). Source: REA, SystemService (U12).
- OBSERVED: the rule queue holds at most 30 requests. Source: REA, class_31 (U19).
- OBSERVED: thresholds do not appear in the configuration sent to the device. Source: PROTO "Device configuration (setparam)" (last paragraph); REA, ConfigService (U10).
- UNVERIFIED: a per-port alarm key in the port configuration. The report found none. The word alarm in the inform is the list of measurements, not alarm definitions (PROTO "Measurements"). Searched: ConfigService (U10) and SystemService (U12). Source: REA, ConfigService (U10); PROTO "Measurements".
- OBSERVED: a sensor rule raises the event EVT_mFi_SensorRuleset. Source: PROTO "Events" (SensorRuleset row).

## 6. What the controller UI shows or allows that mfi-server does not

The web interface of the controller was not read for this report. The points below come from the API and the model facts. What the screens show is UNVERIFIED.

- OBSERVED: the API lists sensors, adds a sensor to a port with a model and a label, moves an existing sensor to another mac and port, and edits its fields. Source: PROTO "mPort and sensors (from ace.jar 2.1.11)", section 7; REA, API (U17).
- OBSERVED: the API assigns labels to sensors. Source: REA, API (U17); INV "Areas" (Sensors and mPort row).
- OBSERVED: the controller keeps measurement history aggregated per minute, quarter hour, hour and day. Source: PROTO "Statistics"; REA, API (U17).
- OBSERVED: the controller offers rules with conditions, actions, states, calendars, scenes and scripts, and widgets. Source: PROTO "Rules and scenes"; INV "Areas" (Rules and scenes and Maps and dashboard rows); REA, API (U17) and class_31 (U19).
- OBSERVED: a temperature unit can be chosen for conditions (Celsius or Fahrenheit). Source: REA, SystemService (U12).
- OBSERVED: removing a sensor deletes its alarms, events, label mappings and readings. Source: REA, sensor service (U13), step 10.
- UNVERIFIED: whether the UI shows the detected sensors and links them to a port. Searched: the API (U17) and the sensor service (U13). Source: REA, sensor service (U13), step 4; REA "Not verified" (interface not checked).
- UNVERIFIED: whether the UI edits the calibration field and can load a custom sensor file. Searched: SystemService (U12) and the API (U17). Source: REA, SystemService (U12).

## Gaps in mfi-server

The mfi-server code was not read for this report. The comparison is with PROTO, INV and LIFE only. INV "Areas" marks Sensors and mPort as not in mfi-server, so the points below are gaps by the inventory. No edit to PROTO is made here (out of scope).

- UNVERIFIED: how the device applies each line of the mPort port configuration. Source: PROTO "mPort and sensors (from ace.jar 2.1.11)", section 3.
- OBSERVED: the 20 second removal of detected sensors and the assignment flow, including the unlinking of a sensor already on the port. Source: PROTO "mPort and sensors (from ace.jar 2.1.11)", section 7; REA, sensor service (U13), step 4.
- OBSERVED: the sensor removal order (alarms, events, label mappings, readings, then the sensor record). Source: REA, sensor service (U13), step 10.
- OBSERVED: the ports of an adopted M2M start at NONE. Source: REA, DeviceManager (U15); LIFE section 5.
- OBSERVED: calibration is one string with identity as default, and CustomSensors comes from the customSensors setting and dl/custom.json. Source: PROTO "mPort and sensors (from ace.jar 2.1.11)", section 4; REA, SystemService (U12).
- UNVERIFIED: the keys of a custom sensor definition, and whether it reaches the device. Source: REA, SystemService (U12); REA, ConfigService (U10).
- UNVERIFIED: whether volt and off_volt are part of the output command for an mPort. The sources conflict. Source: REA, class_33 (U20); PROTO "mPort and sensors (from ace.jar 2.1.11)", section 5.
- OBSERVED: an output with output_lock equal to 1 does not get the command. Source: REA, class_33 (U20).
- INFERRED: the inversion swap does not apply to the four output models, because they have no inversion flag. Source: REA, class_33 (U20); REA, SystemService (U12).
- UNVERIFIED: the power-on behaviour of an output after a power loss, although the model description says it keeps the last configured state. Source: REA, SystemService (U12); PROTO "Device configuration (setparam)".
- OBSERVED: the temperature unit setting and the rule queue limit of 30. Source: REA, SystemService (U12); REA, class_31 (U19).
- UNVERIFIED: per-port alarm settings in the port configuration. Source: REA, ConfigService (U10); PROTO "Measurements".
