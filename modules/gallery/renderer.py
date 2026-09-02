from __future__ import annotations

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from app.text_rendering import draw_lines, fit_wrapped_text
from app.image_rendering import create_blurred_cover_background, fit_crop, resize_to_fit
from app.module_services import ModuleRenderServices


def _create_fit_canvas(img: Image.Image, target_w: int, target_h: int, theme: str) -> Image.Image:
    if theme == "light":
        blurred_bg = fit_crop(img, target_w, target_h).filter(ImageFilter.GaussianBlur(radius=48)).convert("RGBA")
        blurred_bg.alpha_composite(Image.new("RGBA", (target_w, target_h), (250, 248, 244, 175)))
        canvas = blurred_bg
        shadow_fill = (0, 0, 0, 70)
        border_fill = (160, 155, 148, 55)
    else:
        canvas = create_blurred_cover_background(img, target_w, target_h).convert("RGBA")
        shadow_fill = (0, 0, 0, 120)
        border_fill = (255, 255, 255, 26)

    fitted = resize_to_fit(img, target_w, target_h)
    fw, fh = fitted.size
    fx = (target_w - fw) // 2
    fy = (target_h - fh) // 2

    shadow = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    ImageDraw.Draw(shadow, "RGBA").rounded_rectangle(
        [(fx + 8, fy + 12), (fx + fw + 8, fy + fh + 12)],
        radius=24,
        fill=shadow_fill,
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=16))
    canvas.alpha_composite(shadow)

    border_layer = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    ImageDraw.Draw(border_layer, "RGBA").rounded_rectangle(
        [(fx - 4, fy - 4), (fx + fw + 4, fy + fh + 4)],
        radius=26,
        fill=border_fill,
    )
    canvas.alpha_composite(border_layer)
    canvas.paste(fitted, (fx, fy))
    return canvas.convert("RGB")


def _resolve_caption(content: dict, overlay_mode: str) -> str:
    filename = str(content.get("caption_filename", "")).strip()
    folder = str(content.get("caption_folder", "")).strip()
    if overlay_mode == "filename":
        return filename
    if overlay_mode == "folder":
        return folder
    if overlay_mode == "filename_folder":
        if filename and folder:
            return f"{filename}  |  {folder}"
        return filename or folder
    return ""


def _draw_overlay(base: Image.Image, services: ModuleRenderServices, caption: str) -> Image.Image:
    if not caption:
        return base

    img = base.convert("RGBA")
    draw = ImageDraw.Draw(img)
    target_w, target_h = img.size
    panel_x = 56
    panel_w = target_w - 2 * panel_x
    panel_h = 118
    panel_y = target_h - panel_h - 52
    radius = 26

    if services.display_theme == "light":
        panel_fill = (248, 244, 238, 212)
        border_fill = (180, 172, 160, 95)
        text_fill = (28, 24, 19, 255)
    else:
        panel_fill = (12, 12, 12, 170)
        border_fill = (255, 255, 255, 34)
        text_fill = (255, 255, 255, 255)

    overlay = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay, "RGBA")
    overlay_draw.rounded_rectangle(
        [(panel_x, panel_y), (panel_x + panel_w, panel_y + panel_h)],
        radius=radius,
        fill=panel_fill,
        outline=border_fill,
        width=1,
    )
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=12))
    img.alpha_composite(overlay)

    font, lines, line_h, line_spacing, _ = fit_wrapped_text(
        draw,
        caption,
        panel_w - 44,
        panel_h - 30,
        38,
        22,
        services.load_font,
        is_bold=True,
        max_lines=2,
        line_spacing=0.14,
    )
    text_y = panel_y + max(14, (panel_h - ((len(lines) * line_h) + (max(0, len(lines) - 1) * line_spacing))) // 2)
    draw_lines(draw, panel_x + 22, text_y, lines, font, text_fill, line_h, line_spacing)
    return img.convert("RGB")


def render_gallery_image(services: ModuleRenderServices, content: dict, fit_mode: str, overlay_mode: str) -> Image.Image:
    with Image.open(content["image_path"]) as src:
        img = ImageOps.exif_transpose(src).convert("RGB")

    if fit_mode == "cover":
        base = fit_crop(img, services.render_width, services.render_height)
    else:
        base = _create_fit_canvas(img, services.render_width, services.render_height, services.display_theme)

    caption = _resolve_caption(content, overlay_mode)
    return _draw_overlay(base, services, caption)
