"""Deep inspection of Minecraft mod archives and declared dependency constraints.

The verifier treats catalog metadata as hints only. Actual JAR metadata is parsed
from Forge/NeoForge mods.toml, Fabric/Quilt JSON and legacy mcmod.info.
"""
import json
import re
import zipfile
from pathlib import Path

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None


BUILTIN_IDS = {
    "minecraft", "forge", "neoforge", "fabricloader", "fabric",
    "java", "mixin", "fml", "quilt_loader",
}
MAX_ARCHIVE_ENTRY = 8 * 1024 * 1024
MAX_TOTAL_METADATA = 24 * 1024 * 1024
MAX_JARJAR_DEPTH = 3


def _safe_read(archive, name):
    try:
        info = archive.getinfo(name)
        if info.file_size > MAX_ARCHIVE_ENTRY:
            return None
        return archive.read(name)
    except (KeyError, OSError, RuntimeError, zipfile.BadZipFile):
        return None


def _read_json(archive, name):
    raw = _safe_read(archive, name)
    if raw is None:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _read_toml(archive, name):
    if tomllib is None:
        return None
    raw = _safe_read(archive, name)
    if raw is None:
        return None
    try:
        return tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None


def _bool(value, default=True):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "1")
    return default if value is None else bool(value)


def _forge_metadata(archive):
    data = _read_toml(archive, "META-INF/mods.toml")
    if not isinstance(data, dict):
        return [], {}, []
    ids, versions = [], {}
    for mod in data.get("mods", []):
        if not isinstance(mod, dict) or not mod.get("modId"):
            continue
        mod_id = str(mod["modId"]).strip()
        if not mod_id:
            continue
        ids.append(mod_id)
        version = str(mod.get("version", "")).strip()
        if version and not version.startswith("${"):
            versions[mod_id] = version

    dependencies = []
    for owner, entries in (data.get("dependencies") or {}).items():
        if not isinstance(entries, list):
            continue
        for dep in entries:
            if not isinstance(dep, dict) or not dep.get("modId"):
                continue
            dependencies.append({
                "owner": str(owner),
                "id": str(dep["modId"]).strip(),
                "mandatory": _bool(dep.get("mandatory"), True),
                "range": str(dep.get("versionRange", "")).strip(),
                "side": str(dep.get("side", "BOTH")).upper(),
                "source": "META-INF/mods.toml",
                "kind": "requires",
            })
    return ids, versions, dependencies


def _fabric_metadata(archive, filename):
    data = _read_json(archive, filename)
    if not isinstance(data, dict):
        return [], {}, []
    mod_id = str(data.get("id") or "").strip()
    ids = [mod_id] if mod_id else []
    version = str(data.get("version") or "").strip()
    versions = {mod_id: version} if mod_id and version and not version.startswith("${") else {}
    dependencies = []
    for field, kind, mandatory in (
        ("depends", "requires", True),
        ("recommends", "recommends", False),
        ("suggests", "suggests", False),
        ("breaks", "breaks", False),
        ("conflicts", "breaks", False),
    ):
        entries = data.get(field) or {}
        if not isinstance(entries, dict):
            continue
        for dep_id, constraint in entries.items():
            dependencies.append({
                "owner": mod_id or "unknown",
                "id": str(dep_id),
                "mandatory": mandatory,
                "range": str(constraint),
                "side": "BOTH",
                "source": filename + ":" + field,
                "kind": kind,
            })
    for provided in data.get("provides", []):
        if isinstance(provided, str) and provided.strip():
            ids.append(provided.strip())
    return ids, versions, dependencies


def _legacy_metadata(archive):
    data = _read_json(archive, "mcmod.info")
    entries = data if isinstance(data, list) else (
        data.get("modList", [data]) if isinstance(data, dict) else []
    )
    ids, versions = [], {}
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("modid"):
            continue
        mod_id = str(entry["modid"]).strip()
        ids.append(mod_id)
        version = str(entry.get("version", "")).strip()
        if version:
            versions[mod_id] = version
    return ids, versions


def _version_key(value):
    """Comparable token tuple for common numeric Minecraft mod versions."""
    value = str(value or "").strip().lower()
    if value.startswith("v"):
        value = value[1:]
    tokens = re.findall(r"\d+|[a-z]+", value)
    if not tokens:
        return None
    result = []
    for token in tokens:
        result.append((0, int(token)) if token.isdigit() else (1, token))
    while result and result[-1] == (0, 0):
        result.pop()
    return tuple(result)


