# mPort Serial (M2S) in the mFi Controller 2.1.11 (clean room report)

This is a clean-room report of the mPort Serial product (model code M2S) of the mFi Controller 2.1.11 (`ace.jar`). It is built only from the repository documents `docs/PROTOCOL.md` (PROTO) and `docs/controller/INVENTORY.md` (INV), and from the reverse-engineering report of ticket T-MWMRR5WC (REA). The report contains no code from `ace.jar`, no pseudocode and no decompiler output. Every fact has a status (OBSERVED, INFERRED or UNVERIFIED) and a source. Facts already stated in PROTO section "mPort and sensors (from ace.jar 2.1.11)" are referenced by section and are not copied. Nothing in this report was verified on a device.

## 1. Serial settings (speed, data bits, parity, stop bits, flow control)

- OBSERVED: for an M2S the controller sends `ser2net_cfg`, text with the keys `enable` (`on` or `off`), `baudRate`, `parity`, `uartMode`, `termination` and `antenna`; only M2S receives `ser2net_cfg`. Source: PROTO "mPort and sensors (from ace.jar 2.1.11)", section 6; PROTO "Device configuration (setparam)".
- OBSERVED: `serial_cfg` lines `serial.<n>` carry `speed` and `destination`. Source: PROTO "mPort and sensors (from ace.jar 2.1.11)", section 6 and section 3.
- OBSERVED: speed is carried (`baudRate` in `ser2net_cfg`, `speed` in `serial_cfg`); parity is carried (`parity` in `ser2net_cfg`). Source: PROTO "mPort and sensors (from ace.jar 2.1.11)", section 6.
- OBSERVED: data bits and stop bits are read but not written to `ser2net_cfg`; their effect on the device is UNVERIFIED. Source: PROTO "mPort and sensors (from ace.jar 2.1.11)", section 6; REA, question 1.
- UNVERIFIED: flow control. No flow-control key is among the keys the controller emits (`enable`, `baudRate`, `parity`, `uartMode`, `termination`, `antenna`). Source: PROTO "mPort and sensors (from ace.jar 2.1.11)", section 6.
- The UI offers a serial speed from 300 to 115200 and parity none, odd or even (UG-V11 p. 28). CONFIRMED (official guide) for the UI; the exact values sent to the device stay UNVERIFIED (the controller code read does not enumerate them). Source: UG-V11 p. 28; PROTO "mPort and sensors (from ace.jar 2.1.11)", section 6.
- `uartMode`: UG-V11 p. 28 lists RS232 or RS485; QSG-MPORT-S p. 7 and the specifications list RS232, RS422 and RS485; only one serial port (DB9 or terminal block) can be used at a time. CONFIRMED (official guide) for RS232 and RS485; the RS422 value is UNVERIFIED because the two guides disagree. Source: UG-V11 p. 28; QSG-MPORT-S p. 7.
- `termination`: a 120 Ohm termination resistor between TX and RX, offered in RS485 mode (UG-V11 p. 28). `antenna`: internal (default) or external (QSG-MPORT-S p. 6). CONFIRMED (official guide). Source: UG-V11 p. 28; QSG-MPORT-S p. 6.
- OBSERVED: REA found no call to the `serial_cfg` generator in `DeviceManager`, so whether `serial_cfg` reaches the device is UNVERIFIED. Source: REA, question 1.
- OBSERVED: the serial settings travel to the device inside the `setparam` message (`ser2net_cfg` and `serial_cfg`); the sensor record of a Serial port is kept in the sensor collection. Source: PROTO "Device configuration (setparam)"; PROTO "mPort and sensors (from ace.jar 2.1.11)", section 2.

## 2. Serial data access (TCP port or other channel, who opens it, authentication)

- OBSERVED: the controller sends no TCP port in `ser2net_cfg`; the port the device listens on is UNVERIFIED. Source: PROTO "mPort and sensors (from ace.jar 2.1.11)", section 6; REA, question 2.
- INFERRED: the configuration key name `ser2net_cfg` points to a serial-to-network daemon on the device side; the daemon itself is device firmware, not `ace.jar`. Source: PROTO "mPort and sensors (from ace.jar 2.1.11)", section 6 (key name `ser2net_cfg`).
- UNVERIFIED: who opens the serial data channel and how it is authenticated. The controller code read does not show the controller opening a serial data channel, and the device-side behaviour is not in `ace.jar`. Source: PROTO "mPort and sensors (from ace.jar 2.1.11)", section 6.
- The serial line is served over telnet by the device. UG-V11 p. 28 shows the port "used for Telnetting to the device", a "Connected Host" (the IP of the Telnet client connected to the mPort Serial; the controller IP when connected through the web shell) and a Disconnect button. CONFIRMED (official guide) that the device serves the serial line over telnet; the port number stays UNVERIFIED. INFERRED: the Disconnect button is the `kick-serial` command. Source: UG-V11 p. 28.

