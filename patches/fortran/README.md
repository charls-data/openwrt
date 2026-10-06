# Fortran 补丁说明

原始本地修改后的 Makefile 未保留。本目录根据仓库 `Build.md` 重建，补丁基于 `config/sources.lock.json` 指定的官方源文件。r7 已完成 GitHub 编译；设备测试发现运行库经 `sstrip` 后不能作为链接输入，r8 为开发包增加独立的链接用共享库。r9 补齐后续 OpenMP 测试发现缺失的 `libpthread.a` 兼容归档。

| 补丁 | 应用位置 | 作用 |
| --- | --- | --- |
| `openwrt/001-enable-libgomp.patch` | OpenWrt 源码 | cross GCC 启用 libgomp；GFortran 由 SDK Kconfig 片段启用 |
| `openwrt/002-install-libgomp.patch` | OpenWrt 源码 | 补齐 internal toolchain 的 libgomp 安装规则，随 SDK 导出 |
| `packages/001-native-gfortran.patch` | 定制 SDK 的 `feeds/packages` | native GCC 启用 Fortran、OpenMP、Quadmath，并新增两个附加包 |

native 补丁调用 `scripts/install-fortran-files.sh`；构建入口自动将该脚本复制到 GCC recipe 的 `files/`。本机程序、头文件、specs 和 Fortran/OpenMP/Quadmath 静态库从 native GCC 安装目录提取；`finclude`、链接用的目标架构共享库和 `libpthread.a` 从同版本 cross 工具链复制。

头文件和 specs 在 `/usr/lib/gcc/<triple>/<version>/` 下，静态库位于 `/usr/lib/`。`gcc-fortran-dev` 在 GCC 私有目录安装 `libgfortran.so`、`libgomp.so` 两个真实 ELF 文件，保留节表；该 recipe 已使用 GNU `strip`，不会像 core runtime 的 `sstrip` 那样删除节表。`/usr/lib/` 下的同名开发链接指向这两个文件。Quadmath 的开发链接指向官方 GCC 已提供的私有库，不重复占有它。

不能让开发链接指向 `/lib`、`/usr/lib` 中经 `sstrip` 处理的运行库：这种 ELF 仍可被动态加载器加载，但链接器会报 `file in wrong format`。运行时依然通过 SONAME 使用 `libgfortran`、`libgomp`、`libquadmath1` APK 中的库。

`gcc-fortran-dev` 还在 GCC 私有目录安装 SDK 原始的 `libpthread.a`。它是 musl 的 8 字节空归档，线程实现仍来自 libc；该文件使 `-fopenmp` 自动引入的 `-lpthread` 可以正常链接，无需手动创建文件或额外添加 `-L`。两个 native 附加包统一提升到 `14.3.0-r9`；三个运行库仍为 `14.3.0-r5`。

导出的五个包由官方 core runtime 加上 `gcc-fortran-dev`、`gfortran` 组成；本任务不会发布重编的 `gcc`。升版时必须复核官方 GCC 包的文件归属，避免新增开发文件与官方包发生冲突。

构建先检查补丁能否应用，再检查工具链和导出 APK。文件审计要求链接用 ELF 为 x86_64 共享库，且保留节表和动态符号节，同时验证 `libpthread.a` 是完整的 musl 空归档。Linux 回归测试模拟 `sstrip` 删除节表，验证旧运行库链接失败、独立开发库链接成功；SDK 缺少 pthread 兼容归档时，安装脚本也会立即失败。

最后通过 `apk add` 将五个 APK 与官方 GCC、binutils、base-files 安装到独立根目录，检查文件归属和依赖，在 chroot 中运行交付的本机 `gfortran` / 官方 `gcc`。测试不添加 `-L` 或修复库链接，同时验证 Fortran/OpenMP/REAL(16)、C/OpenMP/Quadmath 及最终程序的动态依赖。隔离安装关闭包脚本，不启动路由服务；此检查覆盖编译器安装与链接，不替代设备上的服务测试。本地 Linux 执行时需 root 或可无交互调用的 sudo，用于 chroot 和创建 `/dev/null`。

隔离安装同时使用 `--no-cache --no-logfile`，避免 APK 在安装 `base-files` 前创建真实的 `/var` 目录，与该包的 `/var -> tmp` 软链接冲突；控制台输出仍保存在 `logs/build.log`。
