import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from app.dependency_verifier import inspect_jar, verify_mod_directory, version_satisfies
from app.llm import LLMClient


def make_jar(path, files):
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return path


def forge_toml(mod_id, deps=""):
    return (
        'modLoader="javafml"\nloaderVersion="[1,)"\nlicense="MIT"\n'
        f'[[mods]]\nmodId="{mod_id}"\nversion="1.0.0"\n{deps}'
    )


class VersionRangeTests(unittest.TestCase):
    def test_fabric_space_separated_comparators_are_anded(self):
        self.assertTrue(version_satisfies("1.20.1", ">=1.20 <1.21"))
        self.assertFalse(version_satisfies("1.21.1", ">=1.20 <1.21"))
        self.assertFalse(version_satisfies("1.19.4", ">=1.20 <1.21"))

    def test_or_ranges(self):
        self.assertTrue(version_satisfies("1.19.2", ">=1.20 || 1.19.2"))
        self.assertFalse(version_satisfies("1.18", ">=1.20 || 1.19.2"))

    def test_operator_may_be_followed_by_space(self):
        self.assertTrue(version_satisfies("2.0", ">= 1.5"))

    def test_maven_intervals_still_work(self):
        self.assertTrue(version_satisfies("1.20.1", "[1.20.1,1.21)"))
        self.assertFalse(version_satisfies("1.21", "[1.20.1,1.21)"))
        self.assertTrue(version_satisfies("47.2.0", "[47,)"))


class VerifierRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_shared_jarjar_library_is_not_a_duplicate(self):
        lib = io.BytesIO()
        with zipfile.ZipFile(lib, "w") as archive:
            archive.writestr("META-INF/mods.toml", forge_toml("sharedlib"))
        metadata = json.dumps({"jars": [{"path": "META-INF/jarjar/sharedlib.jar"}]})
        jars = []
        for name in ("modx", "mody"):
            jars.append(make_jar(self.tmp / f"{name}.jar", {
                "META-INF/mods.toml": forge_toml(name),
                "META-INF/jarjar/metadata.json": metadata,
                "META-INF/jarjar/sharedlib.jar": lib.getvalue(),
            }))
        report = verify_mod_directory(jars)
        self.assertEqual(report["duplicate_mod_ids"], {})
        self.assertIn("sharedlib", report["discovered_mod_ids"])

    def test_bundled_library_satisfies_dependency(self):
        lib = io.BytesIO()
        with zipfile.ZipFile(lib, "w") as archive:
            archive.writestr("META-INF/mods.toml", forge_toml("bundled"))
        host = make_jar(self.tmp / "host.jar", {
            "META-INF/mods.toml": forge_toml("host"),
            "META-INF/jarjar/metadata.json": json.dumps({"jars": [{"path": "META-INF/jarjar/b.jar"}]}),
            "META-INF/jarjar/b.jar": lib.getvalue(),
        })
        user = make_jar(self.tmp / "user.jar", {"META-INF/mods.toml": forge_toml(
            "user", '[[dependencies.user]]\nmodId="bundled"\nmandatory=true\nversionRange="[1,)"\nside="BOTH"\n')})
        verify_mod_directory([host, user])  # must not raise

    def test_real_duplicate_is_still_reported(self):
        a = make_jar(self.tmp / "a.jar", {"META-INF/mods.toml": forge_toml("same")})
        b = make_jar(self.tmp / "b.jar", {"META-INF/mods.toml": forge_toml("same")})
        with self.assertRaises(RuntimeError):
            verify_mod_directory([a, b])

    def test_neoforge_mods_toml_name_is_read(self):
        jar = make_jar(self.tmp / "neo.jar", {"META-INF/neoforge.mods.toml": forge_toml("neomod")})
        self.assertEqual(inspect_jar(jar)["mod_ids"], ["neomod"])

    def test_neoforge_optional_type_is_not_mandatory(self):
        deps = ('[[dependencies.neomod]]\nmodId="optionalthing"\ntype="optional"\n'
                'versionRange="[1,)"\nside="BOTH"\n')
        jar = make_jar(self.tmp / "neo.jar", {"META-INF/neoforge.mods.toml": forge_toml("neomod", deps)})
        verify_mod_directory([jar])  # must not raise

    def test_neoforge_required_type_is_mandatory(self):
        deps = ('[[dependencies.neomod]]\nmodId="needed"\ntype="required"\n'
                'versionRange="[1,)"\nside="BOTH"\n')
        jar = make_jar(self.tmp / "neo.jar", {"META-INF/neoforge.mods.toml": forge_toml("neomod", deps)})
        with self.assertRaises(RuntimeError):
            verify_mod_directory([jar])

    def test_neoforge_incompatible_type_is_a_conflict(self):
        deps = ('[[dependencies.neomod]]\nmodId="other"\ntype="incompatible"\n'
                'versionRange="[1,)"\nside="BOTH"\n')
        a = make_jar(self.tmp / "neo.jar", {"META-INF/neoforge.mods.toml": forge_toml("neomod", deps)})
        b = make_jar(self.tmp / "other.jar", {"META-INF/neoforge.mods.toml": forge_toml("other")})
        with self.assertRaises(RuntimeError):
            verify_mod_directory([a, b])

    def test_fabric_depends_array_means_alternatives(self):
        mod = make_jar(self.tmp / "fabmod.jar", {"fabric.mod.json": json.dumps({
            "schemaVersion": 1, "id": "fabmod", "version": "1.0.0",
            "depends": {"fabric-api": ["<0.5", ">=0.90"]}})})
        api = make_jar(self.tmp / "fapi.jar", {"fabric.mod.json": json.dumps({
            "schemaVersion": 1, "id": "fabric-api", "version": "0.100.0"})})
        verify_mod_directory([mod, api])  # must not raise

    def test_platform_version_mismatch_is_caught(self):
        deps = ('[[dependencies.m]]\nmodId="minecraft"\nmandatory=true\n'
                'versionRange="[1.20.1,1.21)"\nside="BOTH"\n')
        jar = make_jar(self.tmp / "m.jar", {"META-INF/mods.toml": forge_toml("m", deps)})
        verify_mod_directory([jar], platform_versions={"minecraft": "1.20.1"})  # ok
        with self.assertRaises(RuntimeError) as ctx:
            verify_mod_directory([jar], platform_versions={"minecraft": "1.21.1"})
        self.assertIn("minecraft", str(ctx.exception))

    def test_builtin_ranges_are_not_reported_as_unverifiable_noise(self):
        deps = ('[[dependencies.m]]\nmodId="minecraft"\nmandatory=true\n'
                'versionRange="[1.20.1,1.21)"\nside="BOTH"\n')
        jar = make_jar(self.tmp / "m.jar", {"META-INF/mods.toml": forge_toml("m", deps)})
        report = verify_mod_directory([jar])
        self.assertEqual(report["unverifiable_constraints"], [])


