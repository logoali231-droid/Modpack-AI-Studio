"""AI structure planner, procedural settlement/dungeon builder and 1.16.5 NBT exporter."""
import gzip
import json
import re
import struct
import zipfile
from pathlib import Path

TARGET_VERSION = "1.16.5"
DATA_VERSION = 2586
MAX_BLOCKS = 120000
MAX_SETTLEMENT_SPAN = 96

MATERIALS = {
    "stone_bricks": "minecraft:stone_bricks", "mossy_stone_bricks": "minecraft:mossy_stone_bricks",
    "cracked_stone_bricks": "minecraft:cracked_stone_bricks", "cobblestone": "minecraft:cobblestone",
    "andesite": "minecraft:andesite", "spruce_planks": "minecraft:spruce_planks",
    "dark_oak_planks": "minecraft:dark_oak_planks", "oak_planks": "minecraft:oak_planks",
    "spruce_log": "minecraft:spruce_log", "dark_oak_log": "minecraft:dark_oak_log",
    "bricks": "minecraft:bricks", "sandstone": "minecraft:sandstone",
    "nether_bricks": "minecraft:nether_bricks", "glass": "minecraft:glass",
    "bookshelf": "minecraft:bookshelf", "lantern": "minecraft:lantern",
    "iron_bars": "minecraft:iron_bars", "oak_stairs": "minecraft:oak_stairs",
    "oak_slab": "minecraft:oak_slab", "oak_fence": "minecraft:oak_fence",
}
DEFAULT_MATERIALS = {
    "wall": "stone_bricks", "accent": "mossy_stone_bricks", "floor": "spruce_planks",
    "roof": "dark_oak_planks", "trim": "spruce_log", "glass": "glass",
}
RESOURCE_ID = re.compile(r"^[a-z0-9_.-]+:[a-z0-9_./-]+$")

SYSTEM_PROMPT = """You are a practical Minecraft Java 1.16.5 world architect.
Return ONLY valid JSON. The request may ask for one building or a settlement.
For one building use:
{"mode":"single","name":"...","structure_type":"tower|keep|outpost|house|ruin",
"width":15,"depth":15,"floors":2,"roof_style":"flat|stepped|pointed",
"style":"...","materials":{"wall":"stone_bricks","accent":"mossy_stone_bricks",
"floor":"spruce_planks","roof":"dark_oak_planks","trim":"spruce_log","glass":"glass"},
"room_types":["entrance","library","treasure"],"features":["balcony","dungeon"]}
For a settlement use:
{"mode":"settlement","name":"...","width":55,"depth":55,
"style":"...","materials":{...},"features":["central_well","main_road","palisade"],
"buildings":[
{"name":"Hall","structure_type":"keep","x":20,"z":20,"width":19,"depth":17,"floors":2,
"roof_style":"stepped","room_types":["entrance","dining","storage"],"features":[]},
{"name":"Smithy","structure_type":"house","x":7,"z":20,"width":13,"depth":11,"floors":1,
"roof_style":"pointed","room_types":["entrance","workshop"],"features":[]}
]}
Rules:
- dimensions for buildings are odd integers 9..25, floors 1..4.
- settlement width/depth 35..96; provide 2..10 buildings, each x/z is its bottom-left coordinate and buildings must fit inside the settlement.
- Allowed structure_type: tower, keep, outpost, house, ruin.
- roof_style: flat, stepped, pointed.
- room_types: entrance, library, treasure, workshop, barracks, dining, storage, altar, prison, garden.
- features for buildings: balcony, watchtower, broken_roof, dungeon, garden.
- settlement features: central_well, main_road, palisade.
- Choose materials only from the supplied palette keys.
- Never return individual block coordinates. Return a compact design, not block-by-block data.
- Be creative but practical, and output JSON only."""

def _bounded_int(data, key, low, high, default=None):
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{key} must be an integer from {low} to {high}.")
    return value

