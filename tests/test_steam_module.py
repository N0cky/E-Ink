from __future__ import annotations

import unittest
from unittest.mock import patch

import requests

from app.steam import (
    _build_store_asset_path,
    _download_steam_candidate,
    extract_active_game,
    get_game_artwork_urls,
    get_store_item_asset_urls,
    parse_steam_profile_input,
)


class SteamHelpersTest(unittest.TestCase):
    def test_parse_steam_profile_accepts_steamid(self) -> None:
        self.assertEqual(
            parse_steam_profile_input("76561198000000000"),
            ("steamid", "76561198000000000"),
        )

    def test_parse_steam_profile_accepts_vanity_name(self) -> None:
        self.assertEqual(
            parse_steam_profile_input("gaben"),
            ("vanity", "gaben"),
        )

    def test_parse_steam_profile_accepts_profile_url(self) -> None:
        self.assertEqual(
            parse_steam_profile_input("https://steamcommunity.com/id/gaben/"),
            ("vanity", "gaben"),
        )
        self.assertEqual(
            parse_steam_profile_input("https://steamcommunity.com/profiles/76561198000000000"),
            ("steamid", "76561198000000000"),
        )

    def test_extract_active_game_returns_none_when_not_playing(self) -> None:
        self.assertIsNone(
            extract_active_game(
                {
                    "steamid": "76561198000000000",
                    "personaname": "Test User",
                    "personastate": 1,
                }
            )
        )

    def test_extract_active_game_returns_normalized_payload(self) -> None:
        content = extract_active_game(
            {
                "steamid": "76561198000000000",
                "personaname": "Test User",
                "personastate": 1,
                "profileurl": "https://steamcommunity.com/id/testuser/",
                "avatarfull": "https://cdn.example/avatar.jpg",
                "gameid": "730",
                "gameextrainfo": "Counter-Strike 2",
            }
        )

        self.assertIsNotNone(content)
        assert content is not None
        self.assertEqual(content["gamename"], "Counter-Strike 2")
        self.assertEqual(content["gameid"], "730")
        self.assertEqual(content["personastate_label"], "Online")

    def test_game_artwork_prefers_portrait_cover_urls(self) -> None:
        urls = get_game_artwork_urls("730")
        self.assertGreaterEqual(len(urls), 3)
        self.assertIn("library_600x900", urls[0])
        self.assertIn("header.jpg", urls[-1])

    def test_build_store_asset_url_replaces_filename(self) -> None:
        url = _build_store_asset_path(
            "steam/apps/730/${FILENAME}?t=123",
            "library_600x900_2x.jpg",
        )
        self.assertEqual(
            url,
            "store_item_assets/steam/apps/730/library_600x900_2x.jpg?t=123",
        )

    def test_get_store_item_asset_urls_uses_getitems_assets(self) -> None:
        payload = {
            "response": {
                "store_items": [
                    {
                        "appid": 730,
                        "assets": {
                            "asset_url_format": "steam/apps/730/${FILENAME}?t=123",
                            "library_capsule_2x": "abc/library_600x900_2x.jpg",
                            "header": "def/header.jpg",
                        },
                    }
                ]
            }
        }
        with patch("app.steam._steam_api_get", return_value=payload):
            urls = get_store_item_asset_urls("730")

        self.assertGreaterEqual(len(urls), 2)
        self.assertEqual(
            urls[0],
            "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/730/abc/library_600x900_2x.jpg?t=123",
        )
        self.assertEqual(
            urls[4],
            "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/730/def/header.jpg?t=123",
        )

    def test_download_steam_candidate_treats_retry_error_as_fallback(self) -> None:
        retry_error = requests.exceptions.RetryError("too many 503 error responses")
        with patch("app.steam.HTTP_SESSION.get", side_effect=retry_error):
            image = _download_steam_candidate("https://example.invalid/image.jpg")

        self.assertIsNone(image)


if __name__ == "__main__":
    unittest.main()
