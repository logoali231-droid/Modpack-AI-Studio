"""AI-assisted procedural Minecraft structure generation.

The model designs a bounded blueprint. Deterministic code builds the blocks and
writes a gzip-compressed vanilla structure NBT file. Initial exporter target:
Minecraft Java 1.16.5 (DataVersion 2586).
"""
import gzip
import json
import struct
from pathlib import Path

from .llm import LLMClient

TARGET_VERSION = "1.16.5"
DATA_VERSION = 2586
MAX_BLOCKS = 60000

MATERIALS = {
    "stone_bricks": "minecraft:stone_bricks",
    "mossy_stone_bricks": "minecraft:mossy_stone_bricks",
    "cracked_stone_bricks": "minecraft:cracked_stone_bricks",
    "cobblestone": "minecraft:cobblestone",
    "andesite": "minecraft:andesite",
    "spruce_planks": "minecraft:spruce_planks",
    "dark_oak_planks": "minecraft:dark_oak_planks",
    "oak_planks": "minecraft:oak_planks",
    "spruce_log": "minecraft:spruce_log",
    "dark_oak_log": "minecraft:dark_oak_log",
    "bricks": "minecraft:bricks",
    "sandstone": "minecraft:sandstone",
    "nether_bricks": "minecraft:nether_bricks",
    "glass": "minecraft:glass",
    "bookshelf": "minecraft:bookshelf",
    "lantern": "minecraft:lantern",
    "iron_bars": "minecraft:iron_bars",
}

DEFAULT_MATERIALS = {
    "wall": "stone_bricks",
    "accent": "mossy_stone_bricks",
    "floor": "spruce_planks",
    "roof": "dark_oak_planks",
    "trim": "spruce_log",
    "glass": "glass",
}

SYSTEM_PROMPT = """You are an architectural planner for a Minecraft structure generator.
Return ONLY one JSON object with this schema:
{
  "name":"short structure name",
  "structure_type":"tower|keep|outpost|house|ruin",
  "width":15,
  "depth":15,
  "floors":3,
  "roof_style":"flat|stepped|pointed",
  "style":"short visual style",
  "materials":{"wall":"stone_bricks","accent":"mossy_stone_bricks","floor":"spruce_planks","roof":"dark_oak_planks","trim":"spruce_log","glass":"glass"},
  "room_types":["entrance","library","treasure","workshop"],
  "features":["balcony","watchtower","broken_roof","cellar","garden"]
}
Rules:
- The target is Minecraft Java 1.16.5. Use only the supplied material keys and enums.
- width and depth must be odd integers from 9 through 25. floors must be 1 through 4.
- material values must be keys from this whitelist: stone_bricks, mossy_stone_bricks,
  cracked_stone_bricks, cobblestone, andesite, spruce_planks, dark_oak_planks,
  oak_planks, spruce_log, dark_oak_log, bricks, sandstone, nether_bricks,
  glass, bookshelf, lantern, iron_bars.
- room_types may contain: entrance, library, treasure, workshop, barracks, dining,
  storage, altar, prison, garden. Return 2-6 entries.
- features may contain: balcony, watchtower, broken_roof, cellar, garden. Return 0-4 entries.
- Be coherent and imaginative, but do not return block coordinates or individual blocks.
- Return valid JSON only. No markdown or explanation."""

