import gzip
import tempfile
import unittest
from pathlib import Path

from app.structure_generator import (
    TARGET_VERSION, build_blocks, validate_blueprint, write_structure_nbt
)


class StructureGeneratorTests(unittest.TestCase):
    def blueprint(self, **changes):
        data = {
            "name": "Abandoned Watchtower",
            "structure_type": "tower",
            "width": 15,
            "depth": 15,
            "floors": 3,
            "roof_style": "stepped",
            "style": "mossy medieval",
            "materials": {
                "wall": "stone_bricks",
                "accent": "mossy_stone_bricks",
                "floor": "spruce_planks",
                "roof": "dark_oak_planks",
                "trim": "spruce_log",
                "glass": "glass",
            },
            "room_types": ["entrance", "library", "treasure"],
            "features": ["balcony", "broken_roof"],
        }
        data.update(changes)
        return data

    def test_blueprint_is_bounded_and_normalized(self):
        result = validate_blueprint(self.blueprint())
        self.assertEqual(result["width"], 15)
        self.assertEqual(result["floors"], 3)
        self.assertEqual(result["materials"]["wall"], "stone_bricks")

    def test_rejects_even_dimensions(self):
        with self.assertRaisesRegex(ValueError, "odd"):
            validate_blueprint(self.blueprint(width=14))

    def test_rejects_untrusted_material_id(self):
        with self.assertRaisesRegex(ValueError, "Unknown material"):
            validate_blueprint(self.blueprint(materials={"wall": "some_mod:explosive_block"}))

    def test_rejects_unbounded_dimensions(self):
        with self.assertRaisesRegex(ValueError, "width"):
            validate_blueprint(self.blueprint(width=101))

    def test_procedural_builder_creates_nonempty_bounded_structure(self):
        blueprint = validate_blueprint(self.blueprint())
        size, blocks = build_blocks(blueprint)
        self.assertGreater(len(blocks), 100)
        self.assertLessEqual(len(blocks), 60000)
        self.assertEqual(size[0], 15)
        self.assertEqual(size[2], 15)
        self.assertTrue(all(0 <= x < size[0] and 0 <= y < size[1] and 0 <= z < size[2]
                            for x, y, z in blocks))

    def test_nbt_export_is_gzip_compressed_structure_compound(self):
        blueprint = validate_blueprint(self.blueprint())
        size, blocks = build_blocks(blueprint)
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "tower.nbt"
            write_structure_nbt(target, size, blocks)
            raw = target.read_bytes()
            self.assertEqual(raw[:2], b"\\x1f\\x8b")
            nbt = gzip.decompress(raw)
            self.assertEqual(nbt[0], 10)  # TAG_Compound root
            self.assertIn(b"DataVersion", nbt)
            self.assertIn(b"minecraft:stone_bricks", nbt)
            self.assertIn(b"minecraft:chest", nbt)

    def test_initial_exporter_target_is_explicit(self):
        self.assertEqual(TARGET_VERSION, "1.16.5")


if __name__ == "__main__":
    unittest.main()
