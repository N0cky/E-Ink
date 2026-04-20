"""
Modul-Entdeckung und -Registry für PlexImageE-Ink.

Beim Start scannt das Framework automatisch das Verzeichnis modules/.
Jedes Unterverzeichnis mit einer __init__.py, die ein `module`-Attribut
(PlexInkModule-Instanz) exportiert, wird als Modul registriert.

Ein manueller Rescan ist über reload_modules() möglich (z. B. per API-Endpunkt).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from app.module_base import PlexInkModule
from app.logger import get_logger

log = get_logger(__name__)

MODULES_DIR = Path(__file__).resolve().parents[1] / "modules"

_registry: list[PlexInkModule] = []


# ---------------------------------------------------------------------------
# Internes Laden
# ---------------------------------------------------------------------------

def _load_one(module_dir: Path) -> PlexInkModule | None:
    """Lädt ein einzelnes Modul aus module_dir/__init__.py."""
    init_py = module_dir / "__init__.py"
    if not init_py.exists():
        return None

    pkg_name = f"modules.{module_dir.name}"
    try:
        spec = importlib.util.spec_from_file_location(
            pkg_name,
            init_py,
            submodule_search_locations=[str(module_dir)],
        )
        if spec is None or spec.loader is None:
            log.warning(f"Kein importlib-Spec für Modul '{module_dir.name}'")
            return None

        mod = importlib.util.module_from_spec(spec)
        sys.modules[pkg_name] = mod
        spec.loader.exec_module(mod)  # type: ignore[union-attr]

        instance = getattr(mod, "module", None)
        if instance is None:
            log.warning(f"Modul '{module_dir.name}': kein 'module'-Attribut in __init__.py")
            return None
        if not isinstance(instance, PlexInkModule):
            log.warning(
                f"Modul '{module_dir.name}': 'module' ist keine PlexInkModule-Instanz "
                f"(Typ: {type(instance).__name__})"
            )
            return None

        return instance

    except Exception as exc:
        log.error(f"Fehler beim Laden von Modul '{module_dir.name}': {exc}", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Öffentliche API
# ---------------------------------------------------------------------------

def discover_modules(modules_dir: Path | None = None) -> list[PlexInkModule]:
    """
    Scannt MODULES_DIR nach Modulordnern und gibt geladene Instanzen zurück.
    Sortiert nach MODULE_PRIORITY aufsteigend, dann alphabetisch nach MODULE_NAME.
    """
    modules_dir = modules_dir or MODULES_DIR
    if not modules_dir.exists():
        log.warning(f"Module-Verzeichnis nicht gefunden: {modules_dir}")
        return []

    found: list[PlexInkModule] = []
    for entry in sorted(modules_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        instance = _load_one(entry)
        if instance is not None:
            found.append(instance)
            log.info(
                f"Modul geladen: [{instance.MODULE_ID}] '{instance.MODULE_NAME}' "
                f"(prio={instance.MODULE_PRIORITY})"
            )

    validated: list[PlexInkModule] = []
    seen_module_ids: dict[str, str] = {}
    seen_field_names: dict[str, str] = {}

    for instance in sorted(found, key=lambda m: (m.MODULE_PRIORITY, m.MODULE_NAME)):
        module_id = (instance.MODULE_ID or "").strip()
        if not module_id:
            log.error(f"Modul '{instance.MODULE_NAME}' verworfen: leere MODULE_ID")
            continue
        if module_id in seen_module_ids:
            log.error(
                f"Modul '{instance.MODULE_NAME}' verworfen: doppelte MODULE_ID '{module_id}' "
                f"(bereits verwendet von '{seen_module_ids[module_id]}')"
            )
            continue

        local_fields: set[str] = set()
        duplicate_fields = False
        for field in instance.SETTINGS_FIELDS:
            field_name = str(field.get("name", "")).strip()
            if not field_name:
                log.error(f"Modul '{module_id}' verworfen: SETTINGS_FIELDS enthält Feld ohne Namen")
                duplicate_fields = True
                break
            if field_name in local_fields:
                log.error(f"Modul '{module_id}' verworfen: doppeltes Feld '{field_name}' im Modul")
                duplicate_fields = True
                break
            owner = seen_field_names.get(field_name)
            if owner is not None:
                log.error(
                    f"Modul '{module_id}' verworfen: Feldname '{field_name}' kollidiert mit Modul '{owner}'"
                )
                duplicate_fields = True
                break
            local_fields.add(field_name)

        if duplicate_fields:
            continue

        seen_module_ids[module_id] = instance.MODULE_NAME
        for field_name in local_fields:
            seen_field_names[field_name] = module_id
        validated.append(instance)

    return validated


def reload_modules(modules_dir: Path | None = None) -> list[PlexInkModule]:
    """
    Alle Module neu entdecken ohne Server-Neustart.
    Entfernt vorherige Einträge aus sys.modules damit __init__.py
    frisch ausgeführt wird.
    """
    global _registry

    # Alte Module-Pakete aus sys.modules entfernen
    for key in list(sys.modules):
        if key.startswith("modules."):
            del sys.modules[key]

    _registry = discover_modules(modules_dir)
    log.info(f"Module-Registry neu geladen: {[m.MODULE_ID for m in _registry]}")
    return list(_registry)


def get_modules() -> list[PlexInkModule]:
    """Alle registrierten Module (sortiert nach Priorität)."""
    return list(_registry)


def get_priority_modules() -> list[PlexInkModule]:
    """Prioritätsmodule (MODULE_PRIORITY < 10), z. B. Plex."""
    return [m for m in _registry if m.MODULE_PRIORITY < 10]


def get_idle_modules() -> list[PlexInkModule]:
    """Idle-Module (MODULE_PRIORITY >= 10) – werden rotiert."""
    return [m for m in _registry if m.MODULE_PRIORITY >= 10]


def get_module_by_id(module_id: str) -> PlexInkModule | None:
    for m in _registry:
        if m.MODULE_ID == module_id:
            return m
    return None


def get_module_info_list() -> list[dict]:
    """Kompakte Metadaten aller Module für Dashboard / API."""
    return [
        {
            "id":          m.MODULE_ID,
            "name":        m.MODULE_NAME,
            "description": m.MODULE_DESCRIPTION,
            "priority":    m.MODULE_PRIORITY,
            "kind":        "priority" if m.MODULE_PRIORITY < 10 else "idle",
        }
        for m in _registry
    ]


def get_module_field_options(module_id: str, field_name: str, env: dict[str, str]) -> list | None:
    mod = get_module_by_id(module_id)
    if mod is None:
        return None
    return mod.get_field_options(field_name, env)
