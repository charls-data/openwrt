"""Check SDK feed pinning through a real recursive GNU make invocation."""
import importlib.util
import io
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("build", ROOT / "scripts/build.py")
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)


@unittest.skipUnless(shutil.which("make"), "Requires GNU make")
class SdkExportTests(unittest.TestCase):
    def test_export_pins_base_feed_without_switching_build_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            tree = Path(temporary)
            sdk = tree / "target/sdk"
            sdk.mkdir(parents=True)
            # Changing build mode midway must fail before export. The upstream
            # equivalent would remove the toolchain when .ver_check is absent.
            (tree / "Makefile").write_text(
                "ifneq ($(CONFIG_BUILDBOT),)\n"
                "$(error Build mode changed during SDK export)\n"
                "endif\n"
                ".PHONY: target/sdk/install\n"
                "target/sdk/install:\n"
                "\t$(MAKE) -C target/sdk install\n"
            )
            # Match upstream's ordinary assignment and MAKEFLAGS reset. Check
            # the generated file, including spaces, rather than command args.
            (sdk / "Makefile").write_text(
                "override MAKEFLAGS=\n"
                "BASE_FEED:=src-git base https://example.org/unpinned.git\n"
                ".PHONY: install\n"
                "install:\n"
                "\t$(file >feeds.conf.default,$(BASE_FEED))\n"
            )
            job = build.Build.__new__(build.Build)
            job.jobs = 2
            job.out = tree / "output"
            job.log = io.StringIO()
            job.lock = {"openwrt": {"url": "https://example.org/openwrt.git", "commit": "a" * 40}}
            job.export_sdk(tree, f"DL_DIR={tree / 'dl'}")
            self.assertEqual(
                (sdk / "feeds.conf.default").read_text(),
                "src-git --root=package base https://example.org/openwrt.git^" + "a" * 40 + "\n",
            )


if __name__ == "__main__":
    unittest.main()
