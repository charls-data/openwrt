# Fortran 补丁说明

原始本地修改后的 Makefile 未保留。本目录根据仓库 `Build.md` 中已验证的编译选项与文件布局重建；补丁基于 `config/sources.lock.json` 指定的官方源文件，尚未完成 GitHub 整链编译验证。

| 补丁 | 应用位置 | 作用 |
| --- | --- | --- |
| `openwrt/001-enable-libgomp.patch` | OpenWrt 源码 | cross GCC 启用 libgomp；GFortran 由 SDK Kconfig 片段启用 |
| `openwrt/002-install-libgomp.patch` | OpenWrt 源码 | 补齐 internal toolchain 的 libgomp 安装规则，随 SDK 导出 |
| `packages/001-native-gfortran.patch` | 定制 SDK 的 `feeds/packages` | native GCC 启用 Fortran、OpenMP、Quadmath，并新增两个附加包 |

native 补丁调用 `scripts/install-fortran-files.sh`；构建入口自动将该脚本复制到 GCC recipe 的 `files/`。它只从 native GCC 安装目录提取本机程序、头文件、specs 和静态库；`finclude` 从同版本 cross 工具链复制，避免本地记录中的 `.mod` 缺失问题。

安装布局遵循原始记录：头文件和 specs 在 `/usr/lib/gcc/<triple>/<version>/` 下；静态库与开发链接在 `/usr/lib/`。开发链接从 runtime ELF 的 SONAME 生成，避免把 `libquadmath1` 的包名误当成 `libquadmath.so.1`。

导出的五个包由官方 core runtime 加上 `gcc-fortran-dev`、`gfortran` 组成；本任务不会发布重编的 `gcc`。升版时必须复核官方 GCC 包的文件归属，避免新增开发文件与官方包发生冲突。

构建先检查补丁能否应用，再检查工具链和导出 APK 的关键文件。`tests/test_fortran_install.py` 在 Linux 上验证安装脚本、ELF SONAME 链接，以及文件缺失/重复时明确失败。
