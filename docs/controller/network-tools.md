# SSH, web shell, UPnP, guest page and Wi-Fi configuration of the mFi Controller 2.1.11 (clean room report)

This is a clean-room report of the network and Wi-Fi area of the mFi Controller 2.1.11 (`ace.jar`): SSH and web shell, UPnP, the guest page and the Wi-Fi configuration of devices. It is built only from the repository documents `docs/controller/INVENTORY.md` (INV), `docs/PROTOCOL.md` (PROTO), `docs/WIFI-SETUP.md` (WIFI), `docs/ARCHITECTURE.md` (ARCH), `mfi-server/DOCS.md` (DOCS) and `AGENTS.md` (AGENTS). It also uses the reverse engineering report quoted in the ticket (REA). REA is an input to this report, not a repository document. The report contains no code from `ace.jar`, no pseudocode and no decompiler output. In this report OBSERVED means stated in the source documents, not read directly from `ace.jar`. INFERRED means deduced from class names or from other facts, and the reason is given. UNVERIFIED means no document confirms it. Nothing here was verified on a device. No credentials, SSID, passwords, and no real MAC, e-mail or private IP address are reproduced.

## 1. SSH and web shell: what they allow, credentials, who may use them

- The controller has an SSH session and a web shell toward a managed device. Their names suggest a terminal on the device, opened from the web interface. INFERRED from the class names SshServlet, WebshellServlet and WebshellInputServlet, and from the Network and Wi-Fi row of INV, which is itself INFERRED. Source: INV "Areas" (Network and Wi-Fi row) and INV "Classes" table.
- The SSH connection to a device is made during adoption: the controller connects on port 22 and sends the adoption command with the inform address and the device key. OBSERVED. Source: PROTO "Adoption", item 3.
- For a factory device, the controller uses the fixed factory credentials described in PROTO. The values are not reproduced here. OBSERVED. Source: PROTO "Adoption", item 4; PROTO "Factory state".
- For an automatic re-adoption, the controller uses its own administrator name and password. OBSERVED. Source: PROTO "Adoption", item 4.
- The administrator password is written into the device configuration as a DES-based Unix crypt with a random two-letter salt, and it becomes the SSH and web password of every adopted device. OBSERVED. Source: PROTO "Security summary"; PROTO "Controller responses" (system_cfg).
- The controller code contains other SSH commands: one restores factory defaults and one sets the default flag in the management configuration. The existence of these commands is OBSERVED; when they are called is UNVERIFIED. Source: PROTO "Adoption" (last paragraph).
- Who may use a web shell: a connected administrator of the controller, as the class names and the Users area suggest. The access check in the code is not in the repository documents. INFERRED for the purpose, UNVERIFIED for the check. Source: INV "Areas" (Users row); INV "Classes" table (WebshellServlet row).
- A telnet mode of the web shell and the exact protocol and port of the web shell are mentioned only by REA. UNVERIFIED. Source: REA report, network section.
- The configuration sent to a device at adoption includes a setting that disables the telnet service. The setting is approximate in PROTO. INFERRED. Source: PROTO "Controller responses" (system_cfg).
- Terminal type, session timeouts and output buffering of the web shell come from REA only. UNVERIFIED. Source: REA report, network section.

## 2. UPnP: purpose and when it activates

- The UpnpServlet class name suggests a UPnP function, inherited from the UniFi code base on which the controller is built. INFERRED. Source: INV "Classes" table (UpnpServlet row); AGENTS "Facts you can rely on" (archive row).
- No repository document says that mFi devices or the controller use UPnP. The mFi discovery is a different protocol on UDP port 10001. UPnP use: UNVERIFIED. Discovery on port 10001: OBSERVED. Source: PROTO "Discovery (UDP 10001)"; INV "Areas" (Discovery row).
- REA reads the class as sending service announcements on the local network, controlled by a setting that is on by default, and not as opening ports on a router. UNVERIFIED. Source: REA report, network section.
- When the announcements start and stop, and which setting controls them, are known only from REA. UNVERIFIED. Source: REA report, network section.

## 3. Guest page (GuestServlet): what it shows and to whom; mFi or UniFi remnant

- The class name suggests a guest access page, where a client of the network is asked for a password or accepts terms before it gets access. INFERRED from the class name. Source: INV "Classes" table (GuestServlet row).
- A change of the guest access settings changes the configuration version sent to devices. OBSERVED. Source: PROTO "Device configuration (setparam)" (change listener bullet).
- The configuration sent to a device has a guest flag in the management configuration and a list of authorized guests in the setparam message. OBSERVED. Source: PROTO "Controller responses" (setparam fields and mgmt_cfg).
- The commands to authorize and unauthorize guests are inherited from UniFi and are listed in PROTO. OBSERVED. Source: PROTO "Commands to the device" (last table row).
- Whether the guest page is shown to clients by mFi devices, and to whom, is not in the repository documents. The page is most likely a UniFi remnant, because the class and the commands are inherited. Remnant: INFERRED. Runtime behaviour: UNVERIFIED. Source: INV "Areas" (Network and Wi-Fi row); PROTO "Commands to the device".
- PROTO documents no mFi model with a guest portal. The guest portal as a page is UNVERIFIED. Source: PROTO "Devices".

