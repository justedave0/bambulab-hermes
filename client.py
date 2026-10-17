"""bambulab plugin — printer access layer.

Wraps the open-source ``bambulabs_api`` (PyPI: bambulabs-api) for local/LAN
mode: ``bl.Printer(ip_address, access_code, serial)`` over MQTT TLS :8883.

Storage layout (share-safe):
* printer records (name / slug / ip / serial / enabled) — non-secret, stored in
  ``plugins.entries.bambulab.settings.printers`` via ``save_plugin_setting``.
* access codes — secrets, stored as ``BAMBLAB_KEY_<SLUG>`` in ``~/.hermes/.env``
  and read ONLY through ``agent.secret_scope.get_secret``. Never in config.yaml,
  never in this repo, never returned by the dashboard API (only a ``has_code`` flag).
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

PLUGIN_ID = "bambulab"
_KEY_PREFIX = "BAMBLAB_KEY_"
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
# Seconds to wait after MQTT connect for printer state to arrive (README pattern).
_STATE_SETTLE_S = 2.5
_CALL_TIMEOUT_S = 30.0


def hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes")).expanduser()


def state_path() -> Path:
    return hermes_home() / "plugins" / PLUGIN_ID / "state.json"


def validate_slug(slug: Any) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", str(slug or "").strip().lower()).strip("-")
    if not _SLUG_RE.match(slug):
        raise ValueError(f"invalid printer slug: {slug!r} (use a-z, 0-9, '-')")
    return slug


def key_env_name(slug: str) -> str:
    return _KEY_PREFIX + validate_slug(slug).upper()


def code_for(slug: str) -> Optional[str]:
    """Resolve a printer's access code from the secret scope (never os.environ)."""
    try:
        from agent.secret_scope import get_secret
        return get_secret(key_env_name(slug)) or None
    except Exception:
        return None


def list_printers() -> list[dict[str, Any]]:
    """All configured printers with a ``has_code`` flag. Never returns code values."""
    try:
        from hermes_cli.config import load_config_readonly
        cfg = load_config_readonly() or {}
    except Exception:
        return []
    entries = (cfg.get("plugins") or {}).get("entries") or {}
    settings = (entries.get(PLUGIN_ID) or {}).get("settings") or {}
    printers = settings.get("printers") or []
    out: list[dict[str, Any]] = []
    for p in printers:
        if not isinstance(p, dict) or not p.get("ip") or not p.get("serial"):
            continue  # skip incomplete rows (still being typed in the dashboard)
        try:
            slug = validate_slug(p.get("slug") or p["ip"])
        except ValueError:
            continue
        out.append({
            "slug": slug,
            "name": str(p.get("name") or ""),
            "ip": str(p["ip"]).strip(),
            "serial": str(p["serial"]).strip(),
            "enabled": bool(p.get("enabled", True)),
            "has_code": bool(code_for(slug)),
        })
    return out


def require_printer(slug: str) -> dict[str, Any]:
    slug = validate_slug(slug)
    for p in list_printers():
        if p["slug"] == slug:
            return p
    raise KeyError(f"printer '{slug}' not configured — add it in the Bambu Lab dashboard tab")


def _with_timeout(fn: Callable[[], Any], seconds: float = _CALL_TIMEOUT_S) -> Any:
    """Run a blocking printer operation on a daemon thread with a hard deadline."""
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["value"] = fn()
        except Exception as exc:  # noqa: BLE001 - reported back to the caller
            box["error"] = exc

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(seconds)
    if t.is_alive():
        raise TimeoutError(f"printer timed out after {seconds:.0f}s")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _safe_call(fn: Callable[[], Any], default: Any = None) -> Any:
    try:
        return fn()
    except Exception:
        return default


