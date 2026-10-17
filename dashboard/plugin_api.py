"""Bambu Lab dashboard plugin — backend API routes.

Mounted at /api/plugins/bambulab/ by the dashboard plugin system.

Storage:
* printer records (non-secret) → plugins.entries.bambulab.settings.printers
* access codes (secret)        → BAMBLAB_KEY_<SLUG> in .env (write via the
  credential lifecycle, read via agent.secret_scope — never returned to clients;
  only a has_code flag is exposed).
"""
from __future__ import annotations

import asyncio
import importlib.util
import re
import threading
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

PLUGIN_ID = "bambulab"
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")

_client_lock = threading.Lock()
_client_mod: Optional[Any] = None


def _get_client() -> Any:
    """Load the plugin's client.py standalone (the dashboard loads this file
    by path, so relative package imports are not guaranteed)."""
    global _client_mod
    with _client_lock:
        if _client_mod is None:
            path = Path(__file__).resolve().parents[1] / "client.py"
            spec = importlib.util.spec_from_file_location("bambulab_client_standalone", str(path))
            if spec is None or spec.loader is None:
                raise RuntimeError(f"cannot load {path}")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            _client_mod = mod
        return _client_mod


# ──────────────────────────────────────────────────────────────────────
# Models
# ──────────────────────────────────────────────────────────────────────

class PrinterIn(BaseModel):
    slug: str = ""
    name: str = ""
    ip: str = ""
    serial: str = ""
    enabled: bool = True
    code: Optional[str] = None  # blank = keep existing code


class PrintersIn(BaseModel):
    printers: list[PrinterIn]


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _stored_printers() -> list[dict[str, Any]]:
    try:
        from hermes_cli.config import load_config_readonly
        cfg = load_config_readonly() or {}
    except Exception:
        return []
    entries = (cfg.get("plugins") or {}).get("entries") or {}
    return ((entries.get(PLUGIN_ID) or {}).get("settings") or {}).get("printers") or []


def _has_code(slug: str) -> bool:
    try:
        from agent.secret_scope import get_secret
        return bool(get_secret(f"BAMBLAB_KEY_{slug.upper()}"))
    except Exception:
        return False


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", str(value or "").strip().lower()).strip("-")


# ──────────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────────

@router.get("/printers")
async def get_printers() -> dict[str, Any]:
    """List printers. Access codes are NEVER returned — only a has_code flag."""
    out = []
    for p in _stored_printers():
        if not isinstance(p, dict):
            continue
        slug = _slugify(p.get("slug") or p.get("name") or p.get("ip") or "")
        out.append({
            "slug": slug,
            "name": str(p.get("name") or ""),
            "ip": str(p.get("ip") or ""),
            "serial": str(p.get("serial") or ""),
            "enabled": bool(p.get("enabled", True)),
            "has_code": _has_code(slug) if slug else False,
        })
    return {"printers": out, "version": "1.0.0"}


@router.post("/printers")
async def save_printers(body: PrintersIn) -> dict[str, Any]:
    """Replace the printer list. Non-secret fields → plugin settings;
    non-blank codes → .env via the credential lifecycle; blank code = keep;
    removed rows have their code removed from .env."""
    from hermes_cli.config import remove_env_value
    from hermes_cli.credential_lifecycle import save_provider_env_credential
    from hermes_cli.plugins_state import save_plugin_setting

    previous_slugs = {_slugify(p.get("slug") or p.get("ip") or "") for p in _stored_printers()}
    previous_slugs.discard("")

    stored: list[dict[str, Any]] = []
    for p in body.printers:
        slug = _slugify(p.slug or p.ip)
        if not slug:
            raise HTTPException(status_code=400, detail="each printer needs a slug (or an IP to derive one)")
        if not _SLUG_RE.match(slug):
            raise HTTPException(status_code=400, detail=f"invalid slug: {slug!r}")
        if not (p.ip.strip() and p.serial.strip()):
            continue  # skip rows still being typed (incomplete)
        stored.append({
            "slug": slug,
            "name": str(p.name or "").strip(),
            "ip": str(p.ip).strip(),
            "serial": str(p.serial).strip(),
            "enabled": bool(p.enabled),
        })
        if p.code and p.code.strip():
            save_provider_env_credential(f"BAMBLAB_KEY_{slug.upper()}", p.code.strip())

    save_plugin_setting(PLUGIN_ID, ("printers",), stored)

    kept = {s["slug"].upper() for s in stored}
    for old in previous_slugs:
        if old not in kept:
            try:
                remove_env_value(f"BAMBLAB_KEY_{old}")
            except Exception:
                pass  # stale code left behind; harmless (unreferenced)

    return {"ok": True, "count": len(stored)}


@router.post("/test/{slug}")
async def test_printer(slug: str) -> dict[str, Any]:
    """Connect to one printer with its stored code; report a snapshot on success,
    the exact error on failure. Read-only — no control commands are sent."""
    mod = _get_client()
    try:
        cfg = mod.require_printer(_slugify(slug))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=str(exc))
    if not cfg["has_code"]:
        raise HTTPException(status_code=400, detail="no access code set for this printer — enter it in the masked field")
    try:
        info = await asyncio.wait_for(asyncio.to_thread(mod.printer_status, cfg), timeout=45)
        return {
            "ok": True,
            "printer": cfg["slug"],
            "state": info.get("gcode_state"),
            "progress": info.get("progress"),
            "nozzle": info.get("nozzle"),
            "bed": info.get("bed"),
            "file": info.get("file"),
            "hms": info.get("hms"),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "printer": cfg["slug"], "error": str(exc)[:300]}


@router.get("/status")
async def status() -> dict[str, Any]:
    """Live status for every enabled printer (read-only, concurrent)."""
    mod = _get_client()
    printers = mod.list_printers()

    async def one(p: dict[str, Any]) -> dict[str, Any]:
        if not p["enabled"]:
            return {"printer": p["slug"], "skipped": "disabled"}
        if not p["has_code"]:
            return {"printer": p["slug"], "skipped": "no access code set"}
        try:
            return await asyncio.wait_for(asyncio.to_thread(mod.printer_status, p), timeout=45)
        except Exception as exc:  # noqa: BLE001
            return {"printer": p["slug"], "error": str(exc)[:200]}

    results = list(await asyncio.gather(*(one(p) for p in printers)))
    return {"printers": results}
