# in-wall devices in the mFi Controller 2.1.11 (clean room report)

This is a clean-room report of the in-wall products of the mFi Controller 2.1.11 (`ace.jar`): outlet `IWO2U`, dimmer `IWD1U` and switch `IWS1U`. It is built only from the repository documents `docs/PROTOCOL.md` (PROTO) and `docs/controller/INVENTORY.md` (INV). The report contains no code from `ace.jar`, no pseudocode and no decompiler output. Every fact has a status (OBSERVED, INFERRED or UNVERIFIED) and a source. Nothing in this report was verified on a device.

## 1. In-wall models known to the controller (codes, outlets, measures)

- OBSERVED: three in-wall model codes are accepted as mFi devices: `IWO2U` (2 ports created at adoption), `IWD1U` (1 port created at adoption) and `IWS1U` (no ports created at adoption). Source: PROTO "Devices" (model-code table and accepted-models list).
- OBSERVED: `IWO2U`, `IWS1U` and `IWD1U` are in the `eth1` interface list of `system_cfg`. Source: PROTO "Controller responses" (`system_cfg`).
- OBSERVED: `IWD1U` and `IWO2U` have a firmware entry in `bundles.json`; `IWS1U` has none, so the controller offers it no firmware upgrade. Source: PROTO "Firmware archive".
- INFERRED: the commercial names from the official Quick Start Guides are the in-wall outlet (MPW / MPW-W) and the in-wall switch or dimmer (LD / LD-W); the code carries no commercial name. Source: PROTO "Devices" (Family table).
- OBSERVED: `IWO2U` and `IWD1U` report the outlet measures `output`, `pf`, `energy_sum`, `v_rms`, `i_rms` and `active_pwr`, sent through `vpower` lines in `port_cfg`. Source: PROTO "Controller responses" (`port_cfg` for mPower and in-wall outlets); PROTO "Measurements" (tag table); INV "Products".
- UNVERIFIED: the measures of `IWS1U`; it has no ports at adoption and its functions were not read. Source: PROTO "Devices"; INV "Products" (IWS1U row).

## 2. Commands: on and off; for the dimmer the level (scale, step, ramp) and the message format

- OBSERVED: on and off use the `mfi-output` command; `val` 1 means on and 0 means off. The fields are `port`, `sId`, `val`, `volt`, `off_volt`, `timer`, `dimmer_level` and `dimmer_ramp`. Source: PROTO "Commands to the device" (`mfi-output`).
- OBSERVED: `dimmer_level` is sent only for dimmers (`IWD1U`); `dimmer_ramp` is present in the same message. Source: PROTO "Commands to the device".
- OBSERVED: the command is queued as a task and delivered as the response to the next inform (`_type=cmd`), only if the device was already connected; a newer command for the same port replaces the old one. Source: PROTO "Commands to the device"; PROTO "mPort and sensors (from ace.jar 2.1.11)", section 5.
- UNVERIFIED: the scale, the step and the ramp unit of `dimmer_level` and `dimmer_ramp`; the controller code read does not enumerate them. Source: PROTO "Commands to the device".

## 3. Settings: state at power-on, dimmer minimum and maximum, load type, lock

- INFERRED: the state at power-on. The `relay` and `output` values sent come from `configed_val` when it exists, otherwise from `output_val`; the report shows no field named for power-on. Source: PROTO "Device configuration (setparam)".
- OBSERVED: only `IWD1U` gets `dimmer_mode` in `device_cfg` (default `switch`). Source: PROTO "Device configuration (setparam)"; PROTO "mPort and sensors (from ace.jar 2.1.11)", section 3.
- OBSERVED: at adoption `IWD1U` has `dimmer_lock` 0 and `led_brightness` 255. Source: INV "Products" (IWD1U row).
- OBSERVED: the lock comes from `output_lock` and is sent as `vpower.K.lock`; the `dimmer_lock_setting` command (fields `sId`, `mac`, `port`, `val`) sets it. Source: PROTO "Commands to the device" (`dimmer_lock_setting`); PROTO "Device configuration (setparam)".
- UNVERIFIED: a dimmer minimum level, a dimmer maximum level and a load type; no such field was found in the configuration or the sensor record. Source: PROTO "Device configuration (setparam)".
- OBSERVED: outlet thresholds are kept as controller rules (`ruleset`) and do not reach the device. Source: PROTO "Device configuration (setparam)"; PROTO "Rules and scenes".

## 4. Physical button of the switch (how it reaches the controller, event or measure, and whether it can command other devices)

- UNVERIFIED: the functions of `IWS1U` were not read. It creates no ports at adoption and appears only in the port-configuration list, not with `mfi=true` in discovery. Source: INV "Products" (IWS1U row); PROTO "Devices".
- INFERRED: a change of the physical state would reach the controller the same way as an outlet state, as an `output` measurement in the `alarm` list. Source: PROTO "Measurements" (tag table, `output`).
- OBSERVED: a `relaySwitch` rule action can switch another port; it sends a command to that port unless the port's `output_lock` is 1, in which case the rule records an error and does nothing. Source: PROTO "Rules and scenes".
- UNVERIFIED: whether the physical button raises a distinct event; the report lists no in-wall-specific event key. Source: PROTO "Events" (event-key table).

## 5. What the controller UI shows or allows for the in-wall devices that mfi-server does not

The controller web interface was not read for this report. The points below come from the API, setparam and model facts; what the screens show is UNVERIFIED.

- OBSERVED: the controller sets `dimmer_mode` in `device_cfg`, sends the `dimmer_lock_setting` command, and carries `dimmer_level` and `dimmer_ramp` in `mfi-output`. Source: PROTO "Device configuration (setparam)"; PROTO "Commands to the device".
- UNVERIFIED: what the dimmer configuration screen of the controller shows and which values it offers. Source: PROTO "Device configuration (setparam)".

## Gaps in mfi-server

The mfi-server code was not read for this report; the comparison is with PROTO and INV only. No edit to PROTO is made here.

- INFERRED: mfi-server does not carry `dimmer_level` or `dimmer_ramp` in `mfi-output`, nor `dimmer_mode` in `device_cfg`, nor the `dimmer_lock_setting` command. Source: INV "Areas"; PROTO "Commands to the device"; PROTO "Device configuration (setparam)".
- UNVERIFIED: the dimmer scale, step, ramp unit, minimum and maximum, and the load type, so mfi-server cannot reproduce the dimmer settings. Source: PROTO "Commands to the device".
- UNVERIFIED: the behaviour of `IWS1U`, so mfi-server cannot represent the in-wall switch. Source: INV "Products" (IWS1U row).
