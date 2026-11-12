import unittest
from app.llm import LLMClient
from app.quests import validate_campaign, build_chapter
class CoreTests(unittest.TestCase):
    def test_json_fence(self): self.assertEqual(LLMClient.json_from('''```json\n{"mods":[]}\n```'''),{"mods":[]})
    def test_json_brace_in_string(self): self.assertEqual(LLMClient.json_from('prefix {"text":"a } b"} trailing'),{"text":"a } b"})
    def test_three_chapters_required(self):
        with self.assertRaises(ValueError): validate_campaign({"chapters":[]})
    def test_coordinates_and_item_fallback(self):
        out=build_chapter({"quests":[{"tasks":[{"item":"invalid item"}]}]},1)
        self.assertIn("x: 0.0d",out); self.assertIn("y: 0.0d",out); self.assertIn("minecraft:book",out)
if __name__=="__main__": unittest.main()