## 4. WlanConf: Wi-Fi configuration of devices (SSID, security, channel), format and when sent

- The WlanConf class name suggests a Wi-Fi configuration record of the controller. Its collection is not named in INV. INFERRED. Source: INV "Classes" table (WlanConf row); INV "Areas" (Network and Wi-Fi row).
- A change of the WLAN settings changes the configuration version. The new configuration is sent with setparam when the device informs with an older version. OBSERVED. Source: PROTO "Device configuration (setparam)" (change listener bullet and confirmation bullet); PROTO "Controller responses" (row 4).
- The exact format of the Wi-Fi block sent to the device, and which keys it holds, is not in the repository documents. UNVERIFIED. Source: PROTO "Controller responses" (system_cfg contents).
- The setup form of a Wi-Fi device without configuration has these fields: network name (essid), security, WEP keys, WPA mode and passphrase, and EAP fields. The security values are none, wep, wpa, wpatkip, wpaaes, wpa2, wpa2tkip and wpa2aes. The form has no channel field. OBSERVED. Source: PROTO "Wi-Fi setup mode" (form table); WIFI "Version 2 window" (step 4).
- The setup page is a different path from the controller configuration. The setup page of a new Wi-Fi device is served at 192.168.2.20 and does not carry controller fields. OBSERVED. Source: WIFI "Why"; WIFI "Version 2 window"; PROTO "Wi-Fi setup mode".
- The controller reads the UniFi table `vap_table` from the inform, which would give channel, power and network names. PROTO states that mFi does not use this table. The conflict is not resolved. UNVERIFIED. Source: PROTO "Payload" (last bullet); REA report, network section.
- REA reports default values for country code, channel, radio mode, power and bandwidth, and a default passphrase used when none is set. These are not in the repository documents and the passphrase is not reproduced here. UNVERIFIED. Source: REA report, network section.

## 5. Security risks (description only, no attack instructions)

- The mFi firmware and the 2015 controller have known weaknesses: old SSH ciphers, and an authentication bypass reported in 2015 that is not fixed. OBSERVED for the statement; the details of the bypass are UNVERIFIED. Source: AGENTS hard rule 8; AGENTS "Facts you can rely on".
- The factory SSH credentials are fixed, and the first SSH contact has no host key check. OBSERVED. Source: PROTO "Security summary"; PROTO "Adoption", item 3.
- The administrator password is kept in clear text by the controller and is sent to every device as a DES crypt, which is weak by modern standards. OBSERVED. Source: PROTO "Security summary".
- The SSH connection to devices has no host key check, so another host on the same network could answer in place of a device. OBSERVED. Source: PROTO "Adoption", item 3; DOCS "Factory adoption".
- The setup page of Wi-Fi devices accepts TLS 1.0 only, with a self-signed certificate that expired in 2018 and a 1024-bit RSA key. Current browsers refuse TLS 1.0. OBSERVED. Source: PROTO "Wi-Fi setup mode"; WIFI "Why".
- REA reports that the Wi-Fi configuration text may carry passphrases and WEP keys in clear text, and that the discovery announcement may reveal product and version on the local network. UNVERIFIED. Source: REA report, network and security sections.
- Devices belong on an isolated network without internet access, and ports 6080 and 6443 must never be exposed to the internet. OBSERVED. Source: AGENTS hard rule 8.

This section describes only the weaknesses. It gives no steps to use them.

## Gaps in mfi-server

The mfi-server code was not read for this report; the comparison uses DOCS, INV and ARCH only.

- mfi-server uses SSH only for adoption and re-pointing. It runs the system ssh program without a shell and sends the adoption command with the inform address and the new key. OBSERVED. Source: DOCS "Adopting and re-pointing devices" (SSH program and Factory adoption paragraphs).
- mfi-server offers no terminal and no web shell. The routes table and the web page sections list none. OBSERVED. Source: DOCS "Web API" (routes table); DOCS "Web page".
- mfi-server has no UPnP function. DOCS does not describe one. OBSERVED that DOCS has no UPnP section; the absence in the code is not checked. Source: DOCS (no UPnP section).
- mfi-server has no guest page and no guest access settings. The routes table and the web page sections list none. OBSERVED. Source: DOCS "Web API" (routes table); DOCS "Web page".
- mfi-server does not send the device configuration yet: DOCS says the configuration step follows after a device test. The Wi-Fi configuration of devices is therefore not sent by mfi-server. OBSERVED. Source: DOCS "Adopting and re-pointing devices" (Factory adoption paragraph); WIFI "Version 2 window" (controller fields not sent).
- The commands mfi-server does send to devices through the inform are the firmware upgrade and the output switch. OBSERVED. Source: DOCS "Firmware" (Updating a device); DOCS "Web API" (output route).
- The Wi-Fi setup of new devices is done by the Windows program, which sends only the home network name, the security mode and the passphrase to the setup page. OBSERVED. Source: WIFI "Version 2 window" (steps 3 and 4).
- Like the controller, mfi-server disables the host key check for factory adoption. OBSERVED. Source: DOCS "Factory adoption" paragraph; PROTO "Adoption", item 3.
- Channel, power and radio settings of devices are not handled by mfi-server. OBSERVED that DOCS does not describe them. Source: DOCS "Adopting and re-pointing devices"; DOCS "Web API" (routes table).
