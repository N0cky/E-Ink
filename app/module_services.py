"""
Render-Dienste, die das Framework jedem Modul bereitstellt.
Bewusst klein: nur das, was jeder Renderer braucht.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ModuleRenderServices:
    render_width: int
    render_height: int
    display_theme: str
    load_font: Callable[[int, bool], object]

    @classmethod
    def from_runtime(cls) -> "ModuleRenderServices":
        """Baut die Services aus der aktuellen RuntimeConfig."""
        from app.config import get_cfg, load_font
        cfg = get_cfg()
        return cls(
            render_width=cfg.render_width,
            render_height=cfg.render_height,
            display_theme=cfg.display_theme,
            load_font=load_font,
        )
