# Module Guide

## Ziel

Neue Module sollen ohne Eingriffe an vielen zentralen Stellen eingebunden werden koennen.
Das Projekt nutzt dafuer eine modulare Registry unter `modules/`.

Ein Modul kann:

- Inhalte laden
- ein Bild rendern
- eigene Settings deklarieren
- eigene Settings validieren
- Runtime-Informationen fuer die Settings-Seite liefern
- dynamische Feldoptionen bereitstellen
- optionale API-Aktionen anbieten
- Health-Informationen melden
- eine eigene Wake-Empfehlung fuer `meta.json` liefern


## Verzeichnisstruktur

Ein Modul liegt in `modules/<module_id>/`.

Minimales Beispiel:

```text
modules/
  example/
    __init__.py
    renderer.py
    data_source.py
```


## Pflichtbestandteile

Jedes Modul exportiert in `__init__.py` ein Attribut `module`.

Dieses Objekt muss eine Instanz einer Klasse sein, die von `PlexInkModule` erbt:

```python
from __future__ import annotations

from PIL import Image

from app.module_base import PlexInkModule


class ExampleModule(PlexInkModule):
    MODULE_ID = "example"
    MODULE_NAME = "Example"
    MODULE_DESCRIPTION = "Beispielmodul"
    MODULE_PRIORITY = 120

    SETTINGS_FIELDS = []
    SETTINGS_GROUPS = []

    def is_enabled(self, env: dict[str, str]) -> bool:
        return True

    def fetch_content(self, env: dict[str, str]):
        return {"text": "Hallo Welt"}

    def render(self, env: dict[str, str], content) -> Image.Image:
        from PIL import Image
        return Image.new("RGB", (1600, 1200), (255, 255, 255))


module = ExampleModule()
```


## Prioritaet

- `MODULE_PRIORITY < 10`: Prioritaetsmodul
  - Beispiel: Plex oder Steam
  - wird vor Idle-Modulen ausgewertet
- `MODULE_PRIORITY >= 10`: Idle-Modul
  - wird in die Idle-Rotation aufgenommen

Je kleiner der Wert, desto hoeher die Prioritaet.


## Registry

Die Registry scannt automatisch `modules/*/__init__.py`.

Wichtige Regeln:

- `MODULE_ID` muss eindeutig sein
- Settings-Feldnamen muessen global eindeutig sein
- kaputte Module werden geloggt und uebersprungen

Die zentrale Registry liegt in:

- [module_registry.py](/C:/Users/tobia/Documents/PlexImageE-Ink/app/module_registry.py)


## Settings deklarieren

Module definieren ihre eigenen Felder in `SETTINGS_FIELDS`.
Framework-Felder bleiben in `app/config.py`.

Beispiel:

```python
SETTINGS_FIELDS = [
    {
        "name": "EXAMPLE_ENABLED",
        "label": "Beispiel aktiv",
        "type": "select",
        "default": "true",
        "wide": False,
        "options": [("true", "Aktiv"), ("false", "Inaktiv")],
        "help": "Aktiviert das Beispielmodul.",
    },
]
```

Typische Feldtypen im Projekt:

- `text`
- `password`
- `number`
- `select`
- `checkbox_group`
- `priority_list`

Optional koennen Felder `default`, `min`, `max`, `placeholder`, `help`, `options`, `datalist_url` enthalten.


## Settings gruppieren

Mit `SETTINGS_GROUPS` lassen sich Felder in der Settings-Seite strukturieren:

```python
SETTINGS_GROUPS = [
    {
        "title": "Allgemein",
        "desc": "Grundkonfiguration des Moduls.",
        "fields": ["EXAMPLE_ENABLED"],
    },
]
```


## Laufzeit-Settings lesen

Module sollen ihre Werte generisch ueber `app.config` lesen, nicht ueber fest verdrahtete `cfg.<feldname>`-Attribute.

Empfohlene Helfer:

- `get_setting(name, default="")`
- `get_int_setting(name, default, min_val=None, max_val=None)`
- `get_bool_setting(name, default=False)`
- `get_csv_setting(name)`
- `get_cfg()` fuer Framework-Werte wie Rendergroesse, Theme, Rotation

Beispiel:

```python
from app.config import get_bool_setting, get_setting

enabled = get_bool_setting("EXAMPLE_ENABLED", True)
title = get_setting("EXAMPLE_TITLE", "Standardtitel")
```


## Render-Services

Fuer Renderer und modulnahe Helfer gibt es Service-Dataclasses:

- `ModuleFetchServices`
- `ModuleRenderServices`

Definiert in:

- [module_services.py](/C:/Users/tobia/Documents/PlexImageE-Ink/app/module_services.py)

Damit lassen sich gemeinsame Framework-Funktionen sauber an Renderer uebergeben, ohne alte Idle-Kompatibilitaetsschichten.


## Optionale Hooks

`PlexInkModule` bietet zusaetzlich optionale Hooks:

### `should_refresh(self, env)`

Erzwingt ein Re-Rendern trotz gleichem `state_key`.

### `get_state_key(self, content)`

Liefert einen Fingerprint fuer den aktuellen Inhalt.

### `validate_settings(self, updates, env)`

Modul-spezifische Validierung.
Rueckgabe: Liste von Fehlermeldungen.

### `get_runtime_summary(self, env)`

