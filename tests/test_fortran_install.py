"""Exercise real install commands against a small synthetic GCC install tree."""
from pathlib import Path
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("build", ROOT / "scripts/build.py")
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)
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
        # musl's pthread implementation lives in libc; this is the real format
        # of its empty link-time compatibility archive.
        (self.tc / "lib/libpthread.a").write_bytes(b"!<arch>\n")

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

    def test_development_links_use_linkable_copies_not_runtime_dsos(self):
        dest = self.install("dev")
        for name in ["libgomp", "libgfortran", "libquadmath"]:
            self.assertEqual((dest / f"usr/lib/{name}.so").readlink().as_posix(),
                             f"gcc/{TRIPLE}/{VERSION}/{name}.so")
        for name in ["libgomp", "libgfortran"]:
            path = dest / self.gccdir / f"{name}.so"
            self.assertFalse(path.is_symlink())
            build.linkable_elf(path)
        # Official gcc supplies this file; the add-on must not own it as well.
        self.assertFalse((dest / self.gccdir / "libquadmath.so").exists())
        self.assertTrue((dest / self.gccdir / "include/omp.h").is_file())
        self.assertTrue((dest / "usr/lib/libcaf_single.a").is_file())
        self.assertEqual((dest / self.gccdir / "libpthread.a").read_bytes(), b"!<arch>\n")

    def test_missing_pthread_compatibility_archive_is_fatal(self):
        (self.tc / "lib/libpthread.a").unlink()
        self.install("dev", success=False)

    def test_linking_works_when_runtime_has_no_section_table(self):
        dest = self.install("dev")
        source = self.root / "probe.c"
        source.write_text("extern int placeholder; int main(void) { return placeholder; }\n")
        for name, soname in [("libgfortran", "libgfortran.so.5"), ("libgomp", "libgomp.so.1")]:
            with self.subTest(library=name):
                # Reproduce sstrip's removed ELF64 section-header fields. The
                # program headers and dynamic loader data remain untouched.
                runtime = self.root / f"runtime-{name}.so"
                data = bytearray((self.tc / "lib" / soname).read_bytes())
                data[40:48] = bytes(8)
                data[58:64] = bytes(6)
                runtime.write_bytes(data)
                with self.assertRaisesRegex(ValueError, "Missing ELF section table"):
                    build.linkable_elf(runtime)
                broken = subprocess.run(["cc", str(source), str(runtime), "-o", str(self.root / "bad")],
                                        capture_output=True, text=True)
                self.assertNotEqual(broken.returncode, 0)
                linked = subprocess.run(["cc", str(source), f"-L{dest / 'usr/lib'}", f"-l{name[3:]}",
                                         "-o", str(self.root / "good")], capture_output=True, text=True)
                self.assertEqual(linked.returncode, 0, linked.stderr)

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

