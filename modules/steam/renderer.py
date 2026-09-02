from __future__ import annotations

from PIL import Image, ImageDraw

from app.config import load_font, now_local
from app.idle_news_rendering import draw_lines, fit_wrapped_text
from app.image_rendering import (
    create_centered_cover_canvas,
    create_light_cover_canvas,
    draw_bottom_gradient,
)

STEAM_ACCENT = (102, 192, 244, 255)
STEAM_LIGHT_ACCENT = (36, 112, 162, 255)


def _draw_avatar(base: Image.Image, avatar: Image.Image | None, x: int, y: int, size: int) -> None:
    if avatar is None:
        return
    thumb = avatar.resize((size, size), Image.LANCZOS).convert("RGBA")
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([(0, 0), (size - 1, size - 1)], radius=22, fill=255)
    thumb.putalpha(mask)
    base.alpha_composite(thumb, (x, y))


def render_steam_dark(
    render_width: int,
    render_height: int,
    content: dict,
    artwork: Image.Image,
    avatar: Image.Image | None,
    show_timestamp: bool,
) -> Image.Image:
    base = create_centered_cover_canvas(artwork, render_width, render_height).convert("RGBA")
    draw_bottom_gradient(base, int(render_height * 0.40), 230, render_width, render_height)
    draw = ImageDraw.Draw(base, "RGBA")
    persona_name = str(content.get("personaname", "")).strip() or "Steam User"

    avatar_size = 148
    _draw_avatar(base, avatar, 78, 68, avatar_size)

    label_font = load_font(26, True)
    title_font, title_lines, title_lh, title_sp, title_th = fit_wrapped_text(
        draw,
        content["gamename"],
        render_width - 160,
        220,
        72,
        34,
        load_font,
        is_bold=True,
        max_lines=3,
        line_spacing=0.12,
    )
    player_font, player_lines, player_lh, player_sp, player_th = fit_wrapped_text(
        draw,
        content["personastate_label"],
        render_width - 160,
        90,
        38,
        22,
        load_font,
        is_bold=False,
        max_lines=2,
        line_spacing=0.10,
    )
    meta_font, meta_lines, meta_lh, meta_sp, meta_th = fit_wrapped_text(
        draw,
        f"{content['personastate_label']} · AppID {content['gameid']}",
        render_width - 160,
        70,
        30,
        18,
        load_font,
        is_bold=False,
        max_lines=1,
        line_spacing=0.10,
    )

    text_x = 80
    text_y = max(int(render_height * 0.58), render_height - (title_th + player_th + meta_th + 120))
    draw.text((text_x, text_y - 42), f"{persona_name} spielt gerade", font=label_font, fill=STEAM_ACCENT)
    cur_y = draw_lines(draw, text_x, text_y, title_lines, title_font, (255, 255, 255, 255), title_lh, title_sp)
    cur_y += 14
    cur_y = draw_lines(draw, text_x, cur_y, player_lines, player_font, (232, 236, 240, 245), player_lh, player_sp)
    cur_y += 10
    draw_lines(draw, text_x, cur_y, meta_lines, meta_font, (205, 212, 220, 235), meta_lh, meta_sp)

    if show_timestamp:
        stamp = now_local().strftime("Aktualisiert: %d.%m.%Y %H:%M")
        draw.text((render_width - 420, 42), stamp, font=load_font(26, False), fill=(220, 225, 232, 220))

    return base.convert("RGB")


def render_steam_light(
    render_width: int,
    render_height: int,
    content: dict,
    artwork: Image.Image,
    avatar: Image.Image | None,
    show_timestamp: bool,
) -> Image.Image:
    base, cover_bottom = create_light_cover_canvas(artwork, render_width, render_height)
    base = base.convert("RGBA")
    draw = ImageDraw.Draw(base, "RGBA")
    persona_name = str(content.get("personaname", "")).strip() or "Steam User"

    avatar_size = 150
    avatar_y = max(28, cover_bottom + 30)
    _draw_avatar(base, avatar, 80, avatar_y, avatar_size)

    text_x = 80 + avatar_size + 26
    text_width = render_width - text_x - 80
    label_font = load_font(24, True)
    title_font, title_lines, title_lh, title_sp, title_th = fit_wrapped_text(
        draw,
        content["gamename"],
        text_width,
        190,
        62,
        30,
        load_font,
        is_bold=True,
        max_lines=3,
        line_spacing=0.12,
    )
    player_font, player_lines, player_lh, player_sp, player_th = fit_wrapped_text(
        draw,
        content["personastate_label"],
        text_width,
        88,
        34,
        20,
        load_font,
        is_bold=False,
        max_lines=2,
        line_spacing=0.10,
    )
    meta_font, meta_lines, meta_lh, meta_sp, meta_th = fit_wrapped_text(
        draw,
        f"{content['personastate_label']} · AppID {content['gameid']}",
        text_width,
        64,
        28,
        18,
        load_font,
        is_bold=False,
        max_lines=1,
        line_spacing=0.10,
    )

    text_y = avatar_y + 10
    draw.text((text_x, text_y - 34), f"{persona_name} spielt gerade", font=label_font, fill=STEAM_LIGHT_ACCENT)
    cur_y = draw_lines(draw, text_x, text_y, title_lines, title_font, (22, 18, 12, 255), title_lh, title_sp)
    cur_y += 12
    cur_y = draw_lines(draw, text_x, cur_y, player_lines, player_font, (78, 68, 58, 255), player_lh, player_sp)
    cur_y += 10
    draw_lines(draw, text_x, cur_y, meta_lines, meta_font, (118, 106, 92, 255), meta_lh, meta_sp)

    if show_timestamp:
        stamp = now_local().strftime("Aktualisiert: %d.%m.%Y %H:%M")
        draw.text((render_width - 420, 40), stamp, font=load_font(24, False), fill=(132, 120, 108, 255))

    return base.convert("RGB")
