"""Exercise real install commands against a small synthetic GCC install tree."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TRIPLE = "x86_64-openwrt-linux-musl"
VERSION = "14.3.0"


@unittest.skipUnless(sys.platform == "linux" and shutil.which("cc"), "Requires Linux tools and symlinks")
class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.native = self.root / "native"
        self.tc = self.root / "toolchain"
        self.gccdir = Path(f"usr/lib/gcc/{TRIPLE}/{VERSION}")
        for name in ["omp.h", "openacc.h", "quadmath.h", "quadmath_weak.h", "ISO_Fortran_binding.h"]:
            self.put(self.native / self.gccdir / "include" / name)
        for name in ["libgomp.spec", "libgfortran.spec", "f951"]:
            self.put(self.native / self.gccdir / name)
        for name in ["libgomp.a", "libquadmath.a", "libgfortran.a", "libcaf_single.a"]:
            self.put(self.native / "usr/lib" / name)
        self.put(self.native / "usr/bin" / f"{TRIPLE}-gfortran")
        self.modules = self.tc / f"lib/gcc/{TRIPLE}/{VERSION}/finclude"
        for name in ["ieee_arithmetic.mod", "ieee_exceptions.mod", "ieee_features.mod", "omp_lib.f90", "omp_lib.h", "omp_lib.mod", "omp_lib_kinds.mod", "openacc.f90", "openacc.mod", "openacc_kinds.mod", "openacc_lib.h"]:
            self.put(self.modules / name, "module from cross toolchain\n")
        for name, soname in [("libgomp", "libgomp.so.1"), ("libquadmath", "libquadmath.so.0"), ("libgfortran", "libgfortran.so.5")]:
            path = self.tc / "lib" / soname
            path.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["cc", "-x", "c", "-shared", f"-Wl,-soname,{soname}", "-o", str(path), "-"], input="int placeholder;\n", text=True, check=True)
            (self.tc / "lib" / f"{name}.so").symlink_to(soname)

    @staticmethod
    def put(path, content="placeholder\n"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def install(self, mode, success=True):
        dest = self.root / mode
        result = subprocess.run(["bash", str(ROOT / "scripts/install-fortran-files.sh"), mode, str(dest), str(self.native), str(self.tc), TRIPLE, VERSION], capture_output=True, text=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return dest

    def test_runtime_links_follow_elf_sonames(self):
        dest = self.install("dev")
        self.assertEqual((dest / "usr/lib/libquadmath.so").readlink().as_posix(), "../../lib/libquadmath.so.0")
        self.assertEqual((dest / "usr/lib/libgfortran.so").readlink().as_posix(), "libgfortran.so.5")
        self.assertTrue((dest / self.gccdir / "include/omp.h").is_file())
        self.assertTrue((dest / "usr/lib/libcaf_single.a").is_file())

    def test_compiler_contains_toolchain_fortran_modules(self):
        dest = self.install("compiler")
        self.assertEqual((dest / self.gccdir / "finclude/omp_lib.mod").read_text(), "module from cross toolchain\n")
        self.assertEqual((dest / "usr/bin/gfortran").readlink().as_posix(), f"{TRIPLE}-gfortran")
        self.assertTrue((dest / self.gccdir / "f951").is_file())

    def test_missing_omp_module_is_fatal(self):
        (self.modules / "omp_lib.mod").unlink()
        self.install("compiler", success=False)

    def test_ambiguous_native_file_is_fatal(self):
        self.put(self.native / "usr/other/omp.h")
        self.install("dev", success=False)


if __name__ == "__main__":
    unittest.main()

