"""bambulab — monitor & control Bambu Lab printers over local MQTT.

Built on the open-source ``bambulabs-api`` (PyPI: bambulabs-api), local/LAN mode:
no Bambu cloud, no cloud account. Works with H2S / X1 / P1 / A1 in Developer mode.

Surfaces:
* Tools (model-callable): bambu_list, bambu_status, bambu_pause, bambu_resume,
  bambu_stop, bambu_speed, bambu_filament.
* CLI: ``hermes bambu list|status|pause|resume|stop|speed|filament|monitor``.
* Slash: ``/bambu <same subcommands>``.
* Dashboard: "Bambu Lab" tab — unlimited printers, masked access-code fields.

Secrets: access codes live as ``BAMBLAB_KEY_<SLUG>`` in ``~/.hermes/.env`` and are
read only through ``agent.secret_scope.get_secret`` — never config.yaml, never chat,
never this repo.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from tools.registry import tool_error, tool_result

from . import client, monitor

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# Tool schemas
# ──────────────────────────────────────────────────────────────────────

_PRINTER_ARG = {
    "printer": {
        "type": "string",
        "description": "Printer slug (see bambu_list). Omit when only one printer is configured.",
    },
}

LIST_SCHEMA = {
    "description": "List configured Bambu Lab printers (slug, name, ip, serial, enabled, whether an access code is set).",
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
}

STATUS_SCHEMA = {
    "description": "Read live status of a Bambu Lab printer over local MQTT: state, progress, file, layer, nozzle/bed temps, speed, HMS errors.",
    "parameters": {"type": "object", "properties": _PRINTER_ARG, "additionalProperties": False},
}

CMD_SCHEMA = {
    "description": "Pause a Bambu Lab print. Control actions — confirm with the user first unless they asked for it.",
    "parameters": {"type": "object", "properties": _PRINTER_ARG, "additionalProperties": False},
}

RESUME_SCHEMA = {
    "description": "Resume a paused Bambu Lab print.",
    "parameters": {"type": "object", "properties": _PRINTER_ARG, "additionalProperties": False},
}

STOP_SCHEMA = {
    "description": "STOP a Bambu Lab print (cancels the job). Destructive — confirm with the user first unless they asked for it.",
    "parameters": {"type": "object", "properties": _PRINTER_ARG, "additionalProperties": False},
}

SPEED_SCHEMA = {
    "description": "Set Bambu Lab print speed level: 1 silent, 2 standard, 3 sport, 4 ludicrous.",
    "parameters": {
        "type": "object",
        "properties": {
            **_PRINTER_ARG,
            "level": {"type": "integer", "minimum": 1, "maximum": 4, "description": "1 silent, 2 standard, 3 sport, 4 ludicrous."},
        },
        "required": ["level"],
        "additionalProperties": False,
    },
}

FILAMENT_SCHEMA = {
    "description": "Load or unload the external filament spool on a Bambu Lab printer.",
    "parameters": {
        "type": "object",
        "properties": {
            **_PRINTER_ARG,
            "action": {"type": "string", "enum": ["load", "unload"], "description": "load or unload the spool."},
        },
        "required": ["action"],
        "additionalProperties": False,
    },
}

MONITOR_SCHEMA = {
    "description": "Poll all enabled Bambu Lab printers once and report state + transition alerts (finished / failed / filament runout / HMS errors). Read-only; safe to run from cron.",
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
}


# ──────────────────────────────────────────────────────────────────────
# Tool handlers
# ──────────────────────────────────────────────────────────────────────

def _printer_arg(args: dict) -> tuple[Optional[dict], Optional[str]]:
    """Resolve the target printer; returns (cfg, error_json)."""
    slug = args.get("printer")
    printers = client.list_printers()
    if not printers:
        return None, tool_error("no printers configured — add them in the Bambu Lab dashboard tab")
    if not slug:
        if len(printers) == 1:
            return printers[0], None
        return None, tool_error(
            "multiple printers configured; pass 'printer' with a slug. Available: "
            + ", ".join(p["slug"] for p in printers))
    try:
        return client.require_printer(slug), None
    except Exception as exc:  # noqa: BLE001
        return None, tool_error(str(exc))


def _handle_list(args: dict, **_: Any) -> str:
    return tool_result({"printers": client.list_printers()})


def _handle_status(args: dict, **_: Any) -> str:
    cfg, err = _printer_arg(args)
    if err:
        return err
    try:
        return tool_result(client.printer_status(cfg))
    except Exception as exc:  # noqa: BLE001
        return tool_error(f"status failed for '{cfg['slug']}': {exc}")


def _handle_cmd(args: dict, action: str, **_: Any) -> str:
    cfg, err = _printer_arg(args)
    if err:
        return err
    try:
        return tool_result(client.send_command(cfg, action))
    except Exception as exc:  # noqa: BLE001
        return tool_error(f"'{action}' failed for '{cfg['slug']}': {exc}")


def _handle_speed(args: dict, **_: Any) -> str:
    cfg, err = _printer_arg(args)
    if err:
        return err
    level = args.get("level", 2)
    try:
        return tool_result(client.send_command(cfg, "speed", str(level)))
    except Exception as exc:  # noqa: BLE001
        return tool_error(f"speed change failed for '{cfg['slug']}': {exc}")


def _handle_filament(args: dict, **_: Any) -> str:
    cfg, err = _printer_arg(args)
    if err:
        return err
    action = f"filament_{args.get('action', 'load')}"
    try:
        return tool_result(client.send_command(cfg, action))
    except Exception as exc:  # noqa: BLE001
        return tool_error(f"filament action failed for '{cfg['slug']}': {exc}")


def _handle_monitor(args: dict, **_: Any) -> str:
    try:
        return tool_result(monitor.check_printers())
    except Exception as exc:  # noqa: BLE001
        return tool_error(f"monitor check failed: {exc}")


# ──────────────────────────────────────────────────────────────────────
# CLI + slash command
# ──────────────────────────────────────────────────────────────────────

_ACTIONS = ("list", "status", "pause", "resume", "stop", "speed", "filament", "monitor")


def _run(argv: list[str]) -> str:
    action = (argv[0] if argv else "help").lower()
    printer = argv[1] if len(argv) > 1 else None
    value = argv[2] if len(argv) > 2 else None

    if action in ("help", "-h", "--help", ""):
        return ("bambulab — Bambu Lab printer control (local MQTT)\n"
                "  hermes bambu list\n"
                "  hermes bambu status [slug]\n"
                "  hermes bambu pause|resume|stop [slug]\n"
                "  hermes bambu speed [slug] <1-4>   (1 silent, 2 standard, 3 sport, 4 ludicrous)\n"
                "  hermes bambu filament [slug] <load|unload>\n"
                "  hermes bambu monitor               # poll all, report alerts")

    if action == "list":
        return json.dumps(client.list_printers(), indent=2)

    if action == "monitor":
        return json.dumps(monitor.check_printers(), indent=2, default=str)

    if action not in ("status", "pause", "resume", "stop", "speed", "filament"):
        return f"unknown action {action!r}\n\n{_run(['help'])}"

    try:
        if printer:
            cfg = client.require_printer(printer)
        else:
            printers = client.list_printers()
            if not printers:
                return "no printers configured — add them in the Bambu Lab dashboard tab"
            if len(printers) > 1:
                return "multiple printers configured; pass a slug: " + ", ".join(p["slug"] for p in printers)
            cfg = printers[0]
    except Exception as exc:  # noqa: BLE001
        return f"error: {exc}"

    try:
        if action == "status":
            return json.dumps(client.printer_status(cfg), indent=2, default=str)
        if action in ("pause", "resume", "stop"):
            return json.dumps(client.send_command(cfg, action))
        if action == "speed":
            if not value or not str(value).isdigit():
                return "usage: hermes bambu speed <slug> <1-4>"
            return json.dumps(client.send_command(cfg, "speed", value))
        if action == "filament":
            kind = (value or "load").lower()
            if kind not in ("load", "unload"):
                return "usage: hermes bambu filament <slug> <load|unload>"
            return json.dumps(client.send_command(cfg, f"filament_{kind}"))
    except Exception as exc:  # noqa: BLE001
        return f"error: {exc}"
    return "unknown action"


def _cli_setup(parser) -> None:
    parser.add_argument("args", nargs="*", help="e.g.: status h2s | monitor | speed h2s 3")


def _cli_handler(args) -> None:
    print(_run(list(getattr(args, "args") or [])))


def _handle_slash(raw_args: str) -> Optional[str]:
    return _run(raw_args.strip().split())


# ──────────────────────────────────────────────────────────────────────
# Registration
# ──────────────────────────────────────────────────────────────────────

def register(ctx: Any) -> None:
    """Plugin entry point — tools, CLI command, and slash command."""
    ctx.register_tool(name="bambu_list", toolset="bambulab", schema=LIST_SCHEMA,
                      handler=_handle_list,
                      description="List configured Bambu Lab printers.")
    ctx.register_tool(name="bambu_status", toolset="bambulab", schema=STATUS_SCHEMA,
                      handler=_handle_status,
                      description="Live status of a Bambu Lab printer over local MQTT.")
    ctx.register_tool(name="bambu_pause", toolset="bambulab", schema=CMD_SCHEMA,
                      handler=lambda a, **kw: _handle_cmd(a, "pause", **kw),
                      description="Pause a Bambu Lab print.")
    ctx.register_tool(name="bambu_resume", toolset="bambulab", schema=RESUME_SCHEMA,
                      handler=lambda a, **kw: _handle_cmd(a, "resume", **kw),
                      description="Resume a paused Bambu Lab print.")
    ctx.register_tool(name="bambu_stop", toolset="bambulab", schema=STOP_SCHEMA,
                      handler=lambda a, **kw: _handle_cmd(a, "stop", **kw),
                      description="Stop (cancel) a Bambu Lab print.")
    ctx.register_tool(name="bambu_speed", toolset="bambulab", schema=SPEED_SCHEMA,
                      handler=_handle_speed,
                      description="Set Bambu Lab print speed level (1-4).")
    ctx.register_tool(name="bambu_filament", toolset="bambulab", schema=FILAMENT_SCHEMA,
                      handler=_handle_filament,
                      description="Load/unload the external filament spool.")
    ctx.register_tool(name="bambu_monitor", toolset="bambulab", schema=MONITOR_SCHEMA,
                      handler=_handle_monitor,
                      description="Poll all printers once; report transition alerts.")

    ctx.register_cli_command(
        "bambu", "Monitor/control Bambu Lab printers (local MQTT)",
        _cli_setup, _cli_handler,
        description="Bambu Lab printers: list/status/pause/resume/stop/speed/filament/monitor")
    ctx.register_command(
        "bambu", _handle_slash,
        description="Bambu Lab printer control (list/status/pause/resume/stop/speed/filament/monitor)",
        args_hint="[list|status|pause|resume|stop|speed|filament|monitor] [slug] [value]")
    logger.info("bambulab plugin registered (7 tools, CLI 'hermes bambu', /bambu, dashboard tab)")