def validate_blueprint(data):
    if not isinstance(data, dict):
        raise ValueError("The AI blueprint must be a JSON object.")
    allowed_types = {"tower", "keep", "outpost", "house", "ruin"}
    kind = str(data.get("structure_type", "house")).lower()
    if kind not in allowed_types:
        raise ValueError(f"Unsupported structure_type: {kind}")
    def bounded_int(key, low, high, default):
        value = data.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ValueError(f"{key} must be an integer from {low} to {high}.")
        return value
    width = bounded_int("width", 9, 25, 15)
    depth = bounded_int("depth", 9, 25, 15)
    floors = bounded_int("floors", 1, 4, 2)
    if width % 2 == 0 or depth % 2 == 0:
        raise ValueError("Structure width and depth must be odd numbers.")
    roof = str(data.get("roof_style", "stepped")).lower()
    if roof not in {"flat", "stepped", "pointed"}:
        raise ValueError("roof_style must be flat, stepped, or pointed.")
    raw_materials = data.get("materials", {})
    if not isinstance(raw_materials, dict):
        raise ValueError("materials must be an object.")
    materials = dict(DEFAULT_MATERIALS)
    for key in materials:
        candidate = str(raw_materials.get(key, materials[key])).lower()
        if candidate not in MATERIALS:
            raise ValueError(f"Unknown material '{candidate}' for '{key}'.")
        materials[key] = candidate
    allowed_rooms = {"entrance", "library", "treasure", "workshop", "barracks",
                     "dining", "storage", "altar", "prison", "garden"}
    rooms = data.get("room_types", ["entrance", "storage", "workshop"])
    if not isinstance(rooms, list):
        raise ValueError("room_types must be an array.")
    rooms = [str(item).lower() for item in rooms if str(item).lower() in allowed_rooms][:6]
    if len(rooms) < 2:
        rooms = ["entrance", "storage"]
    allowed_features = {"balcony", "watchtower", "broken_roof", "cellar", "garden"}
    features = data.get("features", [])
    if not isinstance(features, list):
        raise ValueError("features must be an array.")
    features = list(dict.fromkeys(str(item).lower() for item in features
                                  if str(item).lower() in allowed_features))[:4]
    return {
        "name": str(data.get("name") or "AI Structure")[:64],
        "structure_type": kind, "width": width, "depth": depth, "floors": floors,
        "roof_style": roof, "style": str(data.get("style") or "fantasy")[:120],
        "materials": materials, "room_types": rooms, "features": features,
    }

def _block_state(name, properties=None):
    return (name, tuple(sorted((properties or {}).items())))

