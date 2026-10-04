#!/usr/bin/env bash
set -euo pipefail
task=${1:?Usage: prepare-runner.sh firmware|fortran|third-party}
case "$task" in
    firmware) minimum_gib=20 ;;
    fortran) minimum_gib=35 ;;
    third-party) minimum_gib=12 ;;
    *) printf 'Unknown task: %s\n' "$task" >&2; exit 1 ;;
esac
[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]]

# Only clean known, unused preinstalled SDKs on disposable GitHub-hosted VMs.
# A local invocation only installs dependencies and checks free disk space.
if [[ ${GITHUB_ACTIONS:-} == true && ${RUNNER_ENVIRONMENT:-} == github-hosted ]]; then
    sudo rm -rf -- /usr/share/dotnet /usr/local/lib/android /opt/ghc /usr/local/.ghcup /opt/hostedtoolcache/CodeQL
    sudo docker image prune --all --force
fi
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
    build-essential clang flex bison gawk gettext git libncurses-dev libssl-dev \
    python3 python3-setuptools python3-pyelftools rsync swig unzip \
    zlib1g-dev file wget curl zstd cpio xz-utils patch quilt gperf help2man \
    autoconf automake libtool libelf-dev pkgconf cmake ninja-build time \
    gcc-multilib g++-multilib shellcheck gh
free_kib=$(df -Pk . | awk 'NR==2 {print $4}')
if (( free_kib < minimum_gib * 1024 * 1024 )); then
    printf 'Need at least %s GiB free for %s; currently %s KiB.\n' "$minimum_gib" "$task" "$free_kib" >&2
    exit 1
fi
df -h .
free -h

