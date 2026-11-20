import unittest

from app.ftb_quest_guide import _validate_campaign


def sample_campaign():
    quests = []
    for index in range(1, 4):
        quests.append({
            "title": f"Quest {index}",
            "description": "Complete a useful progression objective.",
            "icon": "minecraft:iron_ingot",
            "task": {"type": "item", "target": "minecraft:iron_ingot", "count": 4},
            "reward": {"type": "xp", "amount": 20},
            "depends_on": [] if index == 1 else [f"Quest {index - 1}"],
            "ftb_tip": "Add an Item task in the FTB Quests editor.",
        })
    return {
        "campaign_title": "Test campaign",
        "chapters": [{
            "title": "First steps",
            "description": "Build a stable beginning.",
            "icon": "minecraft:book",
            "quests": quests,
        }],
    }


class FTBQuestGuideTests(unittest.TestCase):
    def test_valid_campaign_is_accepted(self):
        result = _validate_campaign(sample_campaign())
        self.assertEqual(len(result["chapters"][0]["quests"]), 3)

    def test_forward_dependency_is_rejected(self):
        campaign = sample_campaign()
        campaign["chapters"][0]["quests"][1]["depends_on"] = ["Quest 3"]
        with self.assertRaises(ValueError):
            _validate_campaign(campaign)

    def test_invalid_item_id_is_rejected(self):
        campaign = sample_campaign()
        campaign["chapters"][0]["quests"][0]["task"]["target"] = "not-an-item"
        with self.assertRaises(ValueError):
            _validate_campaign(campaign)


if __name__ == "__main__":
    unittest.main()
