import json
import unittest

from app.llm import LLMClient
from app.quests import validate_campaign, build_datapack, pack_format_for


class CoreTests(unittest.TestCase):
    def test_json_fence(self):
        self.assertEqual(
            LLMClient.json_from('''```json\n{"mods":[]}\n```'''),
            {"mods": []}
        )

    def test_json_brace_in_string(self):
        self.assertEqual(
            LLMClient.json_from('prefix {"text":"a } b"} trailing'),
            {"text": "a } b"}
        )

    def test_three_chapters_required(self):
        with self.assertRaises(ValueError):
            validate_campaign({"chapters": []})

    def test_native_datapack_generation(self):
        campaign = {"chapters": []}
        for chapter_index in range(1, 4):
            campaign["chapters"].append({
                "title": f"Chapter {chapter_index}",
                "description": "Test chapter",
                "quests": [{
                    "title": "Gather iron",
                    "description": "Collect iron ingots",
                    "tasks": [{"item": "minecraft:iron_ingot", "count": 4}],
                    "reward": {"item": "minecraft:bread", "count": 2}
                }]
            })
        campaign = validate_campaign(campaign)
        files = build_datapack(campaign, "1.16.5")
        self.assertIn("pack.mcmeta", files)
        self.assertIn(
            "data/modpack_ai/advancements/quests/chapter_1.json", files
        )
        self.assertIn(
            "data/modpack_ai/advancements/quests/chapter_1/chapter_1_quest_1.json",
            files
        )
        advancement = json.loads(
            files["data/modpack_ai/advancements/quests/chapter_1/chapter_1_quest_1.json"]
        )
        self.assertEqual(
            advancement["criteria"]["task_1"]["trigger"],
            "minecraft:inventory_changed"
        )
        self.assertEqual(
            advancement["rewards"]["loot"],
            ["modpack_ai:quest_rewards/chapter_1_quest_1"]
        )
        self.assertIn(
            "data/modpack_ai/loot_tables/quest_rewards/chapter_1_quest_1.json",
            files
        )

    def test_pack_format_for_1165(self):
        self.assertEqual(pack_format_for("1.16.5"), 6)

    def test_rejects_unknown_or_modded_task_item(self):
        campaign = {
            "chapters": [{
                "title": "One",
                "quests": [{
                    "tasks": [{"item": "some_mod:unknown_item"}]
                }]
            }] * 3
        }
        with self.assertRaises(ValueError):
            validate_campaign(campaign)


if __name__ == "__main__":
    unittest.main()
