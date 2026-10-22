"""Synthetic regressions; tests do not need the game or redistribute its art."""
import unittest
import json
import tempfile
from pathlib import Path
from PIL import Image
from tlg import TRANSFORMERS
from prepare_game_stage import CHARACTERS, composite_layers, layer_names, load_provenance


class GameStageTests(unittest.TestCase):
    def test_mugi_uses_opening_maid_outfit_without_other_characters_accessories(self):
        self.assertEqual(layer_names(CHARACTERS['mugi']),
                         ['2/stb1_s2_1_8.tlg', '2/st1_s2_1_1.tlg'])
        self.assertEqual(CHARACTERS['mugi']['background'], 'bg5_0.png')
        self.assertEqual(layer_names(CHARACTERS['hika']),
                         ['2/stb2_s2_1_2.tlg', '2/st2_s2_1_1.tlg', '2/stp2_s2_1_1.tlg'])
        self.assertEqual(layer_names(CHARACTERS['ayame']),
                         ['2/stb8_s2_1_2.tlg', '2/st8_s2_1_1.tlg', '2/stp8_s2_1_1.tlg'])

    def test_single_character_provenance_preserves_previous_characters(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'provenance.json'
            self.assertEqual(load_provenance(path), {})
            previous = {'hika': {'character_id_in_game': 2}, 'ayame': {'character_id_in_game': 8}}
            path.write_text(json.dumps(previous), encoding='utf-8')
            result = load_provenance(path)
            result['mugi'] = {'character_id_in_game': 1}
            self.assertEqual({key: result[key] for key in previous}, previous)

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
