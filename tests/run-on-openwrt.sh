#!/bin/sh
# Run after installing the five APKs alongside official gcc and binutils.
set -eu
export LC_ALL=C
unset LIBRARY_PATH LD_LIBRARY_PATH LD_PRELOAD GCC_EXEC_PREFIX COMPILER_PATH
cd "$(dirname "$0")"
test_dir=$(mktemp -d)
trap 'rm -rf "$test_dir"' EXIT HUP INT TERM
gfortran --version
test "$(gcc -dumpfullversion)" = "$(gfortran -dumpfullversion)"
for compiler in gcc gfortran; do
    for library in libgfortran libgomp libquadmath; do
        path=$("$compiler" "-print-file-name=$library.so")
        printf '%s: %s -> %s\n' "$compiler" "$library" "$path"
        test "$path" != "$library.so" && test -f "$path"
        if ! readelf -SW "$path" | grep -q '\.dynsym'; then
            printf 'Not a linkable DSO (missing .dynsym/section table): %s\n' "$path" >&2
            exit 1
        fi
    done
done

check_dynamic() {
    executable=$1
    shift
    needed=$(readelf -d "$executable")
    printf '%s\n' "$needed"
    for library in "$@"; do
        if ! printf '%s\n' "$needed" | grep -Fq "[$library.so."; then
            printf 'Expected dynamic dependency %s in %s\n' "$library" "$executable" >&2
            exit 1
        fi
    done
}

gfortran -O2 -fopenmp fortran-openmp.f90 -o "$test_dir/fortran"
check_dynamic "$test_dir/fortran" libgfortran libgomp
OMP_NUM_THREADS=2 OMP_DYNAMIC=FALSE "$test_dir/fortran"
gcc -O2 -fopenmp openmp-quadmath.c -lquadmath -o "$test_dir/c"
check_dynamic "$test_dir/c" libgomp libquadmath
OMP_NUM_THREADS=2 OMP_DYNAMIC=FALSE "$test_dir/c"