def _validate_materials(raw, extra_materials=None):
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("materials must be an object.")
    palette = dict(MATERIALS)
    for key, value in (extra_materials or {}).items():
        if not re.fullmatch(r"[a-z0-9_]{1,32}", str(key)):
            raise ValueError(f"Invalid custom palette key: {key}")
        if not RESOURCE_ID.fullmatch(str(value)):
            raise ValueError(f"Invalid resource location for custom material {key}: {value}")
        palette[str(key)] = str(value)
    result = dict(DEFAULT_MATERIALS)
    for role in result:
        value = str(raw.get(role, result[role])).lower()
        if value not in palette:
            raise ValueError(f"Unknown material '{value}' for '{role}'. Add it to the custom palette first.")
        result[role] = palette[value]
    return result

def validate_blueprint(data, extra_materials=None):
    if not isinstance(data, dict):
        raise ValueError("The AI blueprint must be a JSON object.")
    kind = str(data.get("structure_type", "house")).lower()
    if kind not in {"tower", "keep", "outpost", "house", "ruin"}:
        raise ValueError(f"Unsupported structure_type: {kind}")
    width = _bounded_int(data, "width", 9, 25, 15)
    depth = _bounded_int(data, "depth", 9, 25, 15)
    floors = _bounded_int(data, "floors", 1, 4, 2)
    if width % 2 == 0 or depth % 2 == 0:
        raise ValueError("Building width and depth must be odd numbers.")
    roof = str(data.get("roof_style", "stepped")).lower()
    if roof not in {"flat", "stepped", "pointed"}:
        raise ValueError("roof_style must be flat, stepped, or pointed.")
    rooms_allowed = {"entrance", "library", "treasure", "workshop", "barracks",
                     "dining", "storage", "altar", "prison", "garden"}
    rooms = data.get("room_types", ["entrance", "storage"])
    if not isinstance(rooms, list):
        raise ValueError("room_types must be an array.")
    rooms = [str(v).lower() for v in rooms if str(v).lower() in rooms_allowed][:8]
    if not rooms:
        rooms = ["entrance", "storage"]
    allowed_features = {"balcony", "watchtower", "broken_roof", "dungeon", "garden"}
    features = data.get("features", [])
    if not isinstance(features, list):
        raise ValueError("features must be an array.")
    features = list(dict.fromkeys(str(v).lower() for v in features if str(v).lower() in allowed_features))
    return {
        "name": str(data.get("name") or "AI Structure")[:64], "structure_type": kind,
        "width": width, "depth": depth, "floors": floors, "roof_style": roof,
        "style": str(data.get("style") or "fantasy")[:120],
        "materials": _validate_materials(data.get("materials"), extra_materials),
        "room_types": rooms, "features": features,
    }

def validate_project(data, extra_materials=None):
    if not isinstance(data, dict):
        raise ValueError("AI design must be a JSON object.")
    mode = str(data.get("mode", "single")).lower()
    if mode != "settlement":
        result = validate_blueprint(data, extra_materials)
        result["mode"] = "single"
        return result
    width = _bounded_int(data, "width", 35, MAX_SETTLEMENT_SPAN, 55)
    depth = _bounded_int(data, "depth", 35, MAX_SETTLEMENT_SPAN, 55)
    raw_buildings = data.get("buildings")
    if not isinstance(raw_buildings, list) or not 2 <= len(raw_buildings) <= 10:
        raise ValueError("A settlement must contain 2 to 10 buildings.")
    buildings = []
    for raw in raw_buildings:
        raw = dict(raw)
        if not raw.get("materials") and isinstance(data.get("materials"), dict):
            raw["materials"] = data["materials"]
        building = validate_blueprint(raw, extra_materials)
        requested_x = _bounded_int(raw, "x", 0, width - 1)
        requested_z = _bounded_int(raw, "z", 0, depth - 1)
        if requested_x + building["width"] > width or requested_z + building["depth"] > depth:
            raise ValueError(f"Building '{building['name']}' extends beyond settlement bounds.")
        def overlaps(px, pz):
            return any(
                px < other["x"] + other["width"] and px + building["width"] > other["x"]
                and pz < other["z"] + other["depth"] and pz + building["depth"] > other["z"]
                for other in buildings
            )
        px, pz = requested_x, requested_z
        if overlaps(px, pz):
            candidates = [
                (x, z) for x in range(0, width - building["width"] + 1, 2)
                for z in range(0, depth - building["depth"] + 1, 2)
                if not overlaps(x, z)
            ]
            if not candidates:
                raise ValueError(f"No free space remains for settlement building '{building['name']}'.")
            px, pz = min(candidates, key=lambda point: abs(point[0] - requested_x) + abs(point[1] - requested_z))
        building["x"], building["z"] = px, pz
        buildings.append(building)
    features = data.get("features", [])
    if not isinstance(features, list):
        raise ValueError("Settlement features must be an array.")
    allowed = {"central_well", "main_road", "palisade"}
    features = list(dict.fromkeys(str(v).lower() for v in features if str(v).lower() in allowed))
    return {"mode": "settlement", "name": str(data.get("name") or "AI Settlement")[:64],
            "width": width, "depth": depth, "style": str(data.get("style") or "fantasy")[:120],
            "materials": _validate_materials(data.get("materials"), extra_materials),
            "features": features, "buildings": buildings}

