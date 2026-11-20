"""Generate a structured FTB Quests editor guide from an installed modpack manifest.

This exports design instructions (JSON + Markdown). It deliberately does not
claim to generate importable FTB .snbt files.
"""
import json
import re
from pathlib import Path

ID_RE = re.compile(r"^[a-z0-9_.-]+:[a-z0-9_./-]+$")
TASK_TYPES = {"item", "kill", "dimension", "advancement"}


def _validate_campaign(data):
    if not isinstance(data, dict) or not isinstance(data.get("chapters"), list):
        raise ValueError("Campaign must contain a chapters array.")
    chapters = data["chapters"]
    if not 1 <= len(chapters) <= 12:
        raise ValueError("Campaign must contain 1-12 chapters.")
    for ci, chapter in enumerate(chapters, 1):
        if not isinstance(chapter, dict) or not isinstance(chapter.get("quests"), list):
            raise ValueError(f"Chapter {ci} is missing its quests array.")
        for field in ("title", "description", "icon"):
            if not chapter.get(field):
                raise ValueError(f"Chapter {ci} is missing {field}.")
        if not ID_RE.fullmatch(str(chapter["icon"])):
            raise ValueError(f"Chapter {ci} has an invalid icon ID.")
        quests = chapter["quests"]
        if not 3 <= len(quests) <= 8:
            raise ValueError(f"Chapter {ci} must contain 3-8 quests.")
        prior_titles = []
        for qi, quest in enumerate(quests, 1):
            for field in ("title", "description", "icon", "task", "reward", "depends_on", "ftb_tip"):
                if field not in quest:
                    raise ValueError(f"Chapter {ci}, quest {qi} is missing {field}.")
            if not ID_RE.fullmatch(str(quest["icon"])):
                raise ValueError(f"Chapter {ci}, quest {qi} has an invalid icon ID.")
            task = quest["task"]
            if not isinstance(task, dict) or task.get("type") not in TASK_TYPES:
                raise ValueError(f"Chapter {ci}, quest {qi} has an invalid task type.")
            target = str(task.get("target", ""))
            if not (ID_RE.fullmatch(target) or target.startswith("#")):
                raise ValueError(f"Chapter {ci}, quest {qi} has an invalid task target.")
            if task.get("type") == "item":
                task["count"] = max(1, min(64, int(task.get("count", 1))))
            reward = quest["reward"]
            if not isinstance(reward, dict) or reward.get("type") not in ("item", "xp"):
                raise ValueError(f"Chapter {ci}, quest {qi} has an invalid reward.")
            if reward["type"] == "item":
                if not ID_RE.fullmatch(str(reward.get("target", ""))):
                    raise ValueError(f"Chapter {ci}, quest {qi} has an invalid reward item ID.")
                reward["amount"] = max(1, min(64, int(reward.get("amount", 1))))
            else:
                reward["amount"] = max(1, min(10000, int(reward.get("amount", 1))))
            deps = quest["depends_on"]
            if not isinstance(deps, list):
                raise ValueError(f"Chapter {ci}, quest {qi} dependencies must be a list.")
            if qi == 1 and deps:
                raise ValueError(f"Chapter {ci}, first quest cannot have dependencies.")
            if qi > 1 and not deps:
                raise ValueError(f"Chapter {ci}, quest {qi} must depend on a previous quest.")
            if any(dep not in prior_titles for dep in deps):
                raise ValueError(f"Chapter {ci}, quest {qi} depends on a quest that does not precede it.")
            prior_titles.append(str(quest["title"]))
    return data


def _markdown(campaign, manifest):
    lines = [
        f"# {campaign['campaign_title']}",
        "",
        f"- Minecraft: {manifest.get('minecraft', 'unknown')}",
        f"- Loader: {manifest.get('loader', 'unknown')}",
        "- Output type: FTB Quests editor instructions (not an importable SNBT file)",
        "",
        "> **ID verification required:** IDs proposed by the model are syntax-checked, not proven to exist in the installed mod registries. Verify modded item, entity, dimension and advancement IDs in-game/JEI before entering them in FTB Quests.",
        "",
    ]
    for ci, chapter in enumerate(campaign["chapters"], 1):
        lines.extend([f"## Chapter {ci}: {chapter['title']}", "", chapter["description"], "", f"Chapter icon: `{chapter['icon']}`", ""])
        for qi, quest in enumerate(chapter["quests"], 1):
            task = quest["task"]
            reward = quest["reward"]
            lines.extend([
                f"### {ci}.{qi} {quest['title']}",
                "",
                quest["description"],
                "",
                f"- Icon: `{quest['icon']}`",
                f"- Task: {task['type']} · `{task['target']}`" + (f" × {task['count']}" if "count" in task else ""),
                f"- Reward: {reward['type']} · `{reward.get('target', 'XP')}` × {reward['amount']}",
                f"- Depends on: {', '.join(quest['depends_on']) if quest['depends_on'] else 'None'}",
                f"- FTB editor tip: {quest['ftb_tip']}",
                "",
            ])
    lines.extend([
        "## Before building the quest book",
        "",
        "1. Open FTB Quests in the target instance and create the chapters in the listed order.",
        "2. Create each quest and add the listed task and reward.",
        "3. Link dependencies exactly as listed.",
        "4. Verify every candidate ID in the actual installed modpack; replace IDs that do not exist.",
        "5. Save and test the quest book in a disposable world before using the main save.",
        "",
    ])
    return "\n".join(lines)


