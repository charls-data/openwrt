#!/bin/sh
# Run after installing the five APKs alongside official gcc and binutils.
set -eu
cd "$(dirname "$0")"
test_dir=$(mktemp -d)
trap 'rm -rf "$test_dir"' EXIT HUP INT TERM
gfortran --version
gfortran -O2 -fopenmp fortran-openmp.f90 -o "$test_dir/fortran"
OMP_NUM_THREADS=2 "$test_dir/fortran"
gcc -O2 -fopenmp openmp-quadmath.c -lquadmath -o "$test_dir/c"
OMP_NUM_THREADS=2 "$test_dir/c"

