"""Synthetic regressions; tests do not need the game or redistribute its art."""
import unittest
from PIL import Image
from tlg import TRANSFORMERS
from prepare_game_stage import composite_layers


class GameStageTests(unittest.TestCase):
    def test_color_filters_match_kirikiri_rgb_vectors(self):
        # RGB=(1,2,3), mathematical filter vectors checked against tvpgl.c.
        expected = [(1,2,3),(3,2,5),(6,5,3),(1,3,6),(7,6,4),(1,6,4),
                    (1,2,5),(1,5,3),(3,2,3),(4,6,9),(1,3,4),(4,5,3),
                    (4,6,3),(6,8,5),(7,3,6),(7,8,3)]
        self.assertEqual([transform(1,2,3) for transform in TRANSFORMERS], expected)

    def test_face_and_accessory_use_original_canvas_origin(self):
        body = Image.new('RGBA', (4, 6), (10, 20, 30, 255))
        face = Image.new('RGBA', (4, 3))
        face.putpixel((2, 1), (100, 110, 120, 255))
        accessory = Image.new('RGBA', (4, 2))
        accessory.putpixel((2, 0), (200, 210, 220, 255))
        result = composite_layers(body, face, [accessory])
        self.assertEqual(result.getpixel((2, 1)), (100, 110, 120, 255))
        self.assertEqual(result.getpixel((2, 0)), (200, 210, 220, 255))
        self.assertEqual(result.getpixel((2, 5)), (10, 20, 30, 255))
        self.assertEqual(body.getpixel((2, 1)), (10, 20, 30, 255))


if __name__ == '__main__':
    unittest.main()
