#!/usr/bin/env bash
# Called by the patched native GCC recipe. Compiler/Fortran archives come from
# the native install tree; modules, target DSOs and musl's pthread stub use the SDK.
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

link_library() {
    local library=$1 soname
    # Runtime APKs use sstrip: they can be loaded, but lack the ELF section
    # table required by ld. Keep a separate, linkable DSO like official gcc.
    soname=$(readelf -d "$toolchain/lib/$library.so" | sed -n 's/.*(SONAME).*\[\([^]]*\)\].*/\1/p')
    [[ "$soname" == "$library.so."* && "$soname" != */* ]]
    test -e "$toolchain/lib/$soname"
    install -m 0644 "$toolchain/lib/$library.so" "$dest$gccdir/$library.so"
    ln -s "gcc/$triple/$version/$library.so" "$dest/usr/lib/$library.so"
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
        # musl implements pthreads in libc, but -fopenmp implies -lpthread.
        # Official gcc omits this compatibility archive by default. Put the
        # SDK's original archive in the default search path of both compilers.
        install -m 0644 "$toolchain/lib/libpthread.a" "$dest$gccdir/libpthread.a"
        link_library libgomp
        link_library libgfortran
        # The official gcc dependency already owns the linkable Quadmath DSO.
        # Do not duplicate it or point at /lib's sstripped runtime.
        ln -s "gcc/$triple/$version/libquadmath.so" "$dest/usr/lib/libquadmath.so"
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