def _state(name, props=None):
    return (name, tuple(sorted((props or {}).items())))

def _make_building(bp):
    w, d, floors = bp["width"], bp["depth"], bp["floors"]
    mats = bp["materials"]
    blocks = {}
    def put(x, y, z, state):
        if -24 <= y <= 64 and 0 <= x < w and 0 <= z < d:
            blocks[(x, y, z)] = state
    wall, accent = _state(mats["wall"]), _state(mats["accent"])
    floor, roof, trim = _state(mats["floor"]), _state(mats["roof"]), _state(mats["trim"])
    glass = _state(mats["glass"])
    cx, cz, fh = w // 2, d // 2, 4
    for y in range(0, floors * fh + 1, fh):
        for x in range(w):
            for z in range(d):
                if y == 0 or 1 <= x < w - 1 and 1 <= z < d - 1:
                    put(x, y, z, accent if y == 0 else floor)
    for level in range(floors):
        base = level * fh + 1
        for y in range(base, base + 3):
            for x in range(w):
                for z in range(d):
                    if x in (0, w - 1) or z in (0, d - 1):
                        put(x, y, z, trim if x in (0, w - 1) and z in (0, d - 1) and y == base else wall)
        if level == 0:
            put(cx, base, 0, _state("minecraft:air"))
            put(cx, base + 1, 0, _state("minecraft:air"))
        for offset in (-2, 2):
            put(cx + offset, base + 1, 0, glass)
            put(cx + offset, base + 1, d - 1, glass)
            put(0, base + 1, cz + offset, glass)
            put(w - 1, base + 1, cz + offset, glass)
        divider = cx + (1 if level % 2 == 0 else -1)
        for z in range(2, d - 2):
            if z not in (cz - 1, cz, cz + 1):
                put(divider, base + 1, z, accent)
        room = bp["room_types"][level % len(bp["room_types"])]
        if room == "library":
            for x in (2, w - 3):
                for z in (2, d - 3):
                    put(x, base + 1, z, _state("minecraft:bookshelf"))
        elif room == "treasure":
            put(cx, base + 1, cz, _state("minecraft:chest"))
        elif room == "workshop":
            put(cx, base + 1, cz, _state("minecraft:crafting_table"))
            put(cx - 1, base + 1, cz, _state("minecraft:furnace"))
        elif room == "altar":
            put(cx, base + 1, cz, accent)
            put(cx, base + 2, cz, _state("minecraft:lantern"))
        elif room == "prison":
            for x in range(cx - 1, cx + 2):
                put(x, base + 1, cz, _state("minecraft:iron_bars"))
        put(cx, base + 2, cz + 1, _state("minecraft:lantern"))
    for level in range(floors - 1):
        base = level * fh + 1
        for step in range(4):
            put(2 + step, base + step, 2, _state("minecraft:oak_stairs", {
                "facing": "east", "half": "bottom", "shape": "straight", "waterlogged": "false"}))
    if "balcony" in bp["features"]:
        for x in range(cx - 2, cx + 3):
            put(x, fh, 0, _state("minecraft:oak_slab", {"type": "bottom", "waterlogged": "false"}))
            if x in (cx - 2, cx + 2):
                put(x, fh + 1, 0, _state("minecraft:oak_fence"))
    if "watchtower" in bp["features"]:
        y = floors * fh + 1
        for x in range(cx - 2, cx + 3):
            for z in range(cz - 2, cz + 3):
                put(x, y, z, floor)
    roof_y = floors * fh + 1
    layers = 1 if bp["roof_style"] == "flat" else min(5, max(2, min(w, d) // 5))
    for layer in range(layers):
        inset = 0 if bp["roof_style"] == "flat" else layer
        for x in range(inset, w - inset):
            for z in range(inset, d - inset):
                if layer == 0 or x in (inset, w - inset - 1) or z in (inset, d - inset - 1):
                    put(x, roof_y + layer, z, roof)
    if "broken_roof" in bp["features"] and layers > 1:
        for x, z in ((cx - 2, 1), (cx + 1, 2), (1, cz + 2)):
            blocks.pop((x, roof_y + layers - 1, z), None)
    if bp["structure_type"] == "ruin" or "broken_roof" in bp["features"]:
        for level in range(floors):
            for x in (1, w - 2):
                if (x + level) % 2 == 0:
                    blocks.pop((x, level * fh + 2, 0), None)
    if "garden" in bp["features"]:
        for x, z in ((1, 1), (w - 2, 1), (1, d - 2), (w - 2, d - 2)):
            put(x, 1, z, _state("minecraft:flower_pot"))

    # Real underground dungeon: a 13x13 chamber below the foundation, with
    # a perimeter, internal cells, connecting corridor, ladder shaft and loot room.
    if "dungeon" in bp["features"]:
        top, bottom = -1, -7
        for y in range(bottom, top + 1):
            for x in range(cx - 6, cx + 7):
                for z in range(cz - 6, cz + 7):
                    edge = x in (cx - 6, cx + 6) or z in (cz - 6, cz + 6)
                    if y in (bottom, top) or edge:
                        put(x, y, z, accent if y == bottom else wall)
        for y in range(bottom + 1, top):
            for x in range(cx - 5, cx + 6):
                for z in range(cz - 5, cz + 6):
                    put(x, y, z, _state("minecraft:air"))
        # Two side chambers and a treasure cell separated by barred gates.
        for z in range(cz - 4, cz + 5):
            put(cx, -4, z, wall)
        for z in range(cz - 1, cz + 2):
            put(cx, -4, z, _state("minecraft:air"))
        for x in range(cx - 5, cx + 6):
            put(x, -4, cz + 4, wall)
        for x in range(cx - 1, cx + 2):
            put(x, -4, cz + 4, _state("minecraft:iron_bars"))
        put(cx + 3, -5, cz + 2, _state("minecraft:chest"))
        put(cx - 3, -5, cz - 2, _state("minecraft:spawner"))
        # Ladder shaft from ground level to dungeon floor.
        blocks.pop((cx, 0, cz - 5), None)  # open the floor so the ladder is actually reachable
        for y in range(bottom + 1, 2):
            put(cx, y, cz - 5, _state("minecraft:ladder", {"facing": "south"}))
        put(cx, 1, cz - 5, _state("minecraft:oak_trapdoor", {
            "facing": "north", "half": "top", "open": "false", "powered": "false", "waterlogged": "false"}))
        for x, z in ((cx - 5, cz - 5), (cx + 5, cz - 5), (cx - 5, cz + 5), (cx + 5, cz + 5)):
            put(x, -2, z, _state("minecraft:lantern"))
    return blocks

def build_project(project):
    """Return (size, normalized blocks) for a single building or settlement."""
    blocks = {}
    if project["mode"] == "single":
        blocks.update(_make_building(project))
    else:
        width, depth = project["width"], project["depth"]
        materials = project["materials"]
        ground = _state(materials["accent"])
        # Choose an unoccupied plaza for the well and road hub when possible.
        cx, cz = width // 2, depth // 2
        hub_x, hub_z = cx, cz
        if "central_well" in project["features"]:
            free = []
            for hx in range(3, width - 2):
                for hz in range(3, depth - 2):
                    occupied = any(
                        hx - 2 < bp["x"] + bp["width"] and hx + 3 > bp["x"]
                        and hz - 2 < bp["z"] + bp["depth"] and hz + 3 > bp["z"]
                        for bp in project["buildings"]
                    )
                    if not occupied:
                        free.append((hx, hz))
            if free:
                hub_x, hub_z = min(free, key=lambda p: abs(p[0] - cx) + abs(p[1] - cz))
        if "main_road" in project["features"]:
            for bp in project["buildings"]:
                bx, bz = bp["x"] + bp["width"] // 2, bp["z"] + bp["depth"] // 2
                x0, z0 = hub_x, hub_z
                while x0 != bx:
                    blocks[(x0, 0, z0)] = _state("minecraft:gravel")
                    x0 += 1 if bx > x0 else -1
                while z0 != bz:
                    blocks[(x0, 0, z0)] = _state("minecraft:gravel")
                    z0 += 1 if bz > z0 else -1
        for bp in project["buildings"]:
            local = _make_building(bp)
            for (x, y, z), state in local.items():
                pos = (bp["x"] + x, y, bp["z"] + z)
                if pos in blocks and y >= 0:
                    continue
                blocks[pos] = state
        if "central_well" in project["features"]:
            for y in range(0, 3):
                for x in range(hub_x - 2, hub_x + 3):
                    for z in range(hub_z - 2, hub_z + 3):
                        if abs(x - hub_x) == 2 or abs(z - hub_z) == 2:
                            blocks[(x, y, z)] = _state("minecraft:cobblestone")
            blocks[(hub_x, 1, hub_z)] = _state("minecraft:water")
        if "palisade" in project["features"]:
            for x in range(width):
                for z in (0, depth - 1):
                    blocks[(x, 1, z)] = _state("minecraft:oak_fence")
                if x % 4 == 0:
                    blocks[(x, 2, 0)] = _state("minecraft:oak_fence")
                    blocks[(x, 2, depth - 1)] = _state("minecraft:oak_fence")
            for z in range(depth):
                for x in (0, width - 1):
                    blocks[(x, 1, z)] = _state("minecraft:oak_fence")
    if not blocks:
        raise ValueError("The procedural builder produced an empty structure.")
    if len(blocks) > MAX_BLOCKS:
        raise ValueError(f"Generated project exceeds the {MAX_BLOCKS:,}-block safety limit.")
    min_x = min(p[0] for p in blocks)
    min_y = min(p[1] for p in blocks)
    min_z = min(p[2] for p in blocks)
    max_x = max(p[0] for p in blocks)
    max_y = max(p[1] for p in blocks)
    max_z = max(p[2] for p in blocks)
    normalized = {(x-min_x, y-min_y, z-min_z): state for (x,y,z), state in blocks.items()}
    return (max_x-min_x+1, max_y-min_y+1, max_z-min_z+1), normalized

def _utf(value):
    data = str(value).encode("utf-8")
    return struct.pack(">H", len(data)) + data

def _tag(tag_type, name, payload):
    return bytes([tag_type]) + _utf(name) + payload

def _int(value):
    return struct.pack(">i", int(value))

def _list_payload(element_type, values):
    return bytes([element_type]) + _int(len(values)) + b"".join(values)

def _compound_payload(entries):
    return b"".join(entries) + b"\x00"

def write_structure_nbt(path, size, blocks):
    states = sorted(set(blocks.values()), key=lambda item: (item[0], item[1]))
    palette_index = {state: index for index, state in enumerate(states)}
    palette = []
    for name, properties in states:
        props = []
        if properties:
            props.append(_tag(10, "Properties", _compound_payload([
                _tag(8, key, _utf(value)) for key, value in properties
            ])))
        palette.append(_compound_payload([_tag(8, "Name", _utf(name)), *props]))
    block_list = []
    for (x, y, z), state in sorted(blocks.items(), key=lambda item: (item[0][1], item[0][2], item[0][0])):
        block_list.append(_compound_payload([
            _tag(3, "state", _int(palette_index[state])),
            _tag(9, "pos", _list_payload(3, [_int(x), _int(y), _int(z)])),
        ]))
    root = _compound_payload([
        _tag(3, "DataVersion", _int(DATA_VERSION)),
        _tag(9, "size", _list_payload(3, [_int(v) for v in size])),
        _tag(9, "palette", _list_payload(10, palette)),
        _tag(9, "blocks", _list_payload(10, block_list)),
        _tag(9, "entities", _list_payload(10, [])),
    ])
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as handle:
        handle.write(gzip.compress(bytes([10]) + _utf("") + root, mtime=0))
    return target

def discover_modded_block_palette(mods_directory, limit=3000):
    """Suggest namespaced block IDs from blockstate assets inside local mod JARs.

    Presence of a blockstate asset is a useful discovery hint, not proof that the
    mod registers that block in the selected Minecraft/loader runtime.
    """
    root = Path(mods_directory).expanduser()
    if not root.is_dir():
        raise ValueError(f"Mods directory does not exist: {root}")
    found = {}
    for jar_path in sorted(root.glob("*.jar")):
        try:
            with zipfile.ZipFile(jar_path) as archive:
                for entry in archive.namelist():
                    match = re.match(r"^assets/([a-z0-9_.-]+)/blockstates/(.+)\.json$", entry)
                    if not match or match.group(1) == "minecraft":
                        continue
                    namespace, block_path = match.groups()
                    resource_id = f"{namespace}:{block_path}"
                    base = re.sub(r"[^a-z0-9_]", "_", f"{namespace}_{block_path}")[:26].strip("_")
                    alias = base or "mod_block"
                    suffix = 2
                    while alias in found and found[alias] != resource_id:
                        alias = f"{base[:22]}_{suffix}"
                        suffix += 1
                    found[alias] = resource_id
                    if len(found) >= limit:
                        return found
        except (OSError, zipfile.BadZipFile):
            continue
    return found


def generate_structure(llm, description, minecraft_version, output_path, log, progress=None, custom_palette=None):
    if str(minecraft_version).strip() != TARGET_VERSION:
        raise ValueError(f"Structure export currently supports Minecraft {TARGET_VERSION} only; selected {minecraft_version}.")
    if not str(description).strip():
        raise ValueError("Describe the structure before generating it.")
    custom_palette = custom_palette or {}
    if not isinstance(custom_palette, dict):
        raise ValueError("Custom block palette must be a JSON object mapping short keys to namespace:block IDs.")
    for key, value in custom_palette.items():
        if not re.fullmatch(r"[a-z0-9_]{1,32}", str(key)) or not RESOURCE_ID.fullmatch(str(value)):
            raise ValueError(f"Invalid custom palette entry: {key} = {value}")
    palette = dict(MATERIALS)
    palette.update(custom_palette)
    system = SYSTEM_PROMPT + "\nCUSTOM MATERIAL PALETTE (choose keys only):\n" + json.dumps(palette, ensure_ascii=False)
    if progress:
        progress(10, 100, "Qwen is designing the structure or settlement…")
    log("Structure Designer · asking the model for a compact architectural plan.")
    raw = llm.text(system, f"USER REQUEST:\n{description.strip()[:5000]}\nReturn the design JSON only.")
    try:
        project = validate_project(llm.json_from(raw), custom_palette)
    except (ValueError, TypeError, KeyError) as first_error:
        log(f"Blueprint validation failed ({first_error}); asking Qwen for one constrained repair.")
        repair_prompt = (
            "Your previous JSON blueprint failed validation. Correct it using the exact schema and rules. "
            "Preserve the user's creative intent while fixing the error. "
            f"Validation error: {first_error}\nPrevious response:\n{raw[:12000]}\n"
            "Return only the corrected JSON object."
        )
        repaired = llm.text(system, repair_prompt)
        project = validate_project(llm.json_from(repaired), custom_palette)
    if progress:
        progress(45, 100, "Procedural engine is building rooms, dungeons and settlement layout…")
    size, blocks = build_project(project)
    if progress:
        progress(75, 100, "Writing Minecraft 1.16.5 structure NBT…")
    write_structure_nbt(output_path, size, blocks)
    log(f"Generated {len(blocks):,} blocks · {size[0]}x{size[1]}x{size[2]} · {project['mode']}.")
    # Lightweight sample for the interactive viewport; the NBT contains every block.
    preview_source = list(blocks.items())
    preview_stride = max(1, len(preview_source) // 5000)
    preview = [[x, y, z, state[0]] for (x, y, z), state in preview_source[::preview_stride][:5000]
               if not state[0].endswith(":air")]
    return {"success": True, "name": project["name"], "file": str(output_path),
            "minecraft": TARGET_VERSION, "dimensions": list(size), "block_count": len(blocks),
            "mode": project["mode"], "blueprint": project, "preview_blocks": preview}
