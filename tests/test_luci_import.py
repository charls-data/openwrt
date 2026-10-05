"""Exercise imported LuCI versions with GNU make's assignment semantics."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("build", ROOT / "scripts/build.py")
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)


class LuCIImportTests(unittest.TestCase):
    def test_unknown_or_multiple_framework_includes_are_rejected(self):
        for text in ["include ../luci.mk\n", "# include ../../luci.mk\n",
                     "include ../../luci.mk\ninclude $(TOPDIR)/feeds/luci/luci.mk\n"]:
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "Unexpected LuCI"):
                build.adapt_luci_makefile(text, "2026.10.05~abcdef012345")

    @unittest.skipUnless(shutil.which("make"), "Requires GNU make")
    def test_official_framework_gets_versions_for_both_include_styles(self):
        version = "2026.10.05~abcdef012345"
        with tempfile.TemporaryDirectory() as temporary:
            tree = Path(temporary)
            (tree / "rules.mk").write_text("")
            framework = tree / "feeds/luci/luci.mk"
            framework.parent.mkdir(parents=True)
            # Match luci.mk's package-version choice and read the translation
            # version separately. This catches assignments in the wrong order.
            framework.write_text(
                "VERSION:=$(if $(PKG_VERSION),$(PKG_VERSION)-r$(PKG_RELEASE),$(PKG_SRC_VERSION))\n"
                "$(file >versions.txt,$(VERSION) $(PKG_PO_VERSION))\n"
                "all:;\n"
            )
            for include in ["../../luci.mk", "$(TOPDIR)/feeds/luci/luci.mk"]:
                for explicit in [False, True]:
                    with self.subTest(include=include, explicit=explicit):
                        text = "include $(TOPDIR)/rules.mk\n"
                        if explicit:
                            text += "PKG_VERSION:=1.0.1\nPKG_RELEASE:=3\n"
                        text += f"include {include}\n"
                        (tree / "Makefile").write_text(build.adapt_luci_makefile(text, version))
                        subprocess.run(["make", f"TOPDIR={tree}"], cwd=tree, check=True,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                        expected = "1.0.1-r3" if explicit else f"{version}-r1"
                        self.assertEqual((tree / "versions.txt").read_text(), f"{expected} {version}\n")


if __name__ == "__main__":
    unittest.main()
