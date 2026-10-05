import copy
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("build", ROOT / "scripts/build.py")
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)
LOCK_SPEC = importlib.util.spec_from_file_location("update_lock", ROOT / "scripts/update-lock.py")
update_lock = importlib.util.module_from_spec(LOCK_SPEC)
with mock.patch.dict(sys.modules, {"build": build}):
    LOCK_SPEC.loader.exec_module(update_lock)


class ConfigurationTests(unittest.TestCase):
    def test_current_configuration(self):
        cfg, third, lock = build.load_config()
        self.assertEqual(lock["release"], cfg["openwrt"]["release"])

    def test_default_selection_excludes_disabled_groups(self):
        third = {"builds": [{"name": "a", "enabled": True}, {"name": "b", "enabled": False}]}
        self.assertEqual([g["name"] for g in build.select_groups(third, "")], ["a"])

    def test_explicit_selection_of_disabled_group(self):
        third = {"builds": [{"name": "a", "enabled": False}]}
        with self.assertRaises(ValueError):
            build.select_groups(third, "")
        self.assertEqual(build.select_groups(third, "a")[0]["name"], "a")

    def test_invalid_targets_fail_before_build(self):
        third = {"builds": [{"name": "msd-lite", "enabled": True}]}
        for value in ["missing", "msd-lite,", "msd-lite,msd-lite", "msd-lite; echo unsafe", "$(echo unsafe)"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                build.select_groups(third, value)

    def test_paths_cannot_escape_repository(self):
        for value in ["../private", "/etc/passwd", "foo/../../bar", "C:\\outside"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                build.repo_path(value)

    def test_kconfig_updates_preserve_unrelated_options(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ".config"
            path.write_text('CONFIG_ALL=y\n# CONFIG_PACKAGE_gfortran is not set\nCONFIG_OTHER="kept"\nCONFIG_PACKAGE_libquadmath=y\n')
            build.set_config(path, {"CONFIG_ALL": "n", "CONFIG_PACKAGE_gfortran": "m", "CONFIG_PACKAGE_libquadmath": "m"})
            result = build.fragment_values(path)
            self.assertEqual(result, {"CONFIG_ALL": "n", "CONFIG_PACKAGE_gfortran": "m", "CONFIG_OTHER": '"kept"', "CONFIG_PACKAGE_libquadmath": "m"})
            self.assertEqual(path.read_text().count("CONFIG_PACKAGE_libquadmath"), 1)

    def test_package_list_comments_removals_and_crlf(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "packages.txt"
            path.write_bytes(b"\xef\xbb\xbf# example\r\nluci # UI\r\n-ppp\r\n\r\n")
            self.assertEqual(build.package_list(path), ["luci", "-ppp"])
            path.write_text("luci\nluci\n")
            with self.assertRaises(ValueError):
                build.package_list(path)


class PluginFileTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        patcher = mock.patch.object(build, "ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def plugin(self, filename, name, url="https://example.org/recipes.git", ref="master"):
        path = self.root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'''schema_version = 1
name = "{name}"
enabled = true
[[sources]]
name = "shared"
url = "{url}"
ref = "{ref}"
[[recipes]]
source = "shared"
path = "net/{name}"
select = ["{name}"]
expected_apk_names = ["{name}"]
''', encoding="utf-8")

    def load(self, *files):
        return build.load_third_party({"third_party": {"config_files": list(files)}})

    def test_multiple_files_keep_order_and_share_source(self):
        self.plugin("config/plugins/a.toml", "a")
        self.plugin("config/plugins/b.toml", "b")
        result = self.load("config/plugins/b.toml", "config/plugins/a.toml")
        self.assertEqual([group["name"] for group in result["builds"]], ["b", "a"])
        self.assertEqual(result["builds"][0]["config_file"], "config/plugins/b.toml")
        self.assertEqual(len(result["sources"]), 1)
        self.assertEqual([group["name"] for group in build.select_groups(result, "a")], ["a"])

    def test_unlisted_file_is_not_loaded(self):
        self.plugin("a.toml", "a")
        (self.root / "unlisted.toml").write_text("invalid TOML = [")
        result = self.load("a.toml")
        self.assertEqual([group["name"] for group in result["builds"]], ["a"])
        self.assertEqual((self.root / "unlisted.toml").read_text(), "invalid TOML = [")

    def test_conflicting_shared_source_url_or_ref_is_rejected(self):
        self.plugin("a.toml", "a")
        for url, ref in [("https://example.org/other.git", "master"), ("https://example.org/recipes.git", "stable")]:
            self.plugin("b.toml", "b", url=url, ref=ref)
            with self.subTest(url=url, ref=ref), self.assertRaisesRegex(ValueError, "Conflicting source"):
                self.load("a.toml", "b.toml")

    def test_duplicate_file_or_plugin_name_is_rejected(self):
        self.plugin("a.toml", "same")
        self.plugin("b.toml", "same")
        with self.assertRaisesRegex(ValueError, "Duplicate plugin config file"):
            self.load("a.toml", "./a.toml")
        with self.assertRaisesRegex(ValueError, "Duplicate names"):
            self.load("a.toml", "b.toml")

    def test_missing_or_escaping_file_is_rejected(self):
        for filename in ["missing.toml", "../outside.toml"]:
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                self.load(filename)

    def test_recipe_source_must_be_declared_in_its_own_file(self):
        self.plugin("a.toml", "a")
        path = self.root / "a.toml"
        path.write_text(path.read_text().replace('source = "shared"', 'source = "undeclared"'))
        with self.assertRaisesRegex(ValueError, "Declare source"):
            self.load("a.toml")

    def test_empty_file_list_can_disable_third_party_work(self):
        result = self.load()
        self.assertEqual(result, {"sources": [], "builds": []})
        with self.assertRaisesRegex(ValueError, "No enabled"):
            build.select_groups(result, "")

    def test_host_tools_do_not_require_target_packages(self):
        self.plugin("tools.toml", "tools")
        path = self.root / "tools.toml"
        text = path.read_text().replace('select = ["tools"]', 'host_only = true\nselect = []')
        text = text.replace('expected_apk_names = ["tools"]', 'expected_apk_names = []')
        path.write_text(text)
        recipe = self.load("tools.toml")["builds"][0]["recipes"][0]
        self.assertTrue(recipe["host_only"])
        self.assertEqual(recipe["expected_apk_names"], [])
        for changed in [text.replace('host_only = true', 'host_only = false'),
                        text.replace('select = []', 'select = ["tools"]'),
                        text.replace('expected_apk_names = []', 'expected_apk_names = ["tools"]'),
                        text.replace('host_only = true', 'host_only = true\nluci = true'),
                        text.replace('host_only = true', 'host_only = "true"')]:
            with self.subTest(config=changed), self.assertRaises(ValueError):
                path.write_text(changed)
                self.load("tools.toml")


class SharedRecipeTests(unittest.TestCase):
    def test_shared_recipe_merges_outputs_without_changing_inputs(self):
        groups = [
            {"recipes": [{"source": "shared", "path": "applications/luci-app-example", "luci": True,
                          "select": ["luci-app-example"], "expected_apk_names": ["luci-app-example"]}]},
            {"recipes": [{"source": "shared", "path": "applications/luci-app-example", "luci": True,
                          "languages": ["zh_Hans"], "select": ["luci-i18n-example-zh-cn"],
                          "expected_apk_names": ["luci-i18n-example-zh-cn"]}]},
        ]
        original = copy.deepcopy(groups)
        result = build.merge_recipes(groups)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["select"], ["luci-app-example", "luci-i18n-example-zh-cn"])
        self.assertEqual(result[0]["expected_apk_names"], result[0]["select"])
        self.assertEqual(result[0]["languages"], ["zh_Hans"])
        self.assertEqual(groups, original)

    def test_same_directory_from_different_sources_is_rejected(self):
        groups = [{"recipes": [{"source": source, "path": "net/example", "select": ["example"],
                                "expected_apk_names": ["example"]}]} for source in ["a", "b"]]
        with self.assertRaisesRegex(ValueError, "Conflicting recipe directory"):
            build.merge_recipes(groups)

    def test_shared_recipe_with_conflicting_luci_setting_is_rejected(self):
        groups = [{"recipes": [{"source": "a", "path": "net/example", "luci": luci,
                                "select": ["example"], "expected_apk_names": ["example"]}]} for luci in [False, True]]
        with self.assertRaisesRegex(ValueError, "Conflicting luci setting"):
            build.merge_recipes(groups)

    def test_shared_recipe_cannot_mix_host_and_target_builds(self):
        groups = [{"recipes": [{"source": "a", "path": "qt6tools", "host_only": host,
                                "select": [], "expected_apk_names": []}]} for host in [False, True]]
        with self.assertRaisesRegex(ValueError, "Conflicting host_only setting"):
            build.merge_recipes(groups)


class PluginLockTests(unittest.TestCase):
    def test_update_preserves_unlisted_source_pins(self):
        old = {name: {"url": f"https://example.org/{name}.git", "commit": "a" * 40} for name in ["active", "inactive"]}
        original = copy.deepcopy(old)
        sources = [{"name": "active", "url": "https://example.org/active.git", "ref": "master"}]
        with mock.patch.object(update_lock, "resolve", return_value="b" * 40) as resolve:
            result = update_lock.refresh_third_party(old, sources)
            resolve.assert_called_once_with("https://example.org/active.git", "master")
        self.assertEqual(result["active"]["commit"], "b" * 40)
        self.assertEqual(result["inactive"], original["inactive"])
        self.assertEqual(old, original)


if __name__ == "__main__":
    unittest.main()

