# Changelog

All notable changes to this repository. Each add-on has its own CHANGELOG.md.

## 0.2.0 - 2026-11-15

- New add-on `mfi-controller` 0.1.0 (phase 1): original mFi Controller 2.1.11 on
  Debian 8 jessie with OpenJDK 7u261 and MongoDB 2.4.10, built and tested with
  Docker on an amd64 host (not yet on Home Assistant OS). Measurements in
  `mfi-controller/README.md`.
- New `tools/bench_mfi_controller.sh`: Docker test bench for the add-on (build,
  start, wizard, mficlient login, restart, restore of a `.unf` backup in a
  throwaway container without network). Run by a human, not by the test suite.
- AGENTS.md facts corrected: `mFi/bin/mongod` is a symlink to `/usr/bin/mongod`,
  not a placeholder; the internal MongoDB port 37017 is now measured.
- README: local add-ons folder is now `local_apps` (`/addons` in the
  Advanced SSH & Web Terminal app); install steps use the current "Apps" names.

## 0.1.0 - 2026-11-15

- Repository skeleton: README, AGENTS.md (rules for DevAgentAi), repository.yaml,
  docs (architecture, protocol notes, DevAgentAi settings), offline structure tests.
