import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from app.llm import LLMClient
from app.quests import validate_campaign, build_datapack, pack_format_for
from app.dependency_verifier import verify_mod_directory


def make_campaign(chapter_count):
    return {"chapters": [{
        "title": f"Chapter {chapter_index}",
        "description": "Test chapter",
        "quests": [{
            "title": f"Gather iron {quest_index}",
            "description": "Collect iron ingots",
            "tasks": [{"item": "minecraft:iron_ingot", "count": 4}],
            "reward": {"item": "minecraft:bread", "count": 2}
        } for quest_index in range(1, 4)]
    } for chapter_index in range(1, chapter_count + 1)]}


class CoreTests(unittest.TestCase):
    def test_json_fence(self):
        self.assertEqual(LLMClient.json_from('''```json
{"mods":[]}
```'''), {"mods": []})

    def test_json_brace_in_string(self):
        self.assertEqual(LLMClient.json_from('prefix {"text":"a } b"} trailing'),
                         {"text": "a } b"})

    def test_empty_campaign_rejected(self):
        with self.assertRaises(ValueError):
            validate_campaign({"chapters": []})

    def test_campaign_is_not_limited_to_three_chapters(self):
        campaign = validate_campaign(make_campaign(7))
        files = build_datapack(campaign, "1.16.5")
        self.assertIn("data/modpack_ai/advancements/quests/chapter_7.json", files)
        self.assertIn(
            "data/modpack_ai/advancements/quests/chapter_7/chapter_7_quest_3.json",
            files
        )

    def test_native_datapack_generation(self):
        campaign = validate_campaign(make_campaign(3))
        files = build_datapack(campaign, "1.16.5")
        self.assertIn("pack.mcmeta", files)
        self.assertIn("data/modpack_ai/advancements/quests/chapter_1.json", files)
        advancement = json.loads(
            files["data/modpack_ai/advancements/quests/chapter_1/chapter_1_quest_1.json"]
        )
        self.assertEqual(advancement["criteria"]["task_1"]["trigger"],
                         "minecraft:inventory_changed")
        self.assertEqual(advancement["rewards"]["loot"],
                         ["modpack_ai:quest_rewards/chapter_1_quest_1"])
        self.assertIn(
            "data/modpack_ai/loot_tables/quest_rewards/chapter_1_quest_1.json",
            files
        )

    def test_pack_format_for_1165(self):
        self.assertEqual(pack_format_for("1.16.5"), 6)

    def test_rejects_modded_task_item_until_registry_validation_exists(self):
        campaign = make_campaign(1)
        campaign["chapters"][0]["quests"][0]["tasks"] = [
            {"item": "some_mod:unknown_item"}
        ]
        with self.assertRaises(ValueError):
            validate_campaign(campaign)

    def test_forge_internal_dependency_id_is_checked(self):
        with tempfile.TemporaryDirectory() as temp:
            mod_dir = Path(temp)
            library = mod_dir / "library.jar"
            consumer = mod_dir / "consumer.jar"
            with zipfile.ZipFile(library, "w") as jar:
                jar.writestr("META-INF/mods.toml",
                    'modLoader="javafml"\nloaderVersion="[36,)"\n'
                    '[[mods]]\nmodId="selene"\nversion="1.0.0"\n')
            with zipfile.ZipFile(consumer, "w") as jar:
                jar.writestr("META-INF/mods.toml",
                    'modLoader="javafml"\nloaderVersion="[36,)"\n'
                    '[[mods]]\nmodId="supplementaries"\nversion="1.0.0"\n'
                    '[[dependencies.supplementaries]]\nmodId="selene"\n'
                    'mandatory=true\nversionRange="[1.0,)"\n')
            report = verify_mod_directory([consumer, library])
            self.assertEqual(report["missing_required"], [])

    def test_missing_internal_dependency_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            consumer = Path(temp) / "supplementaries.jar"
            with zipfile.ZipFile(consumer, "w") as jar:
                jar.writestr("META-INF/mods.toml",
                    'modLoader="javafml"\nloaderVersion="[36,)"\n'
                    '[[mods]]\nmodId="supplementaries"\nversion="1.0.0"\n'
                    '[[dependencies.supplementaries]]\nmodId="selene"\n'
                    'mandatory=true\nversionRange="[1.0,)"\n')
            with self.assertRaisesRegex(RuntimeError, "selene"):
                verify_mod_directory([consumer])


if __name__ == "__main__":
    unittest.main()
