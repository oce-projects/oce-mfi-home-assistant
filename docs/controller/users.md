# Users and permissions of the mFi Controller 2.1.11 (clean room report)

This is a clean-room report of the users, permissions, login, tokens and authentication server of the mFi Controller 2.1.11 (`ace.jar`). It is built only from the repository documents `docs/controller/INVENTORY.md` (INV), `docs/PROTOCOL.md` (PROTO), `docs/ARCHITECTURE.md` (ARCH), `mfi-server/DOCS.md` (DOCS) and `AGENTS.md` (AGENTS). It contains no code from `ace.jar`, no pseudocode and no decompiler output. Every fact has a status (OBSERVED, INFERRED or UNVERIFIED) and a source. In this report OBSERVED means stated in the source documents, not read directly from `ace.jar`. Nothing in this report was verified on a device. Passwords, hashes, salts and tokens are not reproduced here: the report only says that they exist and how they are used.

## 1. Account types and permissions; groups

- INV lists the classes User, Admin, Session, Token, AuthServer, Groups and AuthFilter in the Users area. The whole Users area has status INFERRED in INV, and no class of it was opened one by one. INFERRED. Source: INV "Areas" (Users row) and INV Classes table.
- The controller has an administrator account. Automatic re-adoption of a device uses the controller administrator name and password. A normal adoption uses the factory credentials of the device (PROTO "Adoption", item 4). OBSERVED. Source: PROTO "Adoption" (item 4) and "Security summary".
- INFERRED from the class names: Admin is the administrator account, User is a user account, and Groups is a grouping used to grant access. The mapping of Groups to devices or locations is not stated in the repository documents. INFERRED. Source: INV "Areas" (Users row, status INFERRED).
- The existence and the exact permissions of a guest account, the permission set of each account type, and whether Groups grant access to devices or to locations, are not in the repository documents. UNVERIFIED. Source: INV "Areas".

## 2. Login: password check, lockout, session and expiry

- A login and session filter exists in the controller (class AuthFilter). OBSERVED. Source: INV Classes table (AuthFilter, OBSERVED) and INV "Areas" (Web API row).
- The session and token classes (Session, Token, AuthServer) take part in the login, as their names suggest. INFERRED. Source: INV "Areas" (Users row).
- The controller keeps the administrator password in clear text; where exactly it is stored is not known. The device receives it as a DES-based Unix crypt with a random two-letter salt in `system_cfg`, and it becomes the SSH and web password of every adopted device. OBSERVED. Source: PROTO "Security summary" and "Controller responses".
- The hash algorithm the controller uses to verify its own web login password is not in the repository documents. UNVERIFIED. Source: INV "Areas" (Users row).
- The lockout after failed attempts, the name of the session cookie or token, and the expiry of a session or token, are not in the repository documents. UNVERIFIED. Source: INV "Areas" (Users row).

## 3. Token: purpose and duration

- A Token is created for a device at adoption, together with the Device record and its ports, and it is removed when the device is forgotten. OBSERVED. Source: INV "Device lifecycle" (Adoption and Forget rows).
- Whether Token is also used for an API key, a mobile app or a password reset, as the class name might suggest, is not in the repository documents. UNVERIFIED. Source: INV "Areas" (Users row).
- The duration or expiry of a Token is not in the repository documents. UNVERIFIED. Source: INV "Areas" (Users row).

## 4. AuthServer: external authentication (RADIUS, LDAP or other)?

- An AuthServer class is listed in the Users area; its name suggests an authentication-server abstraction. INFERRED. Source: INV "Areas" (Users row) and INV Classes table (AuthServer, INFERRED).
- Whether AuthServer performs external authentication such as RADIUS or LDAP is not stated in the repository documents. UNVERIFIED. Source: INV "Areas" (Users row).
- The `wpa_ident`, `wpa_user` and `wpa_passwd` fields in PROTO are the Wi-Fi (EAP) fields of the device setup form, not the controller login, so they are not evidence of external login authentication. OBSERVED (they are Wi-Fi fields). Source: PROTO "Wi-Fi setup mode" (form fields table).

## 5. Known security weaknesses (description only, no attack instructions)

- AGENTS rule 8 and its facts record that mFi firmware and the 2015 controller have known weaknesses: old SSH ciphers and an unpatched authentication bypass reported in 2015. Ports 6080 and 6443 must never be exposed to the internet, and the devices belong on an isolated network. OBSERVED. Source: AGENTS hard rule 8 and "Facts you can rely on".
- The details of the 2015 authentication bypass are not in the repository documents. UNVERIFIED. Source: AGENTS hard rule 8.
- The controller stores the administrator password in clear text and pushes it to every adopted device as a DES-based crypt, which is weak by modern standards. The factory adoption credentials are a fixed default user and password. OBSERVED. Source: PROTO "Security summary" and "Factory state".
- This section describes the weaknesses only; it gives no steps to exploit them.

## Gaps in mfi-server

The mfi-server code was not read for this report; the comparison is with DOCS, INV and ARCH only.

- mfi-server standalone login: `POST api/v1/login` takes a JSON body with a password, and the answer sets the session cookie `mfi_session`. The password is set with the `set-password` command. A wrong password answers 401, and five failures in 60 seconds from one address answer 429. OBSERVED. Source: DOCS "Web API".
- mfi-server therefore has a lockout, while the controller lockout is UNVERIFIED (section 2). OBSERVED. Source: DOCS "Web API"; INV "Areas" (Users row).
- The mfi-server standalone password is stored as a salted PBKDF2 hash, not in clear text like the controller administrator password. INFERRED. Source: ARCH "Decisions" (2026-11-15).
- In add-on mode mfi-server has no login: the page is served only through the Home Assistant ingress, from the ingress peer address 172.30.32.2 by default; other addresses get 403. OBSERVED. Source: DOCS "Web API" and "Network".
- mfi-server has a single password, with no multiple users, admins, groups, external authentication server or per-device API token. OBSERVED. Source: DOCS "Web API".
- Multiple users for mfi-server are not described in DOCS or ARCH and are not planned in the documents read. INFERRED. Source: DOCS "Web API"; ARCH "Decisions".
