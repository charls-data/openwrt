#!/usr/bin/env python3
"""Optionally publish one successful build as a uniquely named GitHub Release."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", choices=["firmware", "fortran", "third-party"])
    args = parser.parse_args()
    cfg = tomllib.loads((ROOT / "config/build.toml").read_text(encoding="utf-8"))
    release = cfg["openwrt"]["release"]
    run = os.environ["GITHUB_RUN_ID"]
    attempt = os.environ["GITHUB_RUN_ATTEMPT"]
    tag = f"{args.task}-{release}-x86-64-{run}-{attempt}"
    out = ROOT / "dist" / args.task
    if not (out / "sha256sums").is_file():
        raise SystemExit("Refusing to publish an incomplete build")
    bundle = ROOT / "work" / f"{tag}.tar.zst"
    subprocess.run(["tar", "--zstd", "--exclude=./logs", "-cf", str(bundle), "-C", str(out), "."], check=True)
    notes = ROOT / "work" / f"{tag}.txt"
    text = f"OpenWrt {release}, x86/64 generic.\n\nBuild: {args.task}\n"
    text += f"Repository commit: {os.environ['GITHUB_SHA']}\n"
    text += f"Actions run: https://github.com/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{run}\n\n"
    text += "The archive includes outputs, sha256sums and exact build configuration. SDK-built APKs are installed separately from firmware.\n"
    if args.task == "third-party":
        selected = json.loads((out / "metadata/selection.json").read_text(encoding="utf-8"))
        text += "\nSelected groups: " + ", ".join(selected["groups"]) + "\n"
    notes.write_text(text, encoding="utf-8")
    subprocess.run(["gh", "release", "create", tag, str(bundle), "--repo", os.environ["GITHUB_REPOSITORY"],
                    "--target", os.environ["GITHUB_SHA"], "--title", tag, "--notes-file", str(notes), "--latest=false"], check=True)


if __name__ == "__main__":
    main()