def generate_ftb_quest_guide(llm, manifest_path, output_dir, log=print):
    manifest_path = Path(manifest_path)
    if not manifest_path.is_file():
        raise FileNotFoundError("No modpack manifest found. Generate/install the modpack first.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    installed = manifest.get("installed", [])
    if not installed:
        raise ValueError("The manifest contains no installed mods.")
    mod_names = [str(item.get("name", "")) for item in installed if item.get("name")]
    context = (
        f"MODPACK CONCEPT:\n{manifest.get('concept', '')}\n"
        f"DESIGN SUMMARY:\n{manifest.get('design_summary', '')}\n"
        f"MINECRAFT: {manifest.get('minecraft', '')} / {manifest.get('loader', '')}\n"
        f"INSTALLED MODS (names only, do not invent their item IDs):\n"
        + "\n".join(f"- {name}" for name in mod_names)
    )
    plan_system = (
        "You are a Minecraft FTB Quests campaign designer. Design a coherent campaign "
        "for the supplied installed modpack. Return ONLY JSON with campaign_title and "
        "chapters. Each chapter has title, description and icon using a plausible "
        "namespace:path ID. Create 2-8 chapters. Keep progression meaningful, avoid "
        "repetitive collection grind, and respect the supplied modpack concept."
    )
    plan = llm.json_from(llm.text(plan_system, context))
    outlines = plan.get("chapters") if isinstance(plan, dict) else None
    if not isinstance(outlines, list) or not 1 <= len(outlines) <= 12:
        raise ValueError("AI did not return a valid chapter outline.")
    chapter_system = (
        "You create one chapter for an FTB Quests editor guide. Return ONLY JSON with "
        "chapter {title, description, icon} and quests array. Each quest has title, "
        "description, icon, task {type, target, count optional}, reward {type, target "
        "optional, amount}, depends_on (previous quest titles), and ftb_tip. Use 3-8 "
        "quests. Allowed task types: item, kill, dimension, advancement. Allowed reward "
        "types: item, xp. IDs must be namespace:path. The installed mod list contains "
        "names only, not registry data: never present a guessed modded ID as verified. "
        "Prefer familiar vanilla IDs when uncertain. Keep the first quest dependency "
        "list empty; each later quest must depend on at least one earlier quest. Respect "
        "Minecraft progression. Do not mention mod names in quest descriptions or tips."
    )
    chapters = []
    for index, outline in enumerate(outlines, 1):
        title = str(outline.get("title", f"Chapter {index}"))
        description = str(outline.get("description", ""))
        log(f"Designing FTB quest chapter {index}/{len(outlines)}: {title}")
        user = (
            context + f"\n\nCHAPTER {index}: {title}\nPURPOSE: {description}\n"
            "Create exactly this one chapter, with 3-8 quests. Use the requested JSON schema."
        )
        chapter = llm.json_from(llm.text(chapter_system, user))
        if isinstance(chapter.get("chapter"), dict):
            chapter_data = chapter["chapter"]
        else:
            chapter_data = {
                "title": chapter.get("title", title),
                "description": chapter.get("description", description),
                "icon": chapter.get("icon", "minecraft:book"),
            }
        chapter_data["title"] = title
        chapter_data["description"] = description
        chapter_data["quests"] = chapter.get("quests", [])
        chapters.append(chapter_data)

    campaign = _validate_campaign({
        "campaign_title": str(plan.get("campaign_title", manifest.get("concept", "Modpack Campaign"))),
        "chapters": chapters,
    })
    campaign["minecraft_version"] = manifest.get("minecraft", "")
    campaign["loader"] = manifest.get("loader", "")
    campaign["installed_mods"] = mod_names
    campaign["id_verification"] = "syntax_only_verify_in_game"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "Modpack_AI_FTB_Quest_Design.json"
    md_path = output_dir / "Modpack_AI_FTB_Quest_Design.md"
    json_path.write_text(json.dumps(campaign, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(_markdown(campaign, manifest), encoding="utf-8")
    log(f"FTB quest design saved: {json_path}")
    log(f"FTB editor guide saved: {md_path}")
    return {
        "status": "generated",
        "json_file": str(json_path),
        "guide_file": str(md_path),
        "chapters": len(chapters),
        "quests": sum(len(chapter["quests"]) for chapter in chapters),
        "id_verification": "syntax_only_verify_in_game",
    }