def _compare_versions(left, right):
    a, b = _version_key(left), _version_key(right)
    if a is None or b is None:
        return None
    # Pad numeric releases so 1.2 and 1.2.0 compare as equivalent.
    length = max(len(a), len(b))
    a += ((0, 0),) * (length - len(a))
    b += ((0, 0),) * (length - len(b))
    return (a > b) - (a < b)


def _single_range_matches(version, expression):
    expression = expression.strip()
    if not expression or expression in ("*", "any"):
        return True
    if expression.startswith(("[", "(")) and expression.endswith(("]", ")")):
        body = expression[1:-1]
        if "," not in body:
            return _compare_versions(version, body.strip()) == 0
        lower, upper = (part.strip() for part in body.split(",", 1))
        if lower:
            cmp = _compare_versions(version, lower)
            if cmp is None or cmp < 0 or (cmp == 0 and expression[0] == "("):
                return False
        if upper:
            cmp = _compare_versions(version, upper)
            if cmp is None or cmp > 0 or (cmp == 0 and expression[-1] == ")"):
                return False
        return True
    cmp = _compare_versions(version, expression)
    return cmp == 0 if cmp is not None else None


def version_satisfies(version, expression):
    """Evaluate common Maven intervals and Fabric exact/range constraints.

    Returns True/False when understood, None when a syntax cannot be safely
    interpreted. Unknown constraints are reported for manual review, never
    silently declared compatible.
    """
    expression = str(expression or "").strip()
    if not expression or expression in ("*", "any"):
        return True
    # Maven permits unions such as [1.0,1.5),[2.0,)
    parts = re.findall(r"[[(][^])]*[])]|[^,]+", expression)
    if len(parts) > 1 and all(part.strip().startswith(("[", "(")) for part in parts):
        outcomes = [_single_range_matches(version, part) for part in parts]
        if True in outcomes:
            return True
        return None if None in outcomes else False
    return _single_range_matches(version, expression)


def _inspect_archive_bytes(raw, label, depth=0):
    result = {"file": label, "mod_ids": [], "mod_versions": {},
              "dependencies": [], "metadata": [], "warnings": []}
    try:
        import io
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            total = sum(info.file_size for info in infos if not info.is_dir())
            if total > MAX_TOTAL_METADATA * 8:
                result["warnings"].append("Archive has an unusually large uncompressed size.")
            ids, versions, forge_deps = _forge_metadata(archive)
            if ids or forge_deps:
                result["metadata"].append("META-INF/mods.toml")
            result["mod_ids"].extend(ids)
            result["mod_versions"].update(versions)
            result["dependencies"].extend(forge_deps)

            names = set(archive.namelist())
            for metadata_name in ("fabric.mod.json", "quilt.mod.json"):
                if metadata_name in names:
                    ids, versions, deps = _fabric_metadata(archive, metadata_name)
                    result["metadata"].append(metadata_name)
                    result["mod_ids"].extend(ids)
                    result["mod_versions"].update(versions)
                    result["dependencies"].extend(deps)

            ids, versions = _legacy_metadata(archive)
            if ids:
                result["metadata"].append("mcmod.info")
                result["mod_ids"].extend(ids)
                result["mod_versions"].update(versions)

            if depth < MAX_JARJAR_DEPTH:
                metadata = _read_json(archive, "META-INF/jarjar/metadata.json")
                if isinstance(metadata, dict):
                    result["metadata"].append("META-INF/jarjar/metadata.json")
                    for entry in metadata.get("jars", []):
                        if not isinstance(entry, dict):
                            continue
                        path = entry.get("path")
                        if not isinstance(path, str) or not path.startswith("META-INF/jarjar/"):
                            result["warnings"].append("Ignored unsafe Jar-in-Jar path.")
                            continue
                        embedded = _safe_read(archive, path)
                        if embedded is None:
                            result["warnings"].append("Could not read embedded Jar-in-Jar: " + path)
                            continue
                        child = _inspect_archive_bytes(embedded, label + "!" + path, depth + 1)
                        result["mod_ids"].extend(child["mod_ids"])
                        result["mod_versions"].update(child["mod_versions"])
                        result["dependencies"].extend(child["dependencies"])
                        result["metadata"].extend(child["metadata"])
                        result["warnings"].extend(child["warnings"])
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        result["error"] = str(exc)
    result["mod_ids"] = sorted(set(result["mod_ids"]))
    return result


def inspect_jar(path):
    path = Path(path)
    try:
        if path.stat().st_size > 512 * 1024 * 1024:
            return {"file": path.name, "mod_ids": [], "mod_versions": {},
                    "dependencies": [], "metadata": [], "warnings": [],
                    "error": "JAR exceeds 512 MiB inspection limit."}
        return _inspect_archive_bytes(path.read_bytes(), path.name)
    except OSError as exc:
        return {"file": path.name, "mod_ids": [], "mod_versions": {},
                "dependencies": [], "metadata": [], "warnings": [], "error": str(exc)}


