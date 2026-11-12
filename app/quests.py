"""Native Minecraft advancement-based quest datapack generator.

Campaign size is progression-driven, not fixed to three chapters. Hard safety
ceilings prevent malformed local-model output from exhausting memory.
"""
import json
import re

ITEM_RE = re.compile(r"^[a-z0-9_.-]+:[a-z0-9_./-]+$")
MAX_CHAPTERS = 100
MAX_QUESTS_PER_CHAPTER = 20


def _count(value):
    try:
        return max(1, min(64, int(value)))
    except (TypeError, ValueError):
        return 1


def validate_campaign(data):
    chapters = data.get("chapters") if isinstance(data, dict) else None
    if not isinstance(chapters, list) or not 1 <= len(chapters) <= MAX_CHAPTERS:
        raise ValueError(f"Quest campaign must contain 1-{MAX_CHAPTERS} chapters.")
    for ci, chapter in enumerate(chapters, 1):
        quests = chapter.get("quests") if isinstance(chapter, dict) else None
        if not isinstance(quests, list) or not 1 <= len(quests) <= MAX_QUESTS_PER_CHAPTER:
            raise ValueError(f"Chapter {ci} must contain 1-{MAX_QUESTS_PER_CHAPTER} quests.")
        for qi, quest in enumerate(quests, 1):
            if not isinstance(quest, dict) or not isinstance(quest.get("tasks"), list):
                raise ValueError(f"Chapter {ci}, quest {qi} needs item tasks.")
            tasks = []
            for task in quest["tasks"][:4]:
                if not isinstance(task, dict):
                    continue
                item = task.get("item")
                if isinstance(item, str) and ITEM_RE.fullmatch(item) and item.startswith("minecraft:"):
                    tasks.append({"item": item, "count": _count(task.get("count"))})
            if not tasks:
                raise ValueError(f"Chapter {ci}, quest {qi} has no valid vanilla item task.")
            quest["tasks"] = tasks
            reward = quest.get("reward") if isinstance(quest.get("reward"), dict) else {}
            reward_item = reward.get("item")
            quest["reward"] = {
                "item": reward_item if isinstance(reward_item, str)
                and ITEM_RE.fullmatch(reward_item) and reward_item.startswith("minecraft:")
                else "minecraft:bread",
                "count": _count(reward.get("count", 1)),
            }
            quest["title"] = str(quest.get("title") or f"Quest {qi}")[:80]
            quest["description"] = str(quest.get("description") or "")[:200]
        chapter["title"] = str(chapter.get("title") or f"Chapter {ci}")[:80]
        chapter["description"] = str(chapter.get("description") or "")[:200]
    return data


def pack_format_for(version):
    version = str(version).strip()
    exact = {
        "1.13": 4, "1.13.1": 4, "1.13.2": 4,
        "1.14": 4, "1.14.1": 4, "1.14.2": 4, "1.14.3": 4, "1.14.4": 4,
        "1.15": 5, "1.15.1": 5, "1.15.2": 5,
        "1.16": 5, "1.16.1": 5,
        "1.16.2": 6, "1.16.3": 6, "1.16.4": 6, "1.16.5": 6,
        "1.17": 7, "1.17.1": 7,
        "1.18": 8, "1.18.1": 8, "1.18.2": 9,
        "1.19": 10, "1.19.1": 10, "1.19.2": 10, "1.19.3": 12, "1.19.4": 13,
        "1.20": 15, "1.20.1": 15, "1.20.2": 18, "1.20.3": 22, "1.20.4": 22,
    }
    if version not in exact:
        raise ValueError(
            f"Native quest datapacks currently support the verified legacy advancement/item schema through Minecraft 1.20.4; no compatible schema is implemented for Minecraft {version}."
        )
    return exact[version]


def _write_json(files, path, data):
    files[path] = json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def build_datapack(campaign, minecraft_version):
    pack_format = pack_format_for(minecraft_version)
    files = {"pack.mcmeta": json.dumps({
        "pack": {"pack_format": pack_format,
                 "description": "Modpack AI Studio · Custom Quest Campaign"}
    }, ensure_ascii=False, indent=2) + "\n"}
    for chapter_index, chapter in enumerate(campaign["chapters"], 1):
        chapter_id = f"modpack_ai:quests/chapter_{chapter_index}"
        root_path = f"data/modpack_ai/advancements/quests/chapter_{chapter_index}.json"
        _write_json(files, root_path, {
            "display": {
                "icon": {"item": "minecraft:book"},
                "title": {"text": chapter["title"]},
                "description": {"text": chapter["description"]},
                "background": "minecraft:textures/gui/advancements/backgrounds/stone.png",
                "show_toast": False, "announce_to_chat": False
            },
            "criteria": {"chapter_root": {"trigger": "minecraft:impossible"}}
        })
        for quest_index, quest in enumerate(chapter["quests"], 1):
            quest_id = f"chapter_{chapter_index}_quest_{quest_index}"
            criteria, requirements = {}, []
            for task_index, task in enumerate(quest["tasks"], 1):
                criterion = f"task_{task_index}"
                criteria[criterion] = {
                    "trigger": "minecraft:inventory_changed",
                    "conditions": {"items": [{
                        "items": [task["item"]], "count": {"min": task["count"]}
                    }]}
                }
                requirements.append([criterion])
            loot_id = f"modpack_ai:quest_rewards/{quest_id}"
            _write_json(files,
                f"data/modpack_ai/advancements/quests/chapter_{chapter_index}/{quest_id}.json", {
                    "parent": chapter_id,
                    "display": {
                        "icon": {"item": quest["tasks"][0]["item"]},
                        "title": {"text": quest["title"]},
                        "description": {"text": quest["description"]},
                        "frame": "task", "show_toast": True,
                        "announce_to_chat": False, "hidden": False
                    },
                    "criteria": criteria, "requirements": requirements,
                    "rewards": {"loot": [loot_id]}
                })
            reward = quest["reward"]
            _write_json(files,
                f"data/modpack_ai/loot_tables/quest_rewards/{quest_id}.json", {
                    "type": "minecraft:generic",
                    "pools": [{"rolls": 1, "entries": [{
                        "type": "minecraft:item", "name": reward["item"],
                        "functions": [{"function": "minecraft:set_count",
                                       "count": reward["count"]}]
                    }]}]
                })
    return files
