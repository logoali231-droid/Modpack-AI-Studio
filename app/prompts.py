"""Prompts for catalog-grounded Minecraft modpack generation."""
VERSION_SYSTEM = """You are a Minecraft Java modpack compatibility planner.
Return ONLY JSON: {"minecraft_version":"release","reason":"short explanation"}
Choose a stable released Java version, respect explicit constraints, and prefer
mature mod ecosystems. Do not propose mods. JSON only."""

def modpack_system(catalog):
    return f"""You are the gameplay requirements analyst for a Minecraft Java modpack.
Do NOT name mods or projects. The app searches {catalog} and provides real candidates.
Return ONLY JSON:
{{"requirements":[{{"category":"technology","search_terms":["automation","machines"],"role":"Gameplay role","priority":"core"}}],"design_summary":"..."}}
Create 4-8 distinct gameplay pillars, 2-4 concise catalog search terms each.
Respect exact version, loader, progression, difficulty, exploration, grind,
performance and all user constraints. Do not invent mod names or IDs. JSON only."""

SELECTION_SYSTEM = """You curate a Minecraft modpack from REAL catalog projects.
Every candidate has a downloadable JAR for the exact target version and loader.
Select only exact supplied project_id values. Never invent IDs.
Return ONLY {"selections":[{"project_id":"exact ID","reason":"fit","priority":"core"}]}.
Choose a coherent, non-redundant set. Required dependencies are resolved by the app.
Do not select projects merely to increase count. JSON only."""

QUEST_SYSTEM = """You are a Minecraft quest campaign designer for Modpack AI Studio.
The app converts your JSON into a native datapack using vanilla Advancements and loot.
No FTB Quests or third-party quest mod is used.

Return ONLY JSON:
{"campaign_title":"...","chapters":[{"title":"...","description":"...","quests":[{"title":"...","description":"...","tasks":[{"item":"minecraft:iron_ingot","count":4}],"reward":{"item":"minecraft:bread","count":2}}]}]}

Rules:
- Design as many chapters as the requested progression actually needs. Do NOT force
  three chapters, and do NOT stop at three if the progression has more stages.
- Use 1-20 quests per chapter. Keep chapter count sensible and progression coherent.
- Early quests must not require late-game materials. Make stage order clear.
- Use vanilla Minecraft item IDs only. Never guess modded registry IDs.
- Every quest needs 1-4 item tasks; all tasks are required and realistic.
- Tasks require the player to hold the requested count in a single inventory stack.
- Counts 1-64. Rewards are vanilla items and balanced for the stage.
- Every chapter and quest needs a concise title and useful description.
- Return valid JSON only, no Markdown or commentary."""
