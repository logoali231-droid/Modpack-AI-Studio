import gzip
import tempfile
import unittest
from pathlib import Path

from app.structure_generator import (
    TARGET_VERSION, build_project, validate_project, write_structure_nbt
)


class StructureGeneratorTests(unittest.TestCase):
    def single(self, **changes):
        data = {
            "mode": "single", "name": "Abandoned Watchtower", "structure_type": "tower",
            "width": 15, "depth": 15, "floors": 3, "roof_style": "stepped",
            "style": "mossy medieval",
            "materials": {"wall": "stone_bricks", "accent": "mossy_stone_bricks",
                          "floor": "spruce_planks", "roof": "dark_oak_planks",
                          "trim": "spruce_log", "glass": "glass"},
            "room_types": ["entrance", "library", "treasure"],
            "features": ["balcony", "broken_roof"],
        }
        data.update(changes)
        return data

    def settlement(self):
        return {
            "mode": "settlement", "name": "Oakvale", "width": 55, "depth": 55,
            "style": "frontier village", "features": ["central_well", "main_road", "palisade"],
            "buildings": [
                {"name": "Hall", "structure_type": "keep", "x": 19, "z": 19,
                 "width": 17, "depth": 17, "floors": 2, "roof_style": "stepped",
                 "room_types": ["entrance", "dining"], "features": []},
                {"name": "Smithy", "structure_type": "house", "x": 3, "z": 19,
                 "width": 11, "depth": 11, "floors": 1, "roof_style": "pointed",
                 "room_types": ["entrance", "workshop"], "features": []},
                {"name": "Watchtower", "structure_type": "tower", "x": 37, "z": 19,
                 "width": 11, "depth": 11, "floors": 3, "roof_style": "stepped",
                 "room_types": ["entrance", "storage"], "features": []},
            ],
        }

    def test_blueprint_is_bounded_and_normalized(self):
        result = validate_project(self.single())
        self.assertEqual(result["width"], 15)
        self.assertEqual(result["floors"], 3)
        self.assertEqual(result["mode"], "single")

    def test_rejects_even_dimensions(self):
        with self.assertRaisesRegex(ValueError, "odd"):
            validate_project(self.single(width=14))

    def test_rejects_unbounded_dimensions(self):
        with self.assertRaisesRegex(ValueError, "width"):
            validate_project(self.single(width=101))

    def test_modded_block_palette_accepts_resource_ids(self):
        palette = {"create_casing": "create:andesite_casing"}
        data = self.single(materials={"wall": "create_casing"})
        project = validate_project(data, palette)
        self.assertEqual(project["materials"]["wall"], "create:andesite_casing")

    def test_modded_block_palette_rejects_malformed_ids(self):
        palette = {"bad": "Create:No Spaces"}
        with self.assertRaisesRegex(ValueError, "Invalid custom palette"):
            validate_project(self.single(), palette)

    def test_procedural_builder_creates_nonempty_bounded_structure(self):
        project = validate_project(self.single())
        size, blocks = build_project(project)
        self.assertGreater(len(blocks), 100)
        self.assertLessEqual(len(blocks), 120000)
        self.assertEqual(size[0], 15)
        self.assertEqual(size[2], 15)
        self.assertTrue(all(0 <= x < size[0] and 0 <= y < size[1] and 0 <= z < size[2]
                            for x, y, z in blocks))

    def test_dungeon_is_a_real_underground_volume(self):
        plain = validate_project(self.single(features=[]))
        dungeon = validate_project(self.single(features=["dungeon"]))
        plain_size, plain_blocks = build_project(plain)
        dungeon_size, dungeon_blocks = build_project(dungeon)
        self.assertGreater(dungeon_size[1], plain_size[1] + 4)
        ids = {state[0] for state in dungeon_blocks.values()}
        self.assertIn("minecraft:spawner", ids)
        self.assertIn("minecraft:ladder", ids)
        self.assertIn("minecraft:chest", ids)

    def test_settlement_combines_multiple_buildings_and_features(self):
        project = validate_project(self.settlement())
        size, blocks = build_project(project)
        self.assertEqual(project["mode"], "settlement")
        self.assertGreaterEqual(size[0], 55)
        self.assertGreaterEqual(size[2], 55)
        ids = {state[0] for state in blocks.values()}
        self.assertIn("minecraft:gravel", ids)
        self.assertIn("minecraft:water", ids)
        self.assertIn("minecraft:oak_fence", ids)

    def test_settlement_rejects_building_outside_bounds(self):
        data = self.settlement()
        data["buildings"][0]["x"] = 50
        with self.assertRaisesRegex(ValueError, "extends beyond"):
            validate_project(data)

    def test_nbt_export_is_gzip_compressed_structure_compound(self):
        project = validate_project(self.single(features=["dungeon"]))
        size, blocks = build_project(project)
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "tower.nbt"
            write_structure_nbt(target, size, blocks)
            raw = target.read_bytes()
            self.assertEqual(raw[:2], bytes([0x1f, 0x8b]))
            nbt = gzip.decompress(raw)
            self.assertEqual(nbt[0], 10)
            self.assertIn(b"DataVersion", nbt)
            self.assertIn(b"minecraft:stone_bricks", nbt)
            self.assertIn(b"minecraft:spawner", nbt)

    def test_initial_exporter_target_is_explicit(self):
        self.assertEqual(TARGET_VERSION, "1.16.5")


if __name__ == "__main__":
    unittest.main()
