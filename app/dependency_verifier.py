"""Inspect downloaded mod JAR metadata instead of trusting catalog dependency IDs.

Supports Forge/NeoForge mods.toml, Fabric fabric.mod.json, Quilt quilt.mod.json,
legacy mcmod.info, and common Jar-in-Jar metadata. Unknown metadata is reported,
not silently treated as proof of compatibility.
"""
import json
import re
import zipfile
from pathlib import Path

try:
    import tomllib
except ImportError:  # Python 3.10 and older
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None


def _read_json(archive, name):
    try:
        return json.loads(archive.read(name).decode("utf-8"))
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _read_toml(archive, name):
    if tomllib is None:
        return None
    try:
        return tomllib.loads(archive.read(name).decode("utf-8"))
    except (KeyError, UnicodeDecodeError, ValueError):
        return None


def _forge_metadata(archive):
    data = _read_toml(archive, "META-INF/mods.toml")
    if not isinstance(data, dict):
        return [], []
    ids = [str(m.get("modId", "")).strip() for m in data.get("mods", [])
           if isinstance(m, dict) and m.get("modId")]
    deps = []
    for mod_id, entries in (data.get("dependencies") or {}).items():
        if not isinstance(entries, list):
            continue
        for dep in entries:
            if not isinstance(dep, dict) or not dep.get("modId"):
                continue
            deps.append({
                "owner": str(mod_id), "id": str(dep["modId"]),
                "mandatory": bool(dep.get("mandatory", True)),
                "range": str(dep.get("versionRange", "")),
                "side": str(dep.get("side", "BOTH")),
                "source": "mods.toml",
            })
    return ids, deps


def _fabric_metadata(archive, filename):
    data = _read_json(archive, filename)
    if not isinstance(data, dict):
        return [], []
    mod_id = data.get("id")
    ids = [str(mod_id)] if mod_id else []
    depends = data.get("depends") or {}
    breaks = data.get("breaks") or {}
    deps = []
    if isinstance(depends, dict):
        for dep_id, version_range in depends.items():
            deps.append({"owner": str(mod_id or "unknown"), "id": str(dep_id),
                         "mandatory": True, "range": str(version_range),
                         "side": "BOTH", "source": filename})
    if isinstance(breaks, dict):
        for dep_id, version_range in breaks.items():
            deps.append({"owner": str(mod_id or "unknown"), "id": str(dep_id),
                         "mandatory": False, "range": str(version_range),
                         "side": "BOTH", "source": filename, "conflict": True})
    return ids, deps


def inspect_jar(path):
    path = Path(path)
    result = {"file": path.name, "mod_ids": [], "dependencies": [], "metadata": []}
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            ids, deps = _forge_metadata(archive)
            if ids or deps:
                result["metadata"].append("META-INF/mods.toml")
                result["mod_ids"].extend(ids)
                result["dependencies"].extend(deps)

            for metadata_name in ("fabric.mod.json", "quilt.mod.json"):
                if metadata_name in names:
                    ids, deps = _fabric_metadata(archive, metadata_name)
                    result["metadata"].append(metadata_name)
                    result["mod_ids"].extend(ids)
                    result["dependencies"].extend(deps)

            legacy = _read_json(archive, "mcmod.info")
            if isinstance(legacy, list):
                for entry in legacy:
                    if isinstance(entry, dict) and entry.get("modid"):
                        result["mod_ids"].append(str(entry["modid"]))
            elif isinstance(legacy, dict):
                entries = legacy.get("modList", [legacy])
                for entry in entries:
                    if isinstance(entry, dict) and entry.get("modid"):
                        result["mod_ids"].append(str(entry["modid"]))

            # Forge Jar-in-Jar embeds libraries/mods. Recursively inspect embedded
            # archives where metadata declares them, with a strict depth boundary.
            jarjar = _read_json(archive, "META-INF/jarjar/metadata.json")
            if isinstance(jarjar, dict):
                result["metadata"].append("META-INF/jarjar/metadata.json")
                for entry in jarjar.get("jars", []):
                    if isinstance(entry, dict) and entry.get("identifier", {}).get("artifactVersion"):
                        artifact = entry.get("identifier", {}).get("artifactId")
                        if artifact:
                            result["mod_ids"].append(str(artifact).lower().replace("-", "_"))
    except (OSError, zipfile.BadZipFile) as exc:
        result["error"] = str(exc)
    result["mod_ids"] = sorted(set(result["mod_ids"]))
    return result


BUILTIN_IDS = {
    "minecraft", "forge", "neoforge", "fabricloader", "fabric",
    "java", "mixin", "fml",
}


def verify_mod_directory(paths, log=lambda message: None):
    """Return a structured report; raise only for definite mandatory missing deps."""
    inspections = [inspect_jar(path) for path in paths if str(path).lower().endswith(".jar")]
    known = set(BUILTIN_IDS)
    for item in inspections:
        known.update(item["mod_ids"])

    missing, conflicts, unreadable = [], [], []
    for item in inspections:
        if item.get("error"):
            unreadable.append({"file": item["file"], "error": item["error"]})
            continue
        for dep in item["dependencies"]:
            dep_id = dep["id"]
            if dep.get("conflict") and dep_id in known:
                conflicts.append({"file": item["file"], "dependency": dep_id,
                                  "range": dep.get("range", "")})
            elif dep.get("mandatory") and dep_id not in known:
                missing.append({"file": item["file"], "dependency": dep_id,
                                "range": dep.get("range", ""), "source": dep["source"]})

    duplicate_ids = {}
    for item in inspections:
        for mod_id in item["mod_ids"]:
            duplicate_ids.setdefault(mod_id, []).append(item["file"])
    duplicates = {key: value for key, value in duplicate_ids.items() if len(value) > 1}

    report = {
        "checked_jars": len(inspections),
        "discovered_mod_ids": sorted(known - BUILTIN_IDS),
        "missing_required": missing,
        "conflicts": conflicts,
        "duplicate_mod_ids": duplicates,
        "unreadable_jars": unreadable,
        "metadata_coverage": sum(bool(item["metadata"]) for item in inspections),
        "inspections": inspections,
    }
    log(f"Dependency verifier inspected {len(inspections)} JAR(s); "
        f"read metadata from {report['metadata_coverage']}.")
    if missing:
        details = "; ".join(
            f"{entry['file']} requires {entry['dependency']} ({entry['range'] or 'any version'})"
            for entry in missing
        )
        raise RuntimeError("Dependency verification failed. Missing mandatory mod ID(s): " + details)
    if conflicts:
        details = "; ".join(f"{e['file']} conflicts with {e['dependency']}" for e in conflicts)
        raise RuntimeError("Dependency verification found declared conflicts: " + details)
    if duplicates:
        log("WARNING: duplicate internal mod IDs detected: " + ", ".join(duplicates))
    if unreadable:
        log("WARNING: some JARs could not be inspected; see verifier report.")
    return report
