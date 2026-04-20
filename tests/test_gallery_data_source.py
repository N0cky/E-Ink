from __future__ import annotations

import unittest

from modules.gallery.data_source import choose_random_index


class GalleryDataSourceTest(unittest.TestCase):
    def test_recent_avoidance_prevents_immediate_repeat(self) -> None:
        num_images = 6
        seen = [choose_random_index(num_images, slot, 3) for slot in range(12)]
        for previous, current in zip(seen, seen[1:]):
            self.assertNotEqual(previous, current)

    def test_recent_avoidance_can_be_disabled(self) -> None:
        num_images = 3
        a = choose_random_index(num_images, 10, 0)
        b = choose_random_index(num_images, 10, 0)
        self.assertEqual(a, b)

    def test_recent_avoidance_handles_large_slot_values(self) -> None:
        choice = choose_random_index(8, 14_000_000, 5)
        self.assertGreaterEqual(choice, 0)
        self.assertLess(choice, 8)

    def test_recent_avoidance_with_few_images_avoids_immediate_repeat(self) -> None:
        seen = [choose_random_index(2, slot, 5) for slot in range(8)]
        for previous, current in zip(seen, seen[1:]):
            self.assertNotEqual(previous, current)


if __name__ == "__main__":
    unittest.main()
