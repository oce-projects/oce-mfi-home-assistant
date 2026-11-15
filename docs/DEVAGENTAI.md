# DevAgentAi project settings (proposal)

These are the settings proposed for this project in DevAgentAi. They live in the
DevAgentAi database, not in this repository; set them from the DevAgentAi UI.
Keys marked "verify" must be checked against DevAgentAi's own docs before use.

| Key | Proposed value | Note |
|---|---|---|
| `test_command` | `python3 -m unittest discover -s tests -v` | stdlib only, offline |
| `test_image` | `python:3.12-slim` | verify which images DevAgentAi allows |
| `file_regole` | `["AGENTS.md", "docs/ARCHITECTURE.md"]` | together well under the 12,000 character limit |
| `file_con_versione` | `VERSION` | format `schema#regex`: verify |
| `protected_paths` | `repository.yaml`, `tests/` | verify: the global list already contains `Dockerfile`; check whether it matches `mfi-controller/Dockerfile` (path prefix or file name) |
| `rag_cartella` | `KB_STUDI/elettronica-iot/ubiquiti/mfi` | project knowledge base |
| `deploy_attivo` | off | deploy target is Home Assistant OS, not the DevAgentAi Linux host |

## What agents can and cannot verify here

- Can: repository structure, versions, changelogs, YAML and docs consistency,
  absence of vendor files and private data (all in `tests/`).
- Cannot: building the add-on image, running the controller, talking to a device,
  installing on Home Assistant. These need a human or a dedicated runner.
  An agent must write the exact commands and the expected output in the ticket.

## Ticket files

DevAgentAi writes `.tickets/<id>.md`. The folder is in `.gitignore` because
tickets may contain local details that must not be published.
