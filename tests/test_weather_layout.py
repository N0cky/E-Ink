"""
Tests für die Panel-Politur des Wetter-Moduls: Schraffur im E-Ink-Verlauf,
Vollbild in kleinen Größen ohne überlappende Stat-Panels, Foto-Aufbereitung.
"""

from __future__ import annotations

import unittest

from PIL import Image, ImageDraw

import app.config as config
from app.image_rendering import SPECTRA6_COLORS, prepare_photo_for_eink
from app.module_services import ModuleRenderServices
from modules.dwd_weather import renderer


def _hourly(n: int = 14) -> list[dict]:
    return [{"time": f"{(i * 2) % 24:02d}:00", "temp_c": 12 + (i % 7), "icon_code": 1, "day_offset": 0 if i < 12 else 1} for i in range(n)]


def _count(img: Image.Image, color) -> int:
    return sum(c for c, col in img.convert("RGB").getcolors(1 << 20) if col == color)


class HatchTest(unittest.TestCase):
    def _render(self, with_img: bool) -> Image.Image:
        pal = renderer.get_dwd_palette("eink")
        img = Image.new("RGBA", (1200, 400), (*SPECTRA6_COLORS["white"], 255))
        draw = ImageDraw.Draw(img, "RGBA")
        fonts = (config.load_font(22, True), config.load_font(16, False), config.load_font(18, True))
        renderer.draw_hourly_strip(draw, (40, 10, 1160, 390), _hourly(), *fonts, pal, img=img if with_img else None)
        return img

    def test_eink_curve_is_hatched_not_filled(self) -> None:
        filled = _count(self._render(False), SPECTRA6_COLORS["blue"])
        hatched = _count(self._render(True), SPECTRA6_COLORS["blue"])
        self.assertGreater(filled, 20000, "ohne img bleibt die Fläche gefüllt")
        self.assertGreater(hatched, 2000, "Schraffur ist sichtbar")
        self.assertLess(hatched, filled * 0.5, "Schraffur deckt deutlich weniger als die Fläche")
        # Im Kurvenbereich (ohne Icon- und Achsentext, der als Schrift geglättet wird) nur Panelfarben
        chart = self._render(True).convert("RGB").crop((90, 140, 1150, 355))
        colors = {col for _, col in chart.getcolors(1 << 20)}
        self.assertTrue(colors <= set(SPECTRA6_COLORS.values()), f"Mischtöne in der Schraffur: {sorted(colors)[:5]}")


class ResponsiveTest(unittest.TestCase):
    def _content(self) -> dict:
        return {
            "station_name": "Gießen", "current_temp_c": 20.4, "current_label": "Bedeckt", "current_icon_code": 3,
            "current_precipitation_mm_text": "0.0 mm", "current_humidity_text": "83 %",
            "current_wind_text": "25.9 km/h\nBöen 46.3 km/h", "current_wind_dir_label": "SW", "current_pressure_text": "1018 hPa",
            "today": {"min_temp_c": 11, "max_temp_c": 22, "sunrise": "06:42", "sunset": "20:06", "moonrise": "22:14", "moonset": "14:43", "moonPhase": 0.7},
            "hourly_forecast": _hourly(),
            "days": [{"day_date": f"2026-09-{d:02d}", "min_temp_c": 10 + d, "max_temp_c": 20 + d, "icon_code": 2, "sunshine_text": "2h 37m",
                      "wind_kmh": 12, "wind_dir_label": "SW", "uvi_max": 3} for d in range(3, 8)],
            "pollen": {"allergens": {"Birke": {"today": 0.5, "tomorrow": 1.0, "dayafter_to": 0.5}}},
        }

    def test_small_sizes_render_without_overlapping_stat_panels(self) -> None:
        content = self._content()
        for theme, w, h in (("eink", 600, 800), ("light", 800, 480), ("dark", 480, 800), ("eink", 1200, 1600), ("light", 1600, 1200)):
            services = ModuleRenderServices(render_width=w, render_height=h, display_theme=theme, load_font=config.load_font)
            img = renderer.render_dwd_weather_module(services, content)
            self.assertEqual(img.size, (w, h), theme)
        # Skalierung: unter 1200 px schrumpfen die Maße, darüber nicht
        self.assertEqual(max(0.35, min(1.0, 600 / 1200, 800 / 1200)), 0.5)
        self.assertEqual(max(0.35, min(1.0, 1600 / 1200, 1200 / 1200)), 1.0)

    def test_stat_panels_stay_inside_their_bounds(self) -> None:
        # Vier Panels nebeneinander bei 600 px: der Text darf nicht über den Rahmen hinausragen
        pal = renderer.get_dwd_palette("eink")
        img = Image.new("RGBA", (600, 120), (*SPECTRA6_COLORS["white"], 255))
        stat_w, gap, s = 118, 7, 0.5
        for idx, (title, value) in enumerate((("Niederschlag", "0.0 mm"), ("Feuchte", "83 %"), ("Wind", "25.9 km/h  SW\nBöen 46.3 km/h"), ("Luftdruck", "1018 hPa"))):
            sx = 21 + idx * (stat_w + gap)
            renderer.draw_stat_panel(img, (sx, 5, sx + stat_w, 60), title, value, "gauge",
                                     config.load_font(10, True), config.load_font(14, True), pal, load_font=config.load_font, scale=s)
        # Unterhalb der Panels (y > 60) darf keine Tinte liegen
        self.assertEqual(_count(img.crop((0, 66, 600, 120)), SPECTRA6_COLORS["black"]), 0)


class PhotoPrepTest(unittest.TestCase):
    def test_highlights_clip_less_than_the_old_recipe(self) -> None:
        # Verlauf von dunkel nach hell: die Aufbereitung treibt weniger Pixel ins Weiß als das alte
        # Rezept (Aufhellen 1.08 + Kontrast 1.15), das Gesichter ausbleichen ließ
        from PIL import ImageEnhance, ImageOps
        grad = Image.linear_gradient("L").resize((256, 64)).convert("RGB")
        old = ImageOps.autocontrast(grad, cutoff=2)
        old = ImageEnhance.Color(old).enhance(1.35)
        old = ImageEnhance.Brightness(old).enhance(1.08)
        old = ImageEnhance.Contrast(old).enhance(1.15)
        out = prepare_photo_for_eink(grad)

        def white(img: Image.Image) -> int:
            return sum(c for c, v in img.convert("L").getcolors(256) if v >= 250)

        self.assertLess(white(out), white(old) * 0.8)
        self.assertEqual(out.size, grad.size)


if __name__ == "__main__":
    unittest.main()
