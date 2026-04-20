from __future__ import annotations

from PIL import Image

from app.module_services import ModuleRenderServices
from app.idle_news_rendering import (
    create_tagesschau_idle_background,
    create_tagesschau_idle_background_light,
    draw_idle_overlay,
)


def render_tagesschau_module(context: ModuleRenderServices, content: object) -> Image.Image:
    news_items = content if isinstance(content, list) else []
    theme = getattr(context, "display_theme", "dark")
    if theme == "light":
        base = create_tagesschau_idle_background_light(context.render_width, context.render_height)
    else:
        base = create_tagesschau_idle_background(context.render_width, context.render_height)
    return draw_idle_overlay(
        base,
        news_items,
        context.render_width,
        context.render_height,
        context.load_font,
        context.fetch_tagesschau_image,
        context.create_rounded_thumbnail,
        display_theme=theme,
    )
