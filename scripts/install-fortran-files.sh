#!/usr/bin/env bash
# Called by the patched native GCC recipe. All binaries come from the target
# install tree; only compiler-independent Fortran module files come from the SDK.
set -euo pipefail
mode=$1
dest=$2
native=$3
toolchain=$4
triple=$5
version=$6
gccdir="/usr/lib/gcc/$triple/$version"

unique_file() {
    local root=$1 name=$2
    local -a matches=()
    mapfile -t matches < <(find "$root" -type f -name "$name")
    if [[ ${#matches[@]} != 1 ]]; then
        printf 'Expected exactly one %s under %s, found %s\n' "$name" "$root" "${#matches[@]}" >&2
        return 1
    fi
    printf '%s\n' "${matches[0]}"
}

copy_file() {
    local root=$1 name=$2 directory=$3 source
    source=$(unique_file "$root" "$name")
    install -d "$dest$directory"
    install -m 0644 "$source" "$dest$directory/$name"
}

runtime_link() {
    local library=$1 runtime_dir=$2 soname
    # Read the target runtime's actual SONAME. libquadmath's package ABI suffix
    # is 1, while its ELF SONAME is normally libquadmath.so.0.
    soname=$(readelf -d "$toolchain/lib/$library.so" | sed -n 's/.*(SONAME).*\[\([^]]*\)\].*/\1/p')
    [[ "$soname" == "$library.so."* && "$soname" != */* ]]
    test -e "$toolchain/lib/$soname"
    if [[ "$runtime_dir" == /lib ]]; then
        ln -s "../../lib/$soname" "$dest/usr/lib/$library.so"
    else
        ln -s "$soname" "$dest/usr/lib/$library.so"
    fi
}

case "$mode" in
    dev)
        for header in omp.h openacc.h quadmath.h quadmath_weak.h; do
            copy_file "$native/usr" "$header" "$gccdir/include"
        done
        for spec in libgomp.spec libgfortran.spec; do
            copy_file "$native/usr" "$spec" "$gccdir"
        done
        for library in libgomp.a libquadmath.a libgfortran.a libcaf_single.a; do
            copy_file "$native/usr" "$library" /usr/lib
        done
        runtime_link libgomp /lib
        runtime_link libquadmath /lib
        runtime_link libgfortran /usr/lib
        ;;
    compiler)
        install -d "$dest/usr/bin" "$dest$gccdir"
        install -m 0755 "$native/usr/bin/$triple-gfortran" "$dest/usr/bin/$triple-gfortran"
        ln -s "$triple-gfortran" "$dest/usr/bin/gfortran"
        install -m 0755 "$(unique_file "$native/usr" f951)" "$dest$gccdir/f951"
        copy_file "$native/usr" ISO_Fortran_binding.h "$gccdir/include"
        modules="$toolchain/lib/gcc/$triple/$version/finclude"
        for module in ieee_arithmetic.mod ieee_exceptions.mod ieee_features.mod omp_lib.f90 omp_lib.h omp_lib.mod omp_lib_kinds.mod openacc.f90 openacc.mod openacc_kinds.mod openacc_lib.h; do
            test -s "$modules/$module"
        done
        cp -a "$modules" "$dest$gccdir/"
        ;;
    *) printf 'Unknown install mode: %s\n' "$mode" >&2; exit 1 ;;
esac

