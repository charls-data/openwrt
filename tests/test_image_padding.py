"""Exercise the patched Make recipe with aligned and unaligned sparse images."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "patches/imagebuilder/001-pad-with-truncate.patch"
# Minimal upstream context; git apply checks the same hunk against the complete
# pinned ImageBuilder source before every firmware build.
UPSTREAM = """# @param 2: Padding.
##
define Image/pad-to
\tdd if=$(1) of=$(1).new bs=$(2) conv=sync
\tmv $(1).new $(1)
endef

ifeq ($(DUMP),)
endif
"""


@unittest.skipUnless(sys.platform == "linux" and all(shutil.which(tool) for tool in ["git", "make", "truncate"]),
                     "Requires Linux sparse files and GNU build tools")
class ImagePaddingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        include = self.root / "include"
        include.mkdir()
        (include / "image.mk").write_text(UPSTREAM)
        subprocess.run(["git", "apply", str(PATCH)], cwd=self.root, check=True, capture_output=True)
        (self.root / "Makefile").write_text("include include/image.mk\nall:\n\t$(call Image/pad-to,image.bin,$(ALIGN))\n")
        self.image = self.root / "image.bin"

    def pad(self, size):
        subprocess.run(["make", "--no-print-directory", "all", f"ALIGN={size}"], cwd=self.root,
                       check=True, capture_output=True)

    def test_unaligned_image_keeps_data_and_zero_pads(self):
        for original_size, expected_size in [(0, 0), (13, 16), (16, 16), (17, 32)]:
            with self.subTest(original_size=original_size):
                original = bytes(range(original_size))
                self.image.write_bytes(original)
                self.pad(16)
                self.assertEqual(self.image.read_bytes(), original + bytes(expected_size - original_size))

    def test_eight_gib_image_keeps_size_and_data_beyond_read_limit(self):
        size = 8 * 1024**3
        offsets = [0, 2 * 1024**3 + 4096, size - 4]
        with self.image.open("wb") as stream:
            stream.truncate(size)
            for offset in offsets:
                stream.seek(offset)
                stream.write(b"DATA")
        self.pad(size)
        self.assertEqual(self.image.stat().st_size, size)
        with self.image.open("rb") as stream:
            for offset in offsets:
                stream.seek(offset)
                self.assertEqual(stream.read(4), b"DATA")
        self.assertLess(self.image.stat().st_blocks * 512, 1024**2)
        self.assertFalse((self.root / "image.bin.new").exists())


if __name__ == "__main__":
    unittest.main()