## 3. kick-serial

- OBSERVED: the controller raises the event `EVT_mFi_SerialKick` and queues a `cmd` task with `cmd` set to `kick-serial` for the device; the request is `/api/v1.0/cmd/devmgr` with `cmd` and `mac`. Source: PROTO "mPort and sensors (from ace.jar 2.1.11)", section 6; PROTO "Commands to the device" (kick-serial row); PROTO "Events" (`EVT_mFi_SerialKick` row).
- OBSERVED: a queued command is delivered in the response to the next inform, and only if the device was already connected. Source: PROTO "Controller responses" (row 9); PROTO "Commands to the device".
- UNVERIFIED: what the device does with `kick-serial`; the effect is not in the controller code. Source: PROTO "mPort and sensors (from ace.jar 2.1.11)", section 6.
- INFERRED: by its name and its serial-kick event, the command is meant to drop or reset the current serial network session so that a new client can connect. Source: PROTO "mPort and sensors (from ace.jar 2.1.11)", section 6 (event `EVT_mFi_SerialKick`).

## 4. M2S ports and sensors besides the serial, and their measures

- OBSERVED: at adoption an M2S device gets 1 port, while an M2M gets 3 ports. Source: PROTO "mPort and sensors (from ace.jar 2.1.11)", section 3; INV "Products" (mPort Serial row).
- OBSERVED: the M2S uses the same `port_cfg` line format as the M2M (`port.N`, `AI.N`, `DI.N`, `DO.N` lines). Source: PROTO "mPort and sensors (from ace.jar 2.1.11)", section 3.
- INFERRED: because of the shared line format, besides the serial the M2S can carry the same analog, digital-input and digital-output ports and their measures as the M2M. Source: PROTO "mPort and sensors (from ace.jar 2.1.11)", section 3.
- UNVERIFIED: whether an M2S with a sensor other than the Serial model uses those ports in practice. REA reports that an M2S with only a Serial sensor uses none of them. Source: REA, question 4; PROTO "mPort and sensors (from ace.jar 2.1.11)", section 3.
- OBSERVED: the Serial sensor model has no tags, so it carries no measurement. Source: PROTO "mPort and sensors (from ace.jar 2.1.11)", section 2 (Serial row).
- OBSERVED: the Serial model exists only for the M2S variant of the mPort. Source: docs/controller/mport.md, section 1.
- For the sensor models and their measures see `docs/controller/mport.md`; the same sensor table applies. Source: INV "Products"; docs/controller/mport.md.

## 5. What the controller UI shows or allows for an M2S that mfi-server does not

The controller web interface was not read for this report; the points below come from the API, setparam and model facts; what the screens show is UNVERIFIED.

- OBSERVED: the controller configures the serial line (`ser2net_cfg`: `enable`, `baudRate`, `parity`, `uartMode`, `termination`, `antenna`) and sends the `kick-serial` command. Source: PROTO "mPort and sensors (from ace.jar 2.1.11)", section 6; REA, question 5.
- INFERRED: neither the serial configuration nor `kick-serial` is in mfi-server, because INV marks Sensors and mPort as not in mfi-server. Source: INV "Areas" (Sensors and mPort row).
- UNVERIFIED: what the serial-configuration screen of the controller shows and which values it offers. Source: PROTO "mPort and sensors (from ace.jar 2.1.11)", section 6.

## Gaps in mfi-server

The mfi-server code was not read for this report; the comparison is with PROTO and INV only. INV marks Sensors and mPort as not in mfi-server, so the points below are gaps by the inventory. No edit to PROTO is made here (out of scope).

- INFERRED: mfi-server does not build the `ser2net_cfg` serial configuration (`enable`, `baudRate`, `parity`, `uartMode`, `termination`, `antenna`) nor the `serial_cfg` lines. Source: PROTO "mPort and sensors (from ace.jar 2.1.11)", section 6; INV "Areas".
- INFERRED: mfi-server does not send the `kick-serial` command nor raise `EVT_mFi_SerialKick`. Source: PROTO "Commands to the device"; PROTO "Events"; INV "Areas".
- UNVERIFIED: the TCP port and the serial data channel of the device, so mfi-server cannot bridge the serial stream. Source: PROTO "mPort and sensors (from ace.jar 2.1.11)", section 6.
- UNVERIFIED: the allowed values, the defaults, the data bits, the stop bits and the flow control of the serial line. Source: PROTO "mPort and sensors (from ace.jar 2.1.11)", section 6.
