#!/usr/bin/env python3
"""Explicitly refresh source pins. Normal builds never follow moving branches."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tomllib
import urllib.request

from build import load_third_party

ROOT = Path(__file__).resolve().parents[1]


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "openwrt-build-lock"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def resolve(url, ref):
    if re.fullmatch(r"[0-9a-f]{40}", ref):
        return ref
    refs = [f"refs/heads/{ref}", f"refs/tags/{ref}", f"refs/tags/{ref}^{{}}"]
    result = subprocess.check_output(["git", "ls-remote", url, *refs], text=True)
    candidates = {line.split()[1]: line.split()[0] for line in result.splitlines()}
    if refs[0] in candidates and refs[1] in candidates:
        raise ValueError(f"Ambiguous branch/tag: {ref}")
    for name in reversed(refs):
        if name in candidates:
            return candidates[name]
    raise ValueError(f"Cannot resolve {url} {ref}")


def refresh_third_party(existing, sources):
    # Keep pins for temporarily unlisted plugins so switching back does not
    # silently lose their known source versions. Refresh only loaded sources.
    result = dict(existing)
    for source in sources:
        result[source["name"]] = {"url": source["url"], "commit": resolve(source["url"], source["ref"])}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--third-party-only", action="store_true", help="Preserve official OpenWrt/SDK/feed pins")
    args = parser.parse_args()
    cfg = tomllib.loads((ROOT / "config/build.toml").read_text(encoding="utf-8"))
    third = load_third_party(cfg)
    path = ROOT / "config/sources.lock.json"
    lock = json.loads(path.read_text(encoding="utf-8"))
    previous_third_party = lock.get("third_party", {})
    platform = cfg["openwrt"]
    release = platform["release"]
    target = f"{platform['target']}/{platform['subtarget']}"
    if args.third_party_only:
        if (lock["release"], lock["target"]) != (release, target):
            raise ValueError("OpenWrt version changed; a complete lock refresh is required")
    else:
        base = f"https://downloads.openwrt.org/releases/{release}/targets/{target}"
        sums = {}
        for line in fetch(f"{base}/sha256sums").decode().splitlines():
            match = re.fullmatch(r"([0-9a-f]{64})\s+\*?(.+)", line)
            if match:
                sums[match[2]] = match[1]
        downloads = {}
        for kind, prefix in [("imagebuilder", "openwrt-imagebuilder-"), ("sdk", "openwrt-sdk-")]:
            found = [name for name in sums if name.startswith(prefix) and name.endswith(".Linux-x86_64.tar.zst")]
            if len(found) != 1:
                raise ValueError(f"Expected one {kind} archive, found: {found}")
            downloads[kind] = {"url": f"{base}/{found[0]}", "sha256": sums[found[0]]}
        feeds_raw = fetch(f"{base}/feeds.buildinfo")
        if hashlib.sha256(feeds_raw).hexdigest() != sums["feeds.buildinfo"]:
            raise ValueError("feeds.buildinfo checksum mismatch")
        mirrors = {
            "https://git.openwrt.org/feed/packages.git": "https://github.com/openwrt/packages.git",
            "https://git.openwrt.org/project/luci.git": "https://github.com/openwrt/luci.git",
            "https://git.openwrt.org/feed/routing.git": "https://github.com/openwrt/routing.git",
            "https://git.openwrt.org/feed/telephony.git": "https://github.com/openwrt/telephony.git",
        }
        feeds = []
        for line in feeds_raw.decode().splitlines():
            match = re.fullmatch(r"src-git\s+(\S+)\s+(https://[^\s^]+)\^([0-9a-f]{40})", line)
            if not match:
                raise ValueError(f"Unpinned or unsupported official feed: {line}")
            feeds.append({"name": match[1], "url": mirrors.get(match[2], match[2]), "commit": match[3]})
        core_url = "https://github.com/openwrt/openwrt.git"
        lock = {"schema_version": 1, "release": release, "target": target,
                "openwrt": {"url": core_url, "commit": resolve(core_url, f"v{release}")},
                "downloads": downloads, "feeds": feeds}
    lock["third_party"] = refresh_third_party(previous_third_party, third["sources"])
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    print(f"Updated {path}. Review the diff; version upgrades also require patch review.")


if __name__ == "__main__":
    main()

