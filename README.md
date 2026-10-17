# bambulab — Hermes plugin

Monitor and control **Bambu Lab** printers (H2S / X1 / P1 / A1) over **local MQTT** —
multi-printer, live status, transition alerts, and a **dashboard printer-manager** with
masked access-code fields. No Bambu cloud, no cloud account: pure LAN + the open-source
[`bambulabs-api`](https://github.com/BambuTools/bambulabs_api) library.

## Install

```bash
# from this repo (pin the commit you install — catalog rule: exact SHA)
hermes plugins install justedave0/bambulab-hermes --ref <40-char-commit-sha> --yes-deps --enable
```

- `--yes-deps` answers the `bambulabs-api` dependency consent for non-interactive installs.
- Anyone can install it the same way — that's the whole share story. A listing in the
  curated catalog (`hermes plugins install bambulab`) requires a PR to the `hermes-agent`
  repo; the repo install works without it.

## Features
- **Multi-printer, no cap** — add as many printers as you want from the dashboard.
- **Dashboard tab** — *Bambu Lab* in the Hermes web dashboard: name / slug / IP / serial
  per printer, plus a **masked access-code field** (type=password, asterisks). Codes are
  stored in `.env` — never in `config.yaml`, never in this repo, never returned by the
  API (only a `has_code` flag).
- **Tools** (model-callable): `bambu_list`, `bambu_status`, `bambu_monitor`,
  `bambu_pause`, `bambu_resume`, `bambu_stop`, `bambu_speed`, `bambu_filament`.
- **CLI**: `hermes bambu list|status|pause|resume|stop|speed|filament|monitor`.
- **Slash**: `/bambu <same subcommands>` — works from Discord.
- **Alerts** — `bambu_monitor` (tool/CLI/`/bambu monitor`) polls every enabled printer
  once and reports *transitions*: print finished, print failed, filament runout, new HMS
  errors. Wire it to a Hermes cron job (e.g. every 60 s) for Discord notifications.
  Alert-only by design: control actions are never automated.

## Prerequisites
- Python ≥ 3.10, `bambulabs-api` (declared in `plugin.yaml`; install prompt on `--yes-deps`
  or manual `pip install "bambulabs-api>=2.6,<3"`).
- Printer in **LAN / local mode** with **Developer mode** on (same setup OrcaSlicer needs).
  This matters: firmware ≥ 01.07 rejects *unsigned* control commands with HMS
  `0500_0500_0001_0007`; status reads always work, but pause/resume/stop need the
  LAN-only + Developer-mode path.

## Config
- Printers + access codes: the **Bambu Lab** dashboard tab (that's the intended UX).
- Access codes: `.env` → `BAMBLAB_KEY_<SLUG>` (written by the dashboard, read only via
  `agent.secret_scope.get_secret`; removed from `.env` when a printer is removed).
- Monitor state (for transition alerts): `~/.hermes/plugins/bambulab/state.json`.

## Security
- Access codes are secrets: they live only in `.env`, are masked in the dashboard, are
  read through the secret scope, are stripped from any exported pack, and are never
  written to `config.yaml` or committed to this repo.
- The dashboard backend (`dashboard/plugin_api.py`) only mounts when the plugin is
  explicitly enabled (`plugins.enabled` allow-list) — standard Hermes trust gate.
- Control commands (pause/resume/stop/speed/filament) are exposed as tools the model
  must call explicitly; the plugin itself never issues them on its own.