class PipelineRegressionTests(unittest.TestCase):
    def make_pipeline(self, components):
        from app.orchestrator import ModpackPipeline
        tmp = Path(tempfile.mkdtemp())
        instance = tmp / "instance"
        (instance / "minecraft").mkdir(parents=True)
        (instance / "mmc-pack.json").write_text(json.dumps({"components": components}), encoding="utf-8")
        env = {"XDG_DATA_HOME": str(tmp / "data")}
        with mock.patch.dict(os.environ, env):
            return ModpackPipeline(
                {"provider": "Ollama", "model": "m", "instance": str(instance), "catalog": "Modrinth"},
                log=lambda message: None,
            )

    def test_platform_versions_are_read_from_prism_metadata(self):
        pipeline = self.make_pipeline([
            {"uid": "net.minecraft", "version": "1.20.1"},
            {"uid": "net.minecraftforge", "version": "47.2.0"},
        ])
        self.assertEqual(pipeline.prism_platform_versions(), {"minecraft": "1.20.1", "forge": "47.2.0"})

    def test_loader_mismatch_is_rejected_before_any_download(self):
        pipeline = self.make_pipeline([
            {"uid": "net.minecraft", "version": "1.20.1"},
            {"uid": "net.fabricmc.fabric-loader", "version": "0.15.11"},
        ])
        platform = pipeline.prism_platform_versions()
        pipeline.check_instance_loader("fabric", platform)  # ok
        with self.assertRaises(ValueError):
            pipeline.check_instance_loader("forge", platform)

    def test_vanilla_instance_is_rejected_for_modded_pack(self):
        pipeline = self.make_pipeline([{"uid": "net.minecraft", "version": "1.20.1"}])
        with self.assertRaises(ValueError):
            pipeline.check_instance_loader("neoforge", pipeline.prism_platform_versions())

    def test_fabric_pack_is_allowed_on_quilt_instance(self):
        pipeline = self.make_pipeline([
            {"uid": "net.minecraft", "version": "1.20.1"},
            {"uid": "org.quiltmc.quilt-loader", "version": "0.26.0"},
        ])
        pipeline.check_instance_loader("fabric", pipeline.prism_platform_versions())

    def test_prompts_contain_real_newlines_not_escaped_ones(self):
        source = Path(__file__).resolve().parents[1].joinpath("app", "orchestrator.py").read_text(encoding="utf-8")
        self.assertNotIn("\\\\n", source)


class OllamaOptionsTests(unittest.TestCase):
    def test_ollama_request_sets_context_window(self):
        client = LLMClient("Ollama", "", "qwen2.5:3b", lambda message: None, num_ctx=6000)
        response = mock.Mock(ok=True)
        response.json.return_value = {"message": {"content": "{}"}}
        with mock.patch.object(client.session, "post", return_value=response) as post:
            client.text("system", "user")
        options = post.call_args.kwargs["json"]["options"]
        self.assertEqual(options["num_ctx"], 6000)
        self.assertLessEqual(options["temperature"], 0.3)

    def test_default_context_is_larger_than_ollama_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MODPACK_AI_NUM_CTX", None)
            self.assertGreaterEqual(LLMClient("Ollama", "", "m", lambda message: None).num_ctx, 8192)


if __name__ == "__main__":
    unittest.main()
