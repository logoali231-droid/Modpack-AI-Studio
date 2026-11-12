"""Native Minecraft advancement-based quest datapack generator.

This deliberately uses Minecraft's built-in advancements system. It needs no
FTB Quests, quest library, Forge/Fabric mod, or runtime dependency.
"""
import json
import re

ITEM_RE = re.compile(r"^[a-z0-9_.-]+:[a-z0-9_./-]+$")


def _item(value, fallback="minecraft:book"):
    return value if isinstance(value, str) and ITEM_RE.fullmatch(value) else fallback


def _count(value):
    try:
        return max(1, min(64, int(value)))
    except (TypeError, ValueError):
        return 1


def validate_campaign(data):
    if not isinstance(data, dict) or not isinstance(data.get("chapters"), list) or len(data["chapters"]) != 3:
        raise ValueError("Quest plan must contain exactly three chapters.")
    for ci, chapter in enumerate(data["chapters"], 1):
        if not isinstance(chapter, dict) or not isinstance(chapter.get("quests"), list) or not chapter["quests"]:
            raise ValueError(f"Chapter {ci} needs quests.")
        chapter["quests"] = chapter["quests"][:8]
        for qi, quest in enumerate(chapter["quests"], 1):
            if not isinstance(quest, dict) or not isinstance(quest.get("tasks"), list) or not quest["tasks"]:
                raise ValueError(f"Chapter {ci}, quest {qi} needs at least one item task.")
            tasks = []
            for task in quest["tasks"][:4]:
                if not isinstance(task, dict):
                    continue
                item = task.get("item")
                # The first release deliberately sticks to vanilla registry IDs.
                # This avoids generating datapacks that fail to load because an AI
                # guessed a modded item ID that does not exist in the installed JAR.
                if not isinstance(item, str) or not ITEM_RE.fullmatch(item) or not item.startswith("minecraft:"):
                    continue
                tasks.append({"item": item, "count": _count(task.get("count"))})
            if not tasks:
                raise ValueError(f"Chapter {ci}, quest {qi} has no valid namespaced item IDs.")
            quest["tasks"] = tasks
            reward = quest.get("reward")
            if not isinstance(reward, dict):
                reward = {}
            quest["reward"] = {
                "item": _item(reward.get("item"), "minecraft:bread") if str(reward.get("item", "")).startswith("minecraft:") else "minecraft:bread",
                "count": _count(reward.get("count", 1)),
            }
    return data


def pack_format_for(version):
    """Return the data-pack format for supported Minecraft Java releases."""
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
    """Build a self-contained vanilla advancement campaign as datapack files."""
    pack_format = pack_format_for(minecraft_version)
    files = {
        "pack.mcmeta": json.dumps({
            "pack": {
                "pack_format": pack_format,
                "description": "Modpack AI Studio · Custom Quest Campaign"
            }
        }, ensure_ascii=False, indent=2) + "\n"
    }

    for chapter_index, chapter in enumerate(campaign["chapters"], 1):
        chapter_id = f"modpack_ai:quests/chapter_{chapter_index}"
        root_path = f"data/modpack_ai/advancements/quests/chapter_{chapter_index}.json"
        root = {
            "display": {
                "icon": {"item": "minecraft:book"},
                "title": {"text": str(chapter.get("title", f"Chapter {chapter_index}"))[:80]},
                "description": {"text": str(chapter.get("description", ""))[:200]},
                "background": "minecraft:textures/gui/advancements/backgrounds/stone.png",
                "show_toast": False,
                "announce_to_chat": False
            },
            "criteria": {"chapter_root": {"trigger": "minecraft:impossible"}}
        }
        _write_json(files, root_path, root)

        for quest_index, quest in enumerate(chapter["quests"], 1):
            quest_id = f"chapter_{chapter_index}_quest_{quest_index}"
            advancement_path = (
                f"data/modpack_ai/advancements/quests/chapter_{chapter_index}/{quest_id}.json"
            )
            criteria = {}
            requirements = []
            for task_index, task in enumerate(quest["tasks"], 1):
                criterion = f"task_{task_index}"
                criteria[criterion] = {
                    "trigger": "minecraft:inventory_changed",
                    "conditions": {
                        "items": [{
                            "items": [task["item"]],
                            "count": {"min": task["count"]}
                        }]
                    }
                }
                requirements.append([criterion])

            first_item = quest["tasks"][0]["item"]
            reward = quest["reward"]
            loot_id = f"modpack_ai:quest_rewards/chapter_{chapter_index}_quest_{quest_index}"
            advancement = {
                "parent": chapter_id,
                "display": {
                    "icon": {"item": first_item},
                    "title": {"text": str(quest.get("title", f"Quest {quest_index}"))[:80]},
                    "description": {"text": str(quest.get("description", ""))[:200]},
                    "frame": "task",
                    "show_toast": True,
                    "announce_to_chat": False,
                    "hidden": False
                },
                "criteria": criteria,
                "requirements": requirements,
                "rewards": {"loot": [loot_id]}
            }
            _write_json(files, advancement_path, advancement)

            loot_table = {
                "type": "minecraft:generic",
                "pools": [{
                    "rolls": 1,
                    "entries": [{
                        "type": "minecraft:item",
                        "name": reward["item"],
                        "functions": [{
                            "function": "minecraft:set_count",
                            "count": reward["count"]
                        }]
                    }]
                }]
            }
            loot_path = (
                f"data/modpack_ai/loot_tables/quest_rewards/chapter_{chapter_index}_quest_{quest_index}.json"
            )
            _write_json(files, loot_path, loot_table)

    return files