def verify_mod_directory(paths, log=lambda message: None, strict=True):
    """Validate IDs, declared version ranges, conflicts, duplicates and archive health."""
    inspections = [inspect_jar(path) for path in paths
                   if str(path).lower().endswith(".jar")]
    known = set(BUILTIN_IDS)
    versions = {}
    owners = {}
    for item in inspections:
        for mod_id in item["mod_ids"]:
            known.add(mod_id)
            owners.setdefault(mod_id, []).append(item["file"])
            if mod_id in item["mod_versions"]:
                versions[mod_id] = item["mod_versions"][mod_id]

    missing, incompatible, conflicts, unverifiable = [], [], [], []
    unreadable, warnings = [], []
    for item in inspections:
        if item.get("error"):
            unreadable.append({"file": item["file"], "error": item["error"]})
            continue
        warnings.extend({"file": item["file"], "warning": warning}
                        for warning in item.get("warnings", []))
        for dep in item["dependencies"]:
            dep_id = dep["id"]
            if dep.get("kind") == "breaks":
                if dep_id in known:
                    installed_version = versions.get(dep_id)
                    match = version_satisfies(installed_version, dep.get("range", "")) if installed_version else True
                    if match is True:
                        conflicts.append({"file": item["file"], "dependency": dep_id,
                                          "range": dep.get("range", "")})
                    elif match is None:
                        unverifiable.append({"file": item["file"], "dependency": dep_id,
                                              "range": dep.get("range", ""), "kind": "conflict"})
                continue
            if dep_id not in known:
                if dep.get("mandatory"):
                    missing.append({"file": item["file"], "dependency": dep_id,
                                    "range": dep.get("range", ""), "source": dep["source"]})
                continue
            required_range = dep.get("range", "")
            installed_version = versions.get(dep_id)
            if required_range and installed_version:
                match = version_satisfies(installed_version, required_range)
                if match is False:
                    incompatible.append({"file": item["file"], "dependency": dep_id,
                                          "required": required_range, "installed": installed_version})
                elif match is None:
                    unverifiable.append({"file": item["file"], "dependency": dep_id,
                                          "range": required_range, "installed": installed_version,
                                          "kind": "requires"})
            elif required_range and not installed_version:
                unverifiable.append({"file": item["file"], "dependency": dep_id,
                                      "range": required_range, "installed": None,
                                      "kind": "requires"})

    duplicates = {key: value for key, value in owners.items() if len(value) > 1}
    report = {
        "checked_jars": len(inspections),
        "discovered_mod_ids": sorted(known - BUILTIN_IDS),
        "mod_versions": versions,
        "missing_required": missing,
        "incompatible_versions": incompatible,
        "conflicts": conflicts,
        "duplicate_mod_ids": duplicates,
        "unverifiable_constraints": unverifiable,
        "unreadable_jars": unreadable,
        "warnings": warnings,
        "metadata_coverage": sum(bool(item["metadata"]) for item in inspections),
        "inspections": inspections,
    }
    log(f"Dependency verifier inspected {len(inspections)} JAR(s); "
        f"read metadata from {report['metadata_coverage']}.")
    failures = []
    if missing:
        failures.append("missing mandatory mod IDs: " + ", ".join(
            f"{e['dependency']} (required by {e['file']})" for e in missing))
    if incompatible:
        failures.append("incompatible dependency versions: " + ", ".join(
            f"{e['dependency']} {e['installed']} does not satisfy {e['required']}"
            for e in incompatible))
    if conflicts:
        failures.append("declared mod conflicts: " + ", ".join(
            f"{e['file']} conflicts with {e['dependency']}" for e in conflicts))
    if duplicates:
        failures.append("duplicate internal mod IDs: " + ", ".join(
            f"{mod_id} in {', '.join(files)}" for mod_id, files in duplicates.items()))
    if unreadable:
        failures.append("unreadable JAR archives: " + ", ".join(
            f"{entry['file']} ({entry['error']})" for entry in unreadable))
    if strict and failures:
        raise RuntimeError("Dependency verification failed: " + "; ".join(failures))
    if duplicates:
        log("WARNING: duplicate internal mod IDs detected: " + ", ".join(duplicates))
    if unreadable:
        log("WARNING: unreadable JARs detected; inspect the verifier report.")
    if unverifiable:
        log(f"WARNING: {len(unverifiable)} dependency version constraint(s) could not be verified.")
    return report
