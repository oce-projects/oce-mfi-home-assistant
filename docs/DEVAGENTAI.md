# DevAgentAi project settings

These settings live in the DevAgentAi database, not in this repository; values read from DevAgentAi on 2026-11-15.

| Key | Value | Note |
|---|---|---|
| `test_command` | `python3 -m unittest discover -s tests -v` | stdlib only, offline |
| `test_image` | `devagentai-core:latest` | already on the DevAgentAi host; the first proposal `python:3.12-slim` is not available there; the test suite passed in both images on 2026-11-15 |
| `file_regole` | `["AGENTS.md", "docs/ARCHITECTURE.md"]` | together under the 12,000 character limit (checked by `test_rules_files_fit_devagentai_limit`) |
| `protected_paths` | `repository.yaml`, `tests/` | prefix match: a ticket that touches `tests/` waits in review instead of merging by itself; the global entry `Dockerfile` does not match `mfi-controller/Dockerfile` |
| `auto_merge` | `true` | DevAgentAi default |
| `file_con_versione` | not set | the version rules are enforced by `tests/test_repository.py` (`VERSION` vs `CHANGELOG.md`, add-on version vs its changelog and its Dockerfile `BUILD_VERSION`) |
| `rag_cartella` | not set | the default applies: the knowledge base folder named after the project, `KB_TECNICA_PROGETTI/oce-mfi-home-assistant` |
| `deploy_attivo` | off | the deploy target is Home Assistant OS, not the DevAgentAi host |

## What agents can and cannot verify here

- Can: repository structure, versions, changelogs, YAML and docs consistency,
  absence of vendor files and private data (all in `tests/`).
- Cannot: building the add-on image, running the controller, talking to a device,
  installing on Home Assistant. These need a human or a dedicated runner.
  An agent must write the exact commands and the expected output in the ticket.

## Knowledge base

The project knowledge base contains real site data (device MAC addresses, IP addresses, names, key fields). Never copy any of it into this repository. `tests/test_repository.py` checks for MAC addresses, private IPv4 addresses, personal names, e-mail addresses and local paths. The public default inform key may be used in tests.

## Ticket files

DevAgentAi writes `.tickets/<id>.md`. The folder is in `.gitignore` because
tickets may contain local details that must not be published.
