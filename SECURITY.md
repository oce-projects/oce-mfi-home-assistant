# Security Policy

This repository contains Home Assistant add-ons for Ubiquiti mFi devices. The mFi product line is end-of-life, and the mFi Controller 2.1.11 dates from 2015.

## Supported versions

Only the latest version of each add-on receives security fixes. Older versions do not.

| Add-on | Supported versions |
|---|---|
| `mfi-controller` | latest version only |
| `mfi-server` | latest version only |

## Reporting a vulnerability

Report vulnerabilities privately. Never open a public issue for a security problem.

Use GitHub private vulnerability reporting: open the **Security** tab of this repository and choose **Report a vulnerability**.

## Known limits

- The mFi firmware and the mFi Controller 2.1.11 (2015) are old. The vendor no longer publishes security updates for them.
- Keep mFi devices on an isolated network without internet access.
- Never expose these ports to the internet: 6080/tcp (device inform), 6443/tcp (controller web UI), 3478/udp (wake-up packets) and 8099/tcp (mfi-server web page).