def build_blocks(blueprint):
    """Build a bounded, deterministic structure from a validated blueprint."""
    w, d, floors = blueprint["width"], blueprint["depth"], blueprint["floors"]
    mats = {key: MATERIALS[value] for key, value in blueprint["materials"].items()}
    blocks = {}
    def put(x, y, z, state):
        if 0 <= x < w and 0 <= z < d and 0 <= y < 48:
            blocks[(x, y, z)] = state
    air = _block_state("minecraft:air")
    wall = _block_state(mats["wall"])
    accent = _block_state(mats["accent"])
    floor = _block_state(mats["floor"])
    roof = _block_state(mats["roof"])
    trim = _block_state(mats["trim"])
    glass = _block_state(mats["glass"])
    center_x, center_z = w // 2, d // 2
    floor_height = 4
    total_height = floors * floor_height + 2

    # Foundation and a raised, solid floor for each storey.
    for y in range(0, floors * floor_height + 1, floor_height):
        for x in range(w):
            for z in range(d):
                if y == 0 or 1 <= x < w - 1 and 1 <= z < d - 1:
                    put(x, y, z, accent if y == 0 else floor)

    # Perimeter walls, corner supports, doors, and windows.
    for level in range(floors):
        base = level * floor_height + 1
        for y in range(base, base + 3):
            for x in range(w):
                for z in range(d):
                    if x not in (0, w - 1) and z not in (0, d - 1):
                        continue
                    is_corner = x in (0, w - 1) and z in (0, d - 1)
                    state = trim if is_corner and y == base else wall
                    put(x, y, z, state)
        # Front entrance on the ground floor.
        if level == 0:
            put(center_x, base, 0, air)
            put(center_x, base + 1, 0, air)
        # Symmetrical windows on all four sides.
        for offset in (-2, 2):
            wx = center_x + offset
            wz = center_z + offset
            for y in (base + 1,):
                if level > 0 or wx != center_x:
                    put(wx, y, 0, glass)
                    put(wx, y, d - 1, glass)
                    put(0, y, wz, glass)
                    put(w - 1, y, wz, glass)
        # Interior room divider, offset per level to avoid identical floors.
        divider_x = center_x + (1 if level % 2 == 0 else -1)
        for z in range(2, d - 2):
            if z not in (center_z - 1, center_z, center_z + 1):
                put(divider_x, base + 1, z, accent)
        # Decorative room anchors based on the room list.
        room = blueprint["room_types"][level % len(blueprint["room_types"])]
        if room == "library":
            for x in (2, w - 3):
                for z in (2, d - 3):
                    put(x, base + 1, z, _block_state("minecraft:bookshelf"))
        elif room == "treasure":
            put(center_x, base + 1, center_z, _block_state("minecraft:chest"))
        elif room == "workshop":
            put(center_x, base + 1, center_z, _block_state("minecraft:crafting_table"))
            put(center_x - 1, base + 1, center_z, _block_state("minecraft:furnace"))
        elif room == "altar":
            put(center_x, base + 1, center_z, accent)
            put(center_x, base + 2, center_z, _block_state("minecraft:lantern"))
        elif room == "prison":
            for x in range(center_x - 1, center_x + 2):
                put(x, base + 1, center_z, _block_state("minecraft:iron_bars"))
        # Light source near the central support.
        put(center_x, base + 2, center_z + 1, _block_state("minecraft:lantern"))

    # Interior staircase: a compact switchback-like stepped run.
    for level in range(floors - 1):
        base = level * floor_height + 1
        for step in range(4):
            put(2 + step, base + step, 2, _block_state(
                "minecraft:oak_stairs", {"facing": "east", "half": "bottom", "shape": "straight", "waterlogged": "false"}
            ))

    # Optional balcony on the front facade.
    if "balcony" in blueprint["features"]:
        for x in range(center_x - 2, center_x + 3):
            put(x, floor_height, 0, _block_state("minecraft:oak_slab", {"type": "bottom", "waterlogged": "false"}))
            if x in (center_x - 2, center_x + 2):
                put(x, floor_height + 1, 0, _block_state("minecraft:oak_fence"))

    # Optional lookout platform at the top.
    if "watchtower" in blueprint["features"] and w >= 11 and d >= 11:
        y = floors * floor_height + 1
        for x in range(center_x - 2, center_x + 3):
            for z in range(center_z - 2, center_z + 3):
                put(x, y, z, floor)
        for x, z in ((center_x - 2, center_z - 2), (center_x + 2, center_z - 2),
                     (center_x - 2, center_z + 2), (center_x + 2, center_z + 2)):
            put(x, y + 1, z, trim)
            put(x, y + 2, z, trim)

    # Roof layers shrink inward, making a stepped or pointed silhouette.
    roof_y = floors * floor_height + 1
    layers = 1 if blueprint["roof_style"] == "flat" else min(4, max(2, min(w, d) // 5))
    for layer in range(layers):
        inset = 0 if blueprint["roof_style"] == "flat" else layer
        y = roof_y + layer
        for x in range(inset, w - inset):
            for z in range(inset, d - inset):
                if layer == 0 or x in (inset, w - inset - 1) or z in (inset, d - inset - 1):
                    put(x, y, z, roof)
    if "broken_roof" in blueprint["features"] and layers > 1:
        for x, z in ((center_x - 2, 1), (center_x + 1, 2), (1, center_z + 2)):
            blocks.pop((x, roof_y + layers - 1, z), None)

    # Ruins receive controlled gaps and mossy accents, never random corruption.
    if blueprint["structure_type"] == "ruin" or "broken_roof" in blueprint["features"]:
        for level in range(floors):
            y = level * floor_height + 2
            for x in (1, w - 2):
                if (x + level) % 2 == 0:
                    blocks.pop((x, y, 0), None)
    if "garden" in blueprint["features"]:
        for x, z in ((1, 1), (w - 2, 1), (1, d - 2), (w - 2, d - 2)):
            put(x, 1, z, _block_state("minecraft:flower_pot"))
    if "cellar" in blueprint["features"]:
        # A cellar entrance is represented by a trapdoor and ladder access inside.
        put(center_x, 1, center_z - 2, _block_state("minecraft:ladder", {"facing": "south"}))
        put(center_x, 2, center_z - 2, _block_state("minecraft:ladder", {"facing": "south"}))
        put(center_x, 3, center_z - 2, _block_state("minecraft:oak_trapdoor", {
            "facing": "north", "half": "top", "open": "false", "powered": "false", "waterlogged": "false"
        }))

    if len(blocks) > MAX_BLOCKS:
        raise ValueError(f"Generated structure exceeds the {MAX_BLOCKS:,}-block safety limit.")
    if not blocks:
        raise ValueError("The procedural builder produced an empty structure.")
    min_x = min(pos[0] for pos in blocks)
    min_y = min(pos[1] for pos in blocks)
    min_z = min(pos[2] for pos in blocks)
    max_x = max(pos[0] for pos in blocks)
    max_y = max(pos[1] for pos in blocks)
    max_z = max(pos[2] for pos in blocks)
    normalized = {
        (x - min_x, y - min_y, z - min_z): state
        for (x, y, z), state in blocks.items()
    }
    size = (max_x - min_x + 1, max_y - min_y + 1, max_z - min_z + 1)
    return size, normalized

def _utf(value):
    data = str(value).encode("utf-8")
    return struct.pack(">H", len(data)) + data

def _tag(tag_type, name, payload):
    return bytes([tag_type]) + _utf(name) + payload

def _int(value):
    return struct.pack(">i", int(value))

def _string(value):
    return _utf(value)

def _list_payload(element_type, values):
    return bytes([element_type]) + _int(len(values)) + b"".join(values)

def _compound_payload(entries):
    return b"".join(entries) + b"\x00"

def write_structure_nbt(path, size, blocks):
    """Write vanilla structure NBT (gzip, big-endian) for Java 1.16.5."""
    states = sorted(set(blocks.values()), key=lambda item: (item[0], item[1]))
    palette_index = {state: index for index, state in enumerate(states)}
    palette_entries = []
    for name, properties in states:
        props = []
        if properties:
            props.append(_tag(10, "Properties", _compound_payload([
                _tag(8, key, _string(value)) for key, value in properties
            ])))
        palette_entries.append(_compound_payload([
            _tag(8, "Name", _string(name)), *props
        ]))
    block_entries = []
    for (x, y, z), state in sorted(blocks.items(), key=lambda item: (item[0][1], item[0][2], item[0][0])):
        block_entries.append(_compound_payload([
            _tag(3, "state", _int(palette_index[state])),
            _tag(9, "pos", _list_payload(3, [_int(x), _int(y), _int(z)])),
        ]))
    root = _compound_payload([
        _tag(3, "DataVersion", _int(DATA_VERSION)),
        _tag(9, "size", _list_payload(3, [_int(v) for v in size])),
        _tag(9, "palette", _list_payload(10, palette_entries)),
        _tag(9, "blocks", _list_payload(10, block_entries)),
        _tag(9, "entities", _list_payload(10, [])),
    ])
    payload = bytes([10]) + _utf("") + root
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as handle:
        handle.write(gzip.compress(payload, mtime=0))
    return target

def generate_structure(llm, description, minecraft_version, output_path, log, progress=None):
    if str(minecraft_version).strip() != TARGET_VERSION:
        raise ValueError(
            f"The first structure exporter supports Minecraft {TARGET_VERSION} only. "
            f"The selected version is {minecraft_version}. No file was written."
        )
    if not str(description).strip():
        raise ValueError("Describe the structure before generating it.")
    if progress:
        progress(10, 100, "Qwen is designing a compact structure blueprint…")
    log("Structure Designer · asking the model for an architectural blueprint.")
    raw = llm.text(SYSTEM_PROMPT, (
        f"USER STRUCTURE REQUEST:\n{description.strip()[:5000]}\n\n"
        "Design the structure. Return the compact blueprint JSON only."
    ))
    blueprint = validate_blueprint(llm.json_from(raw))
    if progress:
        progress(45, 100, "Procedural builder is constructing the block layout…")
    log(
        f"Blueprint accepted: {blueprint['name']} · {blueprint['width']}x"
        f"{blueprint['depth']} · {blueprint['floors']} floor(s) · {blueprint['structure_type']}."
    )
    size, blocks = build_blocks(blueprint)
    if progress:
        progress(75, 100, "Writing Minecraft structure NBT…")
    write_structure_nbt(output_path, size, blocks)
    log(f"Structure exported: {output_path}")
    log(f"Generated {len(blocks):,} blocks; dimensions {size[0]}x{size[1]}x{size[2]}.")
    return {
        "success": True, "name": blueprint["name"], "file": str(output_path),
        "minecraft": TARGET_VERSION, "dimensions": list(size),
        "block_count": len(blocks), "blueprint": blueprint,
    }
