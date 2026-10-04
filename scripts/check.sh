#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 scripts/build.py validate
python3 -m unittest discover -s tests -p 'test_*.py' -v
for script in scripts/*.sh tests/*.sh; do
    bash -n "$script"
done
shellcheck scripts/*.sh tests/*.sh