def _connect(cfg: dict[str, Any]):
    """Create and connect a Printer; raises a readable error when no code is set."""
    import bambulabs_api as bl
    code = code_for(cfg["slug"])
    if not code:
        raise RuntimeError(
            f"no access code for '{cfg['slug']}' — enter it in the Bambu Lab dashboard tab (masked field)")
    printer = bl.Printer(str(cfg["ip"]), code, str(cfg["serial"]))
    printer.connect()
    time.sleep(_STATE_SETTLE_S)
    return printer


def _hms_is_error(code: Any) -> bool:
    """An HMS code like ``0000_0000_0000_0000`` is clean; any non-zero group is an error."""
    parts = str(code or "").split("_")
    for part in parts:
        if part:
            try:
                if int(part) != 0:
                    return True
            except ValueError:
                return True
    return False


def printer_status(cfg: dict[str, Any]) -> dict[str, Any]:
    """Connect, read a compact live snapshot, disconnect. Read-only."""
    def work() -> dict[str, Any]:
        p = _connect(cfg)
        try:
            def _gs() -> Any:
                try:
                    st = p.get_printer_state()
                    try:
                        return int(st)
                    except Exception:
                        return str(st)
                except Exception:
                    return None

            def _hms_list() -> list[str]:
                try:
                    dump = p.mqtt_dump() or {}
                except Exception:
                    dump = {}
                pr = (dump.get("print") or {}) if isinstance(dump, dict) else {}
                out = []
                for h in pr.get("hms") or []:
                    if isinstance(h, dict) and _hms_is_error(h.get("hms")):
                        out.append(str(h.get("hms")))
                return out

            return {
                "printer": cfg["slug"],
                "name": cfg.get("name") or None,
                "ip": cfg["ip"],
                "serial": cfg["serial"],
                "gcode_state": _gs(),
                "progress": _safe_call(p.get_percentage),
                "file": _safe_call(p.get_file_name),
                "layers": [_safe_call(p.current_layer_num), _safe_call(p.total_layer_num)],
                "nozzle": [_safe_call(p.get_nozzle_temperature),
                           _safe_call(p.get_nozzle_temperature_target)],
                "bed": [_safe_call(p.get_bed_temperature),
                        _safe_call(p.get_bed_temperature_target)],
                "chamber": _safe_call(p.get_chamber_temperature),
                "speed": _safe_call(p.get_print_speed),
                "error_code": _safe_call(p.print_error_code, 0) or 0,
                "hms": _hms_list(),
                "wifi": _safe_call(p.wifi_signal),
                "connected": True,
            }
        finally:
            _safe_call(p.disconnect)

    return _with_timeout(work)


_ACTIONS = {
    "pause": lambda p: p.pause_print(),
    "resume": lambda p: p.resume_print(),
    "stop": lambda p: p.stop_print(),
    "filament_load": lambda p: p.load_filament_spool(),
    "filament_unload": lambda p: p.unload_filament_spool(),
    "light_on": lambda p: p.turn_light_on(),
    "light_off": lambda p: p.turn_light_off(),
}


def send_command(cfg: dict[str, Any], action: str, value: str = "") -> dict[str, Any]:
    """Send a control command. ``speed`` uses ``value`` = 1..4 (silent/standard/sport/ludicrous)."""
    action = str(action or "").strip().lower()
    if action == "speed":
        lvl = int(value) if str(value).strip().isdigit() else 2
        lvl = max(1, min(4, lvl))
        fn = lambda p: p.set_print_speed(lvl)  # noqa: E731
    elif action in _ACTIONS:
        fn = _ACTIONS[action]  # type: ignore[assignment]
    else:
        raise ValueError(f"unknown action {action!r} (choose: pause, resume, stop, speed, filament_load, filament_unload, light_on, light_off)")

    def work() -> dict[str, Any]:
        p = _connect(cfg)
        try:
            ok = fn(p)
            return {"ok": bool(ok), "action": action, "printer": cfg["slug"]}
        finally:
            _safe_call(p.disconnect)

    return _with_timeout(work)
