"""bambulab plugin — monitor/alert state machine.

Polls every enabled printer, detects state transitions, and returns
Discord-ready alert messages. Last-seen state persists in ``state.json``
under the plugin's data dir, so alerts fire on *transitions*, not every poll.

Intended to run from a Hermes cron job (e.g. every 60 s) or via
``hermes bambu monitor`` / ``/bambu monitor``. Alert-only by design:
this module never sends control commands.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from . import client

logger = logging.getLogger(__name__)

# GcodeState enum values (OpenBambuAPI / Bambu Lab protocol).
GCOD_STATES = {
    0: "init", 1: "preparing", 2: "running", 3: "paused",
    4: "finished", 5: "failed", 6: "paused_for_user", 7: "updating",
}
# Printer print-error codes worth alerting on (4020 = filament runout).
ERROR_CODES = {4020: "filament runout"}


def _load_state() -> dict[str, Any]:
    try:
        with open(client.state_path(), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _save_state(state: dict[str, Any]) -> None:
    try:
        path = client.state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
    except Exception as exc:
        logger.debug("bambulab: could not save monitor state: %s", exc)


def _state_name(value: Any) -> Any:
    if isinstance(value, int):
        return GCOD_STATES.get(value, value)
    return value


def _format_alert(p: dict[str, Any], info: dict[str, Any], events: list[str]) -> str:
    name = p.get("name") or p["slug"]
    parts = []
    if "finished" in events:
        parts.append("print FINISHED 🎉")
    if "failed" in events:
        parts.append("print FAILED ⚠️")
    if "filament_out" in events:
        parts.append("filament runout 🧵")
    if "hms_error" in events:
        parts.append("HMS error(s): " + ", ".join(info.get("hms") or []))
    extra = f" — file: {info['file']}" if info.get("file") else ""
    return f"🖨️ *{name}* ({p['ip']}): " + " | ".join(parts) + extra


def check_printers() -> dict[str, Any]:
    """Poll all enabled printers once; return {alerts, printers, checked_at}."""
    state = _load_state()
    results: list[dict[str, Any]] = []
    alerts: list[str] = []

    for p in client.list_printers():
        if not p["enabled"]:
            continue
        if not p["has_code"]:
            results.append({"printer": p["slug"], "skipped": "no access code"})
            continue
        try:
            info = client.printer_status(p)
        except Exception as exc:  # noqa: BLE001 - report per-printer, keep polling others
            results.append({"printer": p["slug"], "error": str(exc)[:200]})
            continue

        prev = state.get(p["slug"]) or {}
        cur_state = info.get("gcode_state")
        cur_hms = list(info.get("hms") or [])
        cur_err = int(info.get("error_code") or 0)

        events: list[str] = []
        if isinstance(cur_state, int) and cur_state == 4 and prev.get("gcode_state") != 4:
            events.append("finished")
        if isinstance(cur_state, int) and cur_state == 5 and prev.get("gcode_state") != 5:
            events.append("failed")
        if cur_err in ERROR_CODES and int(prev.get("error_code") or 0) != cur_err:
            events.append("filament_out")
        if any(h not in (prev.get("hms") or []) for h in cur_hms):
            events.append("hms_error")

        state[p["slug"]] = {
            "gcode_state": cur_state,
            "hms": cur_hms,
            "error_code": cur_err,
            "seen_at": datetime.now(timezone.utc).isoformat(),
        }
        if events:
            alerts.append(_format_alert(p, info, events))
        results.append({
            "printer": p["slug"],
            "state": _state_name(cur_state),
            "progress": info.get("progress"),
            "alerts": events,
        })

    _save_state(state)
    return {
        "alerts": alerts,
        "printers": results,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
