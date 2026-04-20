from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PIL import Image


@dataclass(frozen=True)
class ModuleFetchServices:
    fetch_tagesschau_news: Callable[[bool], list[dict]]
    should_refresh_tagesschau_news: Callable[[], bool]
    fetch_dwd_weather: Callable[[bool], dict | None]
    should_refresh_dwd_weather: Callable[[], bool]


@dataclass(frozen=True)
class ModuleRenderServices:
    render_width: int
    render_height: int
    load_font: Callable[[int, bool], object]
    fetch_tagesschau_image: Callable[[str], Image.Image | None]
    create_rounded_thumbnail: Callable[[Image.Image, int, int, int], Image.Image]
    display_theme: str = "dark"
