# bambulab — Hermes plugin

Monitor and control **Bambu Lab** printers (H2S / X1 / P1 / A1) over **local MQTT** —
multi-printer, live status, Discord alerts, and a **dashboard printer-manager** with
masked access-code fields.

## Features
- **Multi-printer, no cap** — add as many printers as you want.
- **Dashboard** — a *Bambu Lab* tab in the Hermes web dashboard. Add/edit printers
  (name, IP, serial) with a **masked access-code field** (asterisks). Codes are stored
  in `.env` — never in `config.yaml`, never in the repo.
- **Tools** (model-callable): `bambu_list`, `bambu_status`, `bambu_pause`,
  `bambu_resume`, `bambu_stop`, `bambu_speed`, `bambu_filament`.
- **CLI**: `hermes bambu status|pause|resume|stop|speed|filament`.
- **Shareable**: `hermes plugins install <this-repo-url>` (pinned by commit SHA).

## Prerequisites
- Python dep (declared in `plugin.yaml`, surfaced but **not** auto-installed):
  `bambulabs-api` → `pip install bambulabs-api`
- Printer in **LAN / local mode** (Developer mode on) so unsigned local commands are accepted.

## Config
- Printers + codes: enter in the **Bambu Lab** dashboard tab.
- Non-secret settings: `plugins.entries.bambulab.settings` (`poll_seconds`, `alert_on`).
- Access codes: `.env` → `BAMBLAB_KEY_<SLUG>` (written by the dashboard, read via `get_secret`).

## Security
- Access codes are secrets: they live only in `.env`, are read through
  `agent.secret_scope.get_secret`, are stripped from any exported pack, and are never
  written to `config.yaml` or committed to this repo.