Zusatzinfos fuer die Runtime-Karten in den Settings.

### `get_field_options(self, field_name, env)`

Dynamische Optionen fuer Felder, z. B. API-basierte Vorschlagslisten.

### `handle_api_action(self, action, env)`

Optionale modulare API-Aktion.
Rueckgabe: `(payload, status_code)` oder `None`.

### `get_health_status(self, env)`

Optionale Moduldiagnose fuer `/health` und `/api/status`.

### `get_next_wake_seconds(self, env, state)`

Optionale modul-spezifische Wake-Empfehlung fuer `/meta.json`.

- Rueckgabe `None`: Framework-Standardlogik verwenden
- Rueckgabe `int`: Modul bestimmt `next_wake_sec` selbst

Das ist der richtige Hook, wenn ein Modul ein eigenes Anzeigetempo oder
Aktualisierungsintervall braucht, das vom allgemeinen Idle-Takt abweicht.

Beispiel:

```python
def get_next_wake_seconds(self, env: dict[str, str], state: str) -> int | None:
    if env.get("EXAMPLE_INTERVAL_MODE", "idle_rotation") == "custom":
        raw = env.get("EXAMPLE_INTERVAL_SECONDS", "300").strip()
        if raw.isdigit():
            return max(30, min(86400, int(raw)))
    return None
```

### `get_background_poll_seconds(self, env)`

Optionales Poll-Intervall fuer den Background-Worker.

- Rueckgabe `None`: Framework-Standardlogik verwenden
- Rueckgabe `int`: Modul kann haeufiger geprueft werden als das globale `REFRESH_INTERVAL`

Das ist sinnvoll, wenn ein Modul ein eigenes, kuerzeres Wechselintervall hat und
der Server deshalb auch haeufiger neu rendern koennen muss.

Beispiel:

```python
def get_background_poll_seconds(self, env: dict[str, str]) -> int | None:
    if env.get("EXAMPLE_INTERVAL_MODE", "idle_rotation") != "custom":
        return None
    raw = env.get("EXAMPLE_INTERVAL_SECONDS", "300").strip()
    if raw.isdigit():
        return max(30, min(86400, int(raw)))
    return None
```


## Dynamische Feldoptionen

Wenn ein Feld Optionen dynamisch laden soll:

1. Feld mit `datalist_url` oder passender Frontend-Logik definieren
2. `get_field_options()` im Modul implementieren
3. optional ueber `/api/module-field-options/<module_id>/<field_name>` abrufen

Beispiel aus dem DWD-Modul:

- Feld: `DWD_UV_CITY`
- Quelle: `get_field_options("DWD_UV_CITY", env)`


## Modul-API-Aktionen

Fuer modulare Hilfsendpunkte gibt es:

- `/api/module-action/<module_id>/<action>`

Beispiel:

```python
def handle_api_action(self, action: str, env: dict[str, str]):
    if action != "example-data":
        return None
    return {"items": ["a", "b", "c"]}, 200
```


## Health-Status

Module koennen Health-Infos liefern:

```python
def get_health_status(self, env: dict[str, str]) -> dict[str, object] | None:
    return {
        "ok": True,
        "enabled": self.is_enabled(env),
    }
```

Diese Infos fliessen in:

- `/health`
- `/api/status`


## Validierung

Framework-Validierung und Modul-Validierung laufen zusammen.

Das Modul sollte nur Regeln pruefen, die wirklich zu ihm gehoeren.

Beispiele:

- Pflichtkombinationen von Feldern
- gueltige Select-Werte
- Formatpruefungen fuer IDs oder URLs


## Tests

Fuer die Modularchitektur gibt es aktuell zwei Basistests:

- [test_module_registry.py](/C:/Users/tobia/Documents/PlexImageE-Ink/tests/test_module_registry.py)
- [test_settings_validation.py](/C:/Users/tobia/Documents/PlexImageE-Ink/tests/test_settings_validation.py)

Empfehlung fuer neue Module:

- mindestens ein Registry-/Lade-Szenario absichern
- mindestens eine Validierungsregel testen


## Praktische Checkliste fuer neue Module

1. Ordner unter `modules/<id>/` anlegen
2. `__init__.py` mit `module = ...` exportieren
3. `MODULE_ID`, `MODULE_NAME`, `MODULE_DESCRIPTION`, `MODULE_PRIORITY` setzen
4. `fetch_content()` und `render()` implementieren
5. Settings in `SETTINGS_FIELDS` deklarieren
6. bei Bedarf `SETTINGS_GROUPS` ergaenzen
7. Werte ueber `get_setting()` / `get_int_setting()` / `get_bool_setting()` lesen
8. optional `validate_settings()` ergaenzen
9. optional `get_runtime_summary()` ergaenzen
10. optional `get_field_options()` / `handle_api_action()` / `get_health_status()` ergaenzen
11. Tests ergaenzen


## Aktuelle Beispielmodule

- [plex](/C:/Users/tobia/Documents/PlexImageE-Ink/modules/plex/__init__.py)
- [steam](/C:/Users/tobia/Documents/PlexImageE-Ink/modules/steam/__init__.py)
- [dwd_weather](/C:/Users/tobia/Documents/PlexImageE-Ink/modules/dwd_weather/__init__.py)
- [tagesschau](/C:/Users/tobia/Documents/PlexImageE-Ink/modules/tagesschau/__init__.py)
