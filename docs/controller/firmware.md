# Firmware handling of the mFi Controller 2.1.11 (clean room report)

This is a clean-room report of firmware handling in `ace.jar` 2.1.11. It is built only from the repository documents `docs/PROTOCOL.md` (PROTO), `docs/controller/INVENTORY.md` (INV) and `docs/controller/device-lifecycle.md` (LIFE). It contains no controller code, no pseudocode and no decompiler output. Every fact has a status (OBSERVED, INFERRED or UNVERIFIED) and a source given by section or row name. Anything not stated in those documents is UNVERIFIED.

## 1. How the controller knows the device firmware and the latest version

- OBSERVED: the device reports its version in the inform, in the field `version`. Source: PROTO "Payload" (JSON fields read and stored).
- OBSERVED: the device reports its version in discovery. TLV type 3 is the version string and TLV type 22 is the firmware version. Source: PROTO "Discovery" (main types).
- OBSERVED: on the mPower mini (platform P1E, firmware 2.1.11.1309, measured 2026-11-17) the discovery reply has no TLV type 22. The server therefore derives the firmware from the version string of type 3. Source: PROTO "Discovery", MEASURED block. Other models were not measured: UNVERIFIED.
- OBSERVED: the latest version comes from `dl/firmware/bundles.json` in the controller package. Source: PROTO "Firmware archive".
- OBSERVED: an inform gets an `upgrade` response when the device firmware differs from `bundles.json` and auto-upgrade is on. Source: PROTO "Controller responses", row 3.
- UNVERIFIED: the comparison rule. Row 3 says "differs", while the "Firmware archive" section says the controller does not upgrade a device whose firmware is "not older" than the archive version. The sources do not reconcile the two wordings.

## 2. Upgrade command

- OBSERVED: the message has the form `{"_type":"upgrade","url":"http://<host>:<port>/dl/firmware/<path>","version":"<version>"}`. Source: PROTO "Firmware archive" (upgrade message) and "Commands to the device" (`_type: upgrade`).
- OBSERVED: for the 2.1.11 archive the path is `M2M/2.1.11.1309/firmware.bin`. The file in the package is 7,418,034 bytes, with sha256 `7dc6fb4bd67c6352b940d8b65dd0d99325199e8dc4052c20139aaf861fec2a79`. Source: PROTO "Firmware archive" (measured).
- UNVERIFIED: the format of the `version` field. PROTO marks it UNVERIFIED. The hypothesis `2.1.11.1309` is not relied on.
- UNVERIFIED: any md5, signature or other integrity check of the firmware before or after the upgrade. No repository document describes one.
- OBSERVED: the device is in state 4 (firmware upgrade) for 180 s after the upgrade is sent. Source: PROTO "Device states in the controller"; "Firmware archive".
- UNVERIFIED: retry behaviour. No repository document describes a retry count or a retry interval.

## 3. Firmware per model

- OBSERVED: one M2M firmware file serves all models. Source: PROTO "Firmware archive".
- OBSERVED: `bundles.json` lists 10 models: IWD1U, P1E, IWO2U, P8U, M2S, M2M, P6E, P1U, P3E, P3U. All of them point to `M2M/2.1.11.1309/firmware.bin`, version `2.1.11.1309`, with an empty display name. Source: PROTO "Firmware archive" (measured).
- OBSERVED: `bundles.json` uses single quotes and is not strict JSON, so a strict JSON parser rejects it. Source: PROTO "Firmware archive" (measured).
- INFERRED: EM3, EM24, THERM and IWS1U are accepted as mFi models but have no entry in `bundles.json`, so the controller offers no upgrade to them. Source: PROTO "Firmware archive" and "Devices" (model list).
- OBSERVED: a model missing from `dl/firmware/bundles.json` gets HTTP 400. Source: PROTO "Devices".
- UNVERIFIED: any choice of firmware by hardware revision or by model family other than the `bundles.json` entry.

## 4. States during the upgrade and how it detects the end or an error

- OBSERVED: state 4 is firmware upgrade, with a timeout of 180 s. Source: PROTO "Device states in the controller".
- OBSERVED: the upgrade events are `EVT_AP_UpgradeScheduled` (upgrade scheduled) and `EVT_AP_Upgraded` (version changed). Source: PROTO "Events" table.
- OBSERVED: the host status value `upgrade` appears in the states read by the Wi-Fi setup page script. Source: PROTO "Wi-Fi setup mode" (states used by the page script). Its meaning for the controller is UNVERIFIED.
- INFERRED: the end of an upgrade is recognised when the version in a later inform differs from the version before. Source: PROTO "Events" (`EVT_AP_Upgraded`, version changed) and "Controller responses".
- UNVERIFIED: an explicit error for a failed upgrade. No upgrade error event appears in PROTO "Events" or INV "Device lifecycle".
- UNVERIFIED: what happens when the 180 s of state 4 expire without a version change. PROTO gives the timeout and nothing after it.

## 5. Automatic or bulk upgrade

- OBSERVED: the upgrade response depends on an auto-upgrade flag. Source: PROTO "Controller responses", row 3.
- UNVERIFIED: the name, scope and default of that flag, and where it is set.
- INFERRED: no bulk upgrade command exists. PROTO "Commands to the device" lists only the per-device `_type: upgrade` message. Source: PROTO "Commands to the device".
- UNVERIFIED: scheduling of an upgrade for a later time.

## 6. Custom or user-uploaded firmware (UploadServlet)

- OBSERVED: `UploadServlet` is in the System row of the inventory. Source: INV "System".
- OBSERVED: the route `/upload/backup` is the backup-restore upload. Source: LIFE section 5 (Data restore); INV "Device lifecycle" (Data restore row).
- UNVERIFIED: any firmware upload route. None is identified in INV or LIFE. This is not a proof that none exists.
- OBSERVED: the controller serves firmware under `/dl/firmware/<path>`. Source: PROTO "Firmware archive" (URL form).
- UNVERIFIED: which servlet serves `/dl/firmware`. INV lists `DownloadServlet` in the System row but does not say it serves firmware.
- UNVERIFIED: whether any upload path accepts custom firmware.

## Gaps in mfi-server

This comparison uses PROTO "Firmware archive" and "Commands to the device". The mfi-server code was not read for this report.

- Open, UNVERIFIED: the format of the `version` field. PROTO marks this UNVERIFIED.
- Open, UNVERIFIED: the comparison rule, "differs" or "not older" (section 1). PROTO does not reconcile the two.
- Open, UNVERIFIED: an integrity check of the firmware. No repository document marks this; it is UNVERIFIED here.
- Open, UNVERIFIED: retry behaviour. No repository document marks this; it is UNVERIFIED here.
- Open, UNVERIFIED: the outcome after the 180 s of state 4, and an explicit upgrade error. No repository document marks this; it is UNVERIFIED here.
- Open, UNVERIFIED: automatic and bulk upgrade settings, beyond the mention of the auto-upgrade flag in PROTO "Controller responses".
- Open, UNVERIFIED: custom firmware. UploadServlet is known only for the backup route (LIFE section 5).

Nothing in this report was verified on a device. The device side of the upgrade is not in the code read.
