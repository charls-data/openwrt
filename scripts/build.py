#!/usr/bin/env python3
"""Build entry point shared by local Linux builds and GitHub Actions (Python 3.11+)."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]*\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")
HASH = re.compile(r"[0-9a-f]{64}\Z")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def keys(value, allowed, label):
    require(isinstance(value, dict), f"{label} must be a table")
    require(not (value.keys() - set(allowed)), f"Unknown keys in {label}: {value.keys() - set(allowed)}")


def repo_path(value):
    require(isinstance(value, str) and value and "\\" not in value, f"Invalid relative path: {value!r}")
    path = PurePosixPath(value)
    require(not path.is_absolute() and ".." not in path.parts, f"Path must stay inside repository: {value}")
    result = (ROOT / value).resolve()
    require(result.is_relative_to(ROOT), f"Path escapes repository: {value}")
    return result


def names(values, label):
    require(isinstance(values, list) and values, f"{label} must be a nonempty list")
    require(all(isinstance(v, str) and TOKEN.fullmatch(v) for v in values), f"Invalid name in {label}")
    require(len(set(values)) == len(values), f"Duplicate names in {label}")


def package_list(path):
    result = []
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        name = line.split("#", 1)[0].strip()
        if not name:
            continue
        require(TOKEN.fullmatch(name.removeprefix("-")), f"Invalid package at {path}:{number}")
        require(name not in result, f"Duplicate package: {name}")
        result.append(name)
    require(result, "Firmware package list is empty")
    return result


def load_third_party(cfg):
    """Load only listed plugin files; also used before refreshing source locks."""
    keys(cfg["third_party"], ["config_files"], "third_party")
    files = cfg["third_party"]["config_files"]
    require(isinstance(files, list), "third_party.config_files must be a list")
    paths, sources, groups = set(), {}, []
    for filename in files:
        path = repo_path(filename)
        require(path.suffix == ".toml" and path.is_file(), f"Missing plugin TOML: {filename}")
        require(path not in paths, f"Duplicate plugin config file: {filename}")
        paths.add(path)
        plugin = tomllib.loads(path.read_text(encoding="utf-8"))
        keys(plugin, ["schema_version", "name", "enabled", "sources", "recipes"], filename)
        require(plugin["schema_version"] == 1, f"Unsupported schema version in {filename}")
        names([plugin["name"]], f"plugin name in {filename}")
        require(type(plugin["enabled"]) is bool, f"enabled must be boolean in {filename}")
        require(isinstance(plugin["sources"], list) and plugin["sources"], f"Missing sources in {filename}")
        require(isinstance(plugin["recipes"], list) and plugin["recipes"], f"Missing recipes in {filename}")
        local_sources = set()
        for source in plugin["sources"]:
            keys(source, ["name", "url", "ref"], f"source in {filename}")
            names([source["name"]], "source name")
            require(source["name"] not in local_sources, f"Duplicate source {source['name']} in {filename}")
            require(isinstance(source["url"], str) and source["url"].startswith("https://") and
                    isinstance(source["ref"], str) and source["ref"], "Sources require an HTTPS URL and update ref")
            local_sources.add(source["name"])
            previous = sources.get(source["name"])
            require(previous is None or previous == source, f"Conflicting source {source['name']} in {filename}: URL and ref must match across plugin files")
            sources[source["name"]] = source
        for recipe in plugin["recipes"]:
            keys(recipe, ["source", "path", "luci", "languages", "select", "expected_apk_names"], f"recipe in {filename}")
            require(recipe["source"] in local_sources, f"Declare source {recipe['source']} in {filename}")
            repo_path(recipe["path"])
            require(TOKEN.fullmatch(PurePosixPath(recipe["path"]).name), "Invalid recipe directory")
            require(type(recipe.get("luci", False)) is bool, "luci must be boolean")
            if "languages" in recipe:
                require(recipe.get("luci"), "languages requires luci = true")
                names(recipe["languages"], "LuCI languages")
            names(recipe["select"], "recipe select")
            names(recipe["expected_apk_names"], "recipe APK names")
        groups.append({"name": plugin["name"], "enabled": plugin["enabled"],
                       "recipes": plugin["recipes"], "config_file": path.relative_to(ROOT).as_posix()})
    if groups:
        names([group["name"] for group in groups], "plugin names")
    return {"sources": list(sources.values()), "builds": groups}


def load_config():
    cfg = tomllib.loads((ROOT / "config/build.toml").read_text(encoding="utf-8"))
    third = load_third_party(cfg)
    lock = json.loads((ROOT / "config/sources.lock.json").read_text(encoding="utf-8"))
    keys(cfg, ["schema_version", "openwrt", "firmware", "fortran", "third_party"], "build.toml")
    keys(cfg["openwrt"], ["release", "target", "subtarget", "profile", "architecture"], "openwrt")
    keys(cfg["firmware"], ["packages_file", "files_dir", "rootfs_partsize_mib", "boot_partsize_mib", "filesystem", "image_type", "compression", "extra_image_name", "disabled_services"], "firmware")
    keys(cfg["fortran"], ["sdk_config", "packages_config", "required_apk_names"], "fortran")
    require(cfg["schema_version"] == lock["schema_version"] == 1, "Unsupported schema version")
    platform = cfg["openwrt"]
    require(re.fullmatch(r"\d+\.\d+\.\d+", platform["release"]), "A stable OpenWrt release is required")
    require((platform["target"], platform["subtarget"], platform["profile"], platform["architecture"]) == ("x86", "64", "generic", "x86_64"), "This project currently supports x86/64 generic only")
    require(lock["release"] == platform["release"] and lock["target"] == "x86/64", "Version changed: refresh config/sources.lock.json before building")
    firmware = cfg["firmware"]
    require((firmware["filesystem"], firmware["image_type"], firmware["compression"]) == ("ext4", "combined-efi", "gzip"), "Currently supported image: ext4 combined-efi img.gz")
    for key in ["rootfs_partsize_mib", "boot_partsize_mib"]:
        require(type(firmware[key]) is int and 16 <= firmware[key] <= 32768, f"Invalid {key}")
    require(TOKEN.fullmatch(firmware["extra_image_name"]), "Invalid extra_image_name")
    require(isinstance(firmware["disabled_services"], list), "disabled_services must be a list")
    for service in firmware["disabled_services"]:
        require(isinstance(service, str) and TOKEN.fullmatch(service), "Invalid service name")
    package_list(repo_path(firmware["packages_file"]))
    require(repo_path(firmware["files_dir"]).is_dir(), "Missing files_dir")
    for key in ["sdk_config", "packages_config"]:
        require(repo_path(cfg["fortran"][key]).is_file(), f"Missing {key}")
    names(cfg["fortran"]["required_apk_names"], "Fortran APK names")
    require(set(cfg["fortran"]["required_apk_names"]) == {"libgomp", "libquadmath1", "libgfortran", "gcc-fortran-dev", "gfortran"}, "Fortran must export exactly the five documented packages")
    for source in third["sources"]:
        pinned = lock["third_party"].get(source["name"], {})
        require(pinned.get("url") == source["url"] and SHA.fullmatch(pinned.get("commit", "")), f"Refresh lock for source {source['name']}")
    for item in [lock["openwrt"], *lock["feeds"], *lock["third_party"].values()]:
        require(item["url"].startswith("https://") and SHA.fullmatch(item["commit"]), "All Git sources must be locked to a full commit")
    names([feed["name"] for feed in lock["feeds"]], "official feed names")
    for kind in ["imagebuilder", "sdk"]:
        item = lock["downloads"][kind]
        require(item["url"].startswith(f"https://downloads.openwrt.org/releases/{platform['release']}/targets/x86/64/"), "Download URL does not match release/target")
        require(HASH.fullmatch(item["sha256"]), "Invalid download SHA256")
    return cfg, third, lock


def select_groups(third, targets):
    available = {group["name"]: group for group in third["builds"]}
    if targets:
        requested = [part.strip() for part in targets.split(",")]
        require(all(requested), "targets must be comma-separated group names")
        require(len(set(requested)) == len(requested), "Duplicate target")
        require(set(requested) <= available.keys(), f"Unknown targets: {set(requested) - available.keys()}")
        return [available[name] for name in requested]
    result = [group for group in third["builds"] if group["enabled"]]
    require(result, "No enabled third-party build groups")
    return result


def merge_recipes(groups):
    """Compile shared recipes once while retaining every selected output."""
    recipes, directories = {}, {}
    for group in groups:
        for recipe in group["recipes"]:
            key = (recipe["source"], recipe["path"])
            directory = PurePosixPath(recipe["path"]).name
            require(directory not in directories or directories[directory] == key,
                    f"Conflicting recipe directory in selected plugins: {directory}")
            directories[directory] = key
            previous = recipes.get(key)
            require(previous is None or previous.get("luci", False) == recipe.get("luci", False),
                    f"Conflicting luci setting for recipe: {key}")
            merged = dict(recipe if previous is None else previous)
            for field in ["select", "expected_apk_names", "languages"]:
                if field in merged or field in recipe:
                    merged[field] = list(dict.fromkeys([*merged.get(field, []), *recipe.get(field, [])]))
            recipes[key] = merged
    return list(recipes.values())


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def set_config(path, values):
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    result = []
    for line in existing.splitlines():
        match = re.match(r"(?:# )?(CONFIG_[A-Za-z0-9_+-]+)(?:=| is not set)", line)
        if not match or match[1] not in values:
            result.append(line)
    for key, value in values.items():
        result.append(f"# {key} is not set" if value == "n" else f"{key}={value}")
    path.write_text("\n".join(result) + "\n", encoding="utf-8")


def fragment_values(path):
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if re.fullmatch(r"CONFIG_[A-Za-z0-9_+-]+=.+", line):
            key, value = line.split("=", 1)
            values[key] = value
        elif match := re.fullmatch(r"# (CONFIG_[A-Za-z0-9_+-]+) is not set", line):
            values[match[1]] = "n"
        else:
            require(not line.strip() or line.startswith("#"), f"Invalid Kconfig line: {line}")
    return values


class Build:
    def __init__(self, task, cfg, third, lock, jobs):
        self.task, self.cfg, self.third, self.lock = task, cfg, third, lock
        self.jobs = jobs or max(1, min(os.cpu_count() or 1, self.memory_jobs()))
        self.work = ROOT / "work" / task
        self.out = ROOT / "dist" / task
        require(not self.work.exists(), f"Build directory already exists: {self.work}. Move/remove this task directory before a fresh build.")
        require(not self.out.exists(), f"Output directory already exists: {self.out}. Save/remove it before a fresh build.")
        self.work.mkdir(parents=True)
        (self.out / "logs").mkdir(parents=True)
        self.log = (self.out / "logs/build.log").open("w", encoding="utf-8")
        self.cache = ROOT / ".cache/openwrt"
        self.cache.mkdir(parents=True, exist_ok=True)
        shutil.copytree(ROOT / "config", self.out / "metadata/config")
        shutil.copytree(ROOT / "patches", self.out / "metadata/patches")
        write_json(self.out / "metadata/run.json", {
            "task": task, "jobs": self.jobs, "repository_commit": os.environ.get("GITHUB_SHA"),
            "run_id": os.environ.get("GITHUB_RUN_ID"), "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "runner_image": os.environ.get("ImageVersion"),
        })

    @staticmethod
    def memory_jobs():
        try:
            match = re.search(r"MemTotal:\s+(\d+)", Path("/proc/meminfo").read_text())
            return max(1, int(match[1]) // (2 * 1024 * 1024))
        except (OSError, TypeError):
            return 2

    def run(self, *args, cwd=None, capture=False, env=None):
        command = [str(arg) for arg in args]
        line = f"\n$ {shlex.join(command)}\n"
        print(line, flush=True)
        self.log.write(line)
        self.log.flush()
        process = subprocess.Popen(command, cwd=cwd or ROOT, env=env, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        output = []
        for line in process.stdout:
            self.log.write(line)
            if capture:
                output.append(line)
            else:
                print(line, end="", flush=True)
        self.log.flush()
        require(process.wait() == 0, f"Command failed: {shlex.join(command)} (see {self.out}/logs/build.log)")
        return "".join(output)

    def make(self, tree, target, serial=False, *variables):
        return self.run("make", f"-j{1 if serial else self.jobs}", target, "V=s", *variables, cwd=tree)

    def checkout(self, item, dest, sparse=None):
        dest.mkdir(parents=True)
        self.run("git", "init", "--quiet", dest)
        self.run("git", "remote", "add", "origin", item["url"], cwd=dest)
        args = ["git", "fetch", "--depth=1"]
        if sparse:
            args.append("--filter=blob:none")
        self.run(*args, "origin", item["commit"], cwd=dest)
        if sparse:
            self.run("git", "sparse-checkout", "init", "--cone", cwd=dest)
            self.run("git", "sparse-checkout", "set", *sparse, cwd=dest)
        self.run("git", "checkout", "--detach", "FETCH_HEAD", cwd=dest)
        actual = self.run("git", "rev-parse", "HEAD", cwd=dest, capture=True).strip()
        require(actual == item["commit"], "Git source commit mismatch")

    def archive(self, kind, dest):
        item = self.lock["downloads"][kind]
        filename = item["url"].rsplit("/", 1)[1]
        archive = self.cache / f"{item['sha256']}-{filename}"
        if not archive.exists() or digest(archive) != item["sha256"]:
            temporary = archive.with_suffix(".partial")
            self.run("curl", "--fail", "--location", "--retry", "4", "--output", temporary, item["url"])
            require(digest(temporary) == item["sha256"], f"SHA256 mismatch: {filename}")
            temporary.replace(archive)
        self.unpack(archive, dest)
        return dest

    def unpack(self, archive, dest):
        dest.mkdir(parents=True)
        # Official SDK and ImageBuilder archives contain trusted relative symlinks.
        self.run("tar", "--zstd", "-xf", archive, "--strip-components=1", "-C", dest)

    def feeds(self, tree, sdk):
        entries = list(self.lock["feeds"])
        lines = []
        if sdk:
            core = self.lock["openwrt"]
            lines.append(f"src-git --root=package base {core['url']}^{core['commit']}")
            entries.insert(0, {"name": "base", **core})
        lines += [f"src-git {feed['name']} {feed['url']}^{feed['commit']}" for feed in self.lock["feeds"]]
        (tree / "feeds.conf").write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.run("./scripts/feeds", "update", "-a", cwd=tree)
        for feed in entries:
            actual = self.run("git", "rev-parse", "HEAD", cwd=tree / "feeds" / feed["name"], capture=True).strip()
            require(actual == feed["commit"], f"Feed {feed['name']} did not resolve to its locked commit")
        self.run("./scripts/feeds", "install", "-a", cwd=tree)

    def patch(self, tree, directory):
        for path in sorted(directory.glob("*.patch")):
            self.run("git", "apply", "--check", path, cwd=tree)
            self.run("git", "apply", path, cwd=tree)

    def configure(self, tree, values, required=()):
        set_config(tree / ".config", values)
        self.make(tree, "defconfig", True)
        # Preserve the resolved configuration even if required symbols were
        # dropped, so the failed run's artifact contains useful diagnostics.
        shutil.copy2(tree / ".config", self.out / f"metadata/{tree.name}.config")
        actual = fragment_values(tree / ".config")
        for symbol in required:
            require(actual.get(symbol) in ("y", "m"), f"Kconfig dropped required symbol: {symbol}")
        require(actual.get("CONFIG_USE_APK") == "y", "SDK must produce APK packages")

    def download_dir(self, tree):
        directory = self.cache / "dl" / f"{self.cfg['openwrt']['release']}-x86-64"
        directory.mkdir(parents=True, exist_ok=True)
        return f'DL_DIR={directory}'

    def firmware(self):
        tree = self.archive("imagebuilder", self.work / "imagebuilder")
        # The upstream dd padding reads with bs=rootfs size. For large images,
        # Linux short reads plus conv=sync insert padding between file chunks.
        self.patch(tree, ROOT / "patches/imagebuilder")
        cfg = self.cfg["firmware"]
        set_config(tree / ".config", {
            "CONFIG_TARGET_KERNEL_PARTSIZE": str(cfg["boot_partsize_mib"]),
            "CONFIG_TARGET_ROOTFS_PARTSIZE": str(cfg["rootfs_partsize_mib"]),
            "CONFIG_TARGET_ROOTFS_EXT4FS": "y", "CONFIG_TARGET_ROOTFS_SQUASHFS": "n",
            "CONFIG_GRUB_EFI_IMAGES": "y", "CONFIG_GRUB_IMAGES": "n",
            "CONFIG_TARGET_IMAGES_GZIP": "y",
        })
        overlay = self.work / "overlay"
        shutil.copytree(repo_path(cfg["files_dir"]), overlay, ignore=shutil.ignore_patterns(".gitkeep"))
        common = [f"PROFILE={self.cfg['openwrt']['profile']}", "PACKAGES=" + " ".join(package_list(repo_path(cfg["packages_file"])))]
        manifest = self.run("make", "manifest", *common, "STRIP_ABI=1", cwd=tree, capture=True)
        (self.out / "manifest.txt").write_text(manifest, encoding="utf-8")
        self.run("make", "image", *common, f"ROOTFS_PARTSIZE={cfg['rootfs_partsize_mib']}",
                 f"FILES={overlay}", f"EXTRA_IMAGE_NAME={cfg['extra_image_name']}",
                 "DISABLED_SERVICES=" + " ".join(cfg["disabled_services"]), cwd=tree)
        images = list((tree / "bin/targets/x86/64").glob("*-generic-ext4-combined-efi.img.gz"))
        require(len(images) == 1, f"Expected one EFI ext4 image, got {images}")
        shutil.copy2(images[0], self.out)
        shutil.copy2(tree / ".config", self.out / "metadata/imagebuilder.config")
        for pattern in ["*.manifest", "profiles.json", "*.buildinfo"]:
            for path in (tree / "bin/targets/x86/64").glob(pattern):
                shutil.copy2(path, self.out / "metadata" / path.name)

    def fortran(self):
        tree = self.work / "source"
        self.checkout(self.lock["openwrt"], tree)
        self.patch(tree, ROOT / "patches/fortran/openwrt")
        self.feeds(tree, sdk=False)
        values = fragment_values(repo_path(self.cfg["fortran"]["sdk_config"]))
        values.update({"CONFIG_TARGET_x86": "y", "CONFIG_TARGET_x86_64": "y",
                       "CONFIG_TARGET_x86_64_DEVICE_generic": "y", "CONFIG_VERSIONOPT": "y",
                       "CONFIG_VERSION_NUMBER": json.dumps(self.cfg["openwrt"]["release"]),
                       "CONFIG_VERSION_FILENAMES": "y"})
        self.configure(tree, values, ["CONFIG_INSTALL_GFORTRAN", "CONFIG_SDK"])
        download = self.download_dir(tree)
        self.make(tree, "toolchain/install", False, download)
        self.check_toolchain(tree)
        # A clean runner has no prebuilt kernel modules. Build the SDK's target
        # staging files explicitly; none of these kernels/kmods enter firmware.
        self.make(tree, "target/linux/compile", False, download)
        self.make(tree, "package/compile", False, download)
        self.make(tree, "package/install", True, download)
        self.export_sdk(tree, download)
        archives = list((tree / "bin/targets/x86/64").glob("openwrt-sdk-*.tar.zst"))
        require(len(archives) == 1, f"Expected one exported SDK, got {archives}")
        archive = self.out / f"openwrt-sdk-{self.cfg['openwrt']['release']}-x86-64-gfortran-openmp.tar.zst"
        shutil.copy2(archives[0], archive)
        sdk = self.work / "sdk"
        self.unpack(archive, sdk)
        self.check_toolchain(sdk)
        self.feeds(sdk, sdk=True)
        self.patch(sdk / "feeds/packages", ROOT / "patches/fortran/packages")
        install_dir = sdk / "feeds/packages/devel/gcc/files"
        install_dir.mkdir(exist_ok=True)
        shutil.copy2(ROOT / "scripts/install-fortran-files.sh", install_dir)
        # Refresh package metadata after the new package definitions are added.
        self.run("./scripts/feeds", "update", "-i", "packages", cwd=sdk)
        self.run("./scripts/feeds", "install", "-p", "packages", "gcc", cwd=sdk)
        values = fragment_values(repo_path(self.cfg["fortran"]["packages_config"]))
        self.configure(sdk, values, [key for key, value in values.items() if key.startswith("CONFIG_PACKAGE_") and value != "n"])
        runtime = (sdk / "package/toolchain/Makefile").read_text(encoding="utf-8")
        require(runtime.count("define Package/libgomp/install") == 2, "Exported SDK lost the internal libgomp install patch")
        download = self.download_dir(sdk)
        self.make(sdk, "package/toolchain/clean", True, download)
        self.make(sdk, "package/toolchain/compile", True, download)
        self.make(sdk, "package/feeds/packages/gcc/clean", True, download)
        self.make(sdk, "package/feeds/packages/gcc/compile", False, download)
        selected = self.collect_apks(sdk, self.cfg["fortran"]["required_apk_names"], dependencies=False)
        self.audit_fortran(sdk, selected)
        shutil.copytree(ROOT / "tests", self.out / "tests", ignore=shutil.ignore_patterns("__pycache__", "test_*.py"))

    def export_sdk(self, tree, download):
        # Changing CONFIG_BUILDBOT only at export enables OpenWrt's .ver_check
        # cleanup and deletes the already-built toolchain. Pin only BASE_FEED;
        # command-line make variables propagate to target/sdk's sub-make.
        core = self.lock["openwrt"]
        base_feed = f"src-git --root=package base {core['url']}^{core['commit']}"
        self.make(tree, "target/sdk/install", False, download, f"BASE_FEED={base_feed}")

    def check_toolchain(self, tree):
        compilers = list((tree / "staging_dir").glob("toolchain-*/bin/*-openwrt-linux-musl-gfortran"))
        require(len(compilers) == 1, "Expected one cross gfortran")
        compiler = compilers[0]
        compiler_env = {**os.environ, "STAGING_DIR": str(tree / "staging_dir")}
        version = self.run(compiler, "-dumpfullversion", capture=True, env=compiler_env).strip()
        triple = self.run(compiler, "-dumpmachine", capture=True, env=compiler_env).strip()
        require(triple == "x86_64-openwrt-linux-musl", f"Unexpected compiler target: {triple}")
        tc = compiler.parent.parent
        for name in ["libc.so", "libgcc_s.so.1", "libgfortran.so", "libgomp.so", "libquadmath.so"]:
            require((tc / "lib" / name).exists(), f"Missing toolchain runtime: {name}")
        include = tc / f"lib/gcc/{triple}/{version}"
        for name in ["include/omp.h", "include/quadmath.h", "finclude/omp_lib.mod", "finclude/openacc.mod"]:
            require((include / name).is_file(), f"Missing toolchain development file: {name}")
        # Match the shared runtimes shipped in the APKs. Forcing -static here
        # can leave libgfortran's _Unwind_* references unresolved in OpenWrt.
        # musl's libc.so is also its loader: invoke it explicitly because the
        # Ubuntu runner has no target /lib/ld-musl-x86_64.so.1 interpreter.
        executable = tree / "fortran-smoke"
        self.run(compiler, "-O2", "-fopenmp", ROOT / "tests/fortran-openmp.f90", "-o", executable, env=compiler_env)
        loader = tc / "lib/libc.so"
        library_path = tc / "lib"
        runtime_env = {key: value for key, value in os.environ.items()
                       if key not in ("LD_LIBRARY_PATH", "LD_PRELOAD")}
        runtime_env.update({"OMP_NUM_THREADS": "2", "OMP_DYNAMIC": "FALSE"})
        # Keep the resolved library paths in the build log for diagnosis.
        self.run(loader, "--library-path", library_path, "--list", executable, env=runtime_env)
        self.run(loader, "--library-path", library_path, executable, env=runtime_env)
        write_json(self.out / f"metadata/{tree.name}-toolchain.json", {
            "gcc_version": version, "target": triple, "smoke_test": "dynamic-musl",
            "loader": str(loader.relative_to(tree)), "library_path": str(library_path.relative_to(tree)),
            "passed": True,
        })

    def third_party(self, groups):
        recipes = merge_recipes(groups)
        sdk = self.archive("sdk", self.work / "sdk")
        self.feeds(sdk, sdk=True)
        sources = {recipe["source"] for recipe in recipes}
        for source in sorted(sources):
            paths = sorted({recipe["path"] for recipe in recipes if recipe["source"] == source})
            self.checkout(self.lock["third_party"][source], self.work / "sources" / source, paths)
        copied = []
        for recipe in recipes:
            source = self.work / "sources" / recipe["source"] / recipe["path"]
            require((source / "Makefile").is_file(), f"Recipe has no Makefile: {source}")
            name = source.name
            dest = sdk / "package/custom" / name
            require(not dest.exists(), f"Conflicting recipe directory: {name}")
            shutil.copytree(source, dest, symlinks=True)
            if recipe.get("luci"):
                makefile = dest / "Makefile"
                text = makefile.read_text(encoding="utf-8")
                require(text.count("include ../../luci.mk") == 1, "Unexpected LuCI recipe include; review integration")
                text = text.replace("include ../../luci.mk", "include $(TOPDIR)/feeds/luci/luci.mk")
                # Imported recipes have no Git history at their new path. Supply
                # a deterministic version instead of inheriting our repo's date.
                commit = self.lock["third_party"][recipe["source"]]["commit"]
                epoch = int(self.run("git", "show", "-s", "--format=%ct", "HEAD",
                                     cwd=self.work / "sources" / recipe["source"], capture=True).strip())
                date = datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y.%m.%d")
                version = f"{date}~{commit[:12]}"
                text = text.replace("include $(TOPDIR)/rules.mk", f"include $(TOPDIR)/rules.mk\n\nPKG_VERSION:={version}\nPKG_RELEASE:=1\nPKG_SRC_VERSION:={version}\nPKG_PO_VERSION:={version}")
                makefile.write_text(text, encoding="utf-8")
            copied.append(name)
        values = {"CONFIG_ALL": "n", "CONFIG_ALL_KMODS": "n", "CONFIG_ALL_NONSHARED": "n",
                  "CONFIG_SIGNED_PACKAGES": "n", "CONFIG_AUTOREMOVE": "n", "CONFIG_BUILD_LOG": "y"}
        selects = sorted({name for recipe in recipes for name in recipe["select"]})
        values.update({f"CONFIG_PACKAGE_{name}": "m" for name in selects})
        # Translation package symbols are hidden. Kconfig selects them through
        # LUCI_LANG_*; setting only CONFIG_PACKAGE_luci-i18n-* is insufficient.
        # SDK Config-build.in declares disabled language options as bool, so m
        # is invalid even though luci.mk declares tristate. Use y for the
        # language; the translation is still limited by its parent package=m.
        languages = {lang for recipe in recipes for lang in recipe.get("languages", [])}
        language_symbols = [f"CONFIG_LUCI_LANG_{lang}" for lang in sorted(languages)]
        values.update({symbol: "y" for symbol in language_symbols})
        self.configure(sdk, values, language_symbols + [f"CONFIG_PACKAGE_{name}" for name in selects])
        shutil.copytree(sdk / "package/custom", self.out / "metadata/recipes", symlinks=True)
        write_json(self.out / "metadata/selection.json", {"groups": [group["name"] for group in groups],
                   "config_files": [group["config_file"] for group in groups], "recipes": recipes})
        for name in copied:
            self.make(sdk, f"package/custom/{name}/compile", False, self.download_dir(sdk))
        required = sorted({name for recipe in recipes for name in recipe["expected_apk_names"]})
        self.collect_apks(sdk, required, dependencies=True)

    def collect_apks(self, sdk, required, dependencies):
        apk = sdk / "staging_dir/host/bin/apk"
        inventory, selected = [], {}
        for path in sorted((sdk / "bin").rglob("*.apk")):
            raw = self.run(apk, "adbdump", "--format", "json", path, capture=True)
            metadata = json.loads(raw)
            info = metadata.get("info", {})
            require(info.get("name") and info.get("version") and info.get("arch"), f"Invalid APK metadata: {path}")
            require(info["arch"] in (self.cfg["openwrt"]["architecture"], "noarch"), f"Wrong APK architecture: {path}")
            record = {"file": path.relative_to(sdk).as_posix(), "sha256": digest(path), "info": info}
            inventory.append(record)
            name = info["name"]
            if name in required:
                require(name not in selected, f"Multiple APKs for {name}")
                shutil.copy2(path, self.out)
                selected[name] = path
            elif dependencies:
                # Keep separately: do not recommend blindly replacing official
                # libc, GCC or LuCI with every package emitted by the SDK.
                target = self.out / "build-dependencies" / path.relative_to(sdk / "bin")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
        write_json(self.out / "metadata/packages.json", inventory)
        require(set(required) == selected.keys(), f"Missing APKs: {set(required) - selected.keys()}")
        return selected

    def audit_fortran(self, sdk, selected):
        apk = sdk / "staging_dir/host/bin/apk"
        root = self.work / "fortran-audit"
        root.mkdir()
        self.run(apk, "extract", "--allow-untrusted", "--no-chown", "--destination", root, *selected.values())
        compiler = next((sdk / "staging_dir").glob("toolchain-*/bin/*-openwrt-linux-musl-gfortran"))
        version = self.run(compiler, "-dumpfullversion", capture=True,
                           env={**os.environ, "STAGING_DIR": str(sdk / "staging_dir")}).strip()
        base = f"usr/lib/gcc/x86_64-openwrt-linux-musl/{version}"
        expected = ["usr/bin/gfortran", "usr/bin/x86_64-openwrt-linux-musl-gfortran", f"{base}/f951",
                    f"{base}/include/ISO_Fortran_binding.h", f"{base}/finclude/omp_lib.mod", f"{base}/finclude/openacc.mod",
                    *[f"{base}/include/{name}" for name in ["omp.h", "openacc.h", "quadmath.h", "quadmath_weak.h"]],
                    *[f"usr/lib/{name}" for name in ["libgomp.a", "libquadmath.a", "libgfortran.a", "libcaf_single.a", "libgomp.so", "libquadmath.so", "libgfortran.so"]],
                    f"{base}/libgomp.spec", f"{base}/libgfortran.spec"]
        for name in expected:
            require((root / name).exists(), f"Missing file or broken link in Fortran APKs: {name}")
        for executable in [root / "usr/bin/gfortran", root / base / "f951"]:
            info = self.run("readelf", "-h", executable, capture=True)
            require("Advanced Micro Devices X86-64" in info, f"Wrong native executable architecture: {executable}")
        write_json(self.out / "metadata/fortran-file-audit.json", {"required_files": expected, "passed": True})

    def finish(self):
        lines = []
        for path in sorted(self.out.rglob("*")):
            if path.is_file() and not path.is_relative_to(self.out / "logs") and path.name != "sha256sums":
                lines.append(f"{digest(path)}  {path.relative_to(self.out).as_posix()}")
        (self.out / "sha256sums").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Build completed: {self.out}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", choices=["validate", "firmware", "fortran", "third-party"])
    parser.add_argument("--targets", default="", help="Comma-separated third-party build group names")
    parser.add_argument("--jobs", type=int, default=0, help="0: automatic, based on CPU and RAM")
    parser.add_argument("--plan", action="store_true", help="Validate and print build inputs; no downloads or compilation")
    args = parser.parse_args()
    require(0 <= args.jobs <= 64, "jobs must be between 0 and 64")
    require(not args.targets or args.task == "third-party", "targets is only supported by third-party")
    cfg, third, lock = load_config()
    groups = select_groups(third, args.targets) if args.task == "third-party" else []
    merge_recipes(groups)  # Detect conflicting imports before downloads, including --plan.
    if args.task == "validate" or args.plan:
        print(json.dumps({"task": args.task, "release": cfg["openwrt"]["release"], "target": lock["target"],
                          "groups": [group["name"] for group in groups],
                          "config_files": [group["config_file"] for group in groups], "configuration": "valid"}, indent=2))
        return
    require(sys.platform == "linux", "Actual OpenWrt builds require Linux x86_64; use --plan for offline validation")
    build = Build(args.task, cfg, third, lock, args.jobs)
    try:
        if args.task == "firmware":
            build.firmware()
        elif args.task == "fortran":
            build.fortran()
        else:
            build.third_party(groups)
        build.finish()
    finally:
        build.log.close()


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)

