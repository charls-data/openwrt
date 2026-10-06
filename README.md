# OpenWrt 自用构建

面向 OpenWrt **25.12.5 / x86/64 / generic**，三个独立的 GitHub Actions workflow 均为手动触发。固件与 SDK 生成的 APK 分开交付，安装系统后按需添加 APK。

| Actions 中的名称 | 输入与用途 | 主要产物 |
| --- | --- | --- |
| Build firmware | 官方 ImageBuilder，读取固件配置与包列表 | UEFI / ext4 固件，rootfs 8192 MiB、启动分区 128 MiB |
| Build Fortran SDK and packages | 官方源码构建支持 GFortran / OpenMP 的 SDK，再编译本机 Fortran | 定制 SDK 与五个 APK |
| Build third-party packages | 官方 SDK，按配置选择第三方包组 | msd_lite、vlmcsd、qBittorrent，各自的 LuCI / 中文包及配套运行库 |

这三个任务不互相依赖。通常只需反复运行第三个；更换 OpenWrt 版本时，再重新构建前两个。不会因普通 push 自动启动耗时编译。

## 首次运行

1. 将本目录提交到 GitHub 仓库的默认分支，包含 `.github/workflows/`。
2. 在仓库 **Actions** 中选择一个 workflow，点击 **Run workflow**。
3. 编译完成后，在该次运行的 **Artifacts** 下载结果。固件和 Fortran 默认还会发布到 **Releases**，第三方包默认只上传 Artifact。

所有任务使用 `ubuntu-24.04` GitHub 托管 runner。无需自托管机器、PAT 或额外 Secrets；发布使用本仓库的 `GITHUB_TOKEN`。如果组织策略禁止 `contents: write`，需由仓库管理员允许 Release 发布，或调整 workflow 权限并关闭发布选项。

输入参数：

| 参数 | 可用任务 | 含义 |
| --- | --- | --- |
| `publish_release` | 全部 | 成功后将产物打包为 `.tar.zst` 并创建独立 Release；默认固件/Fortran 开、第三方关 |
| `jobs` | Fortran、第三方 | `0` 自动按 CPU 数和内存选择并行度；也可指定 `1`、`2`、`4` |
| `targets` | 第三方 | 留空编译所有启用的组；可填 `msd-lite`、`vlmcsd`、`qbittorrent`，多组以英文逗号分隔 |

Artifacts 配置保留 30 天，失败时也上传已有日志。Release 用任务名、OpenWrt 版本、运行编号和重试编号区分，不覆盖以前产物，适合保存很少重编的固件和 SDK。Fortran 和第三方任务超时设为 360 分钟；实际耗时取决于托管 runner 和下载速度，尚未在 GitHub 完成整链实测。

## 仓库结构

```text
.github/workflows/
  firmware.yml                    # 官方 ImageBuilder
  fortran.yml                     # 定制 SDK + 五个 Fortran APK
  third-party.yml                 # 官方 SDK + 可选包组
config/
  build.toml                      # OpenWrt 版本、目标、分区、文件路径
  packages.txt                    # 固件包列表
  sources.lock.json               # 下载 SHA256、源码和 feed 提交
  third-party/                    # 每个插件一个独立 TOML
    msd-lite.toml                 # msd_lite + LuCI + 中文包
    vlmcsd.toml                   # vlmcsd + JavaScript LuCI + 中文包
    qbittorrent.toml              # qBittorrent + Qt6 / libtorrent + LuCI / 中文包
  fortran/
    sdk.config                    # 定制 SDK 配置片段
    packages.config               # 五个 Fortran 包的配置片段
files/                            # ImageBuilder 根文件系统覆盖文件
patches/fortran/
  openwrt/                        # cross libgomp 开关与 runtime 安装
  packages/                       # native GCC / GFortran 打包补丁
patches/imagebuilder/              # 大 rootfs 镜像的填充修复
scripts/                          # workflow 和本地构建共用入口
tests/                            # 配置/打包测试，以及 OpenWrt 本机测试程序
Build.md                          # 原始本地编译记录
```

`work/`、`dist/` 和 `.cache/` 是生成目录，不提交到仓库。

## 修改固件

编辑 `config/build.toml`：

```toml
[firmware]
packages_file = "config/packages.txt"
files_dir = "files"
rootfs_partsize_mib = 8192
boot_partsize_mib = 128
filesystem = "ext4"
image_type = "combined-efi"
compression = "gzip"
extra_image_name = "econwang-charls"
disabled_services = ["nginx", "dockerd"]
```

启动分区大小写入 ImageBuilder 的 `CONFIG_TARGET_KERNEL_PARTSIZE`。`nginx` 和 `dockerd` 会安装，但默认不启用。固件中的内核与 kmod 来自官方 ImageBuilder 及对应仓库。

ImageBuilder 解压后会应用 `patches/imagebuilder/001-pad-with-truncate.patch`。官方 `Image/pad-to` 使用整个目标大小作为 `dd bs`；8 GiB 文件会因 Linux 单次读取长度限制和 `conv=sync` 被错误填充为 40 GiB。修复用 `truncate` 向上对齐文件长度，保留已有数据，也避免分配巨大复制缓冲区。此问题影响额外生成的单独 `rootfs.img.gz`；EFI combined 镜像由另一条规则读取原始 rootfs。补丁只调整宿主机构建步骤，不修改固件内核或包。

`config/packages.txt` 一行一个包，支持空行、`#` 注释、行尾注释，以及 `-包名` 移除默认包。依赖交给 ImageBuilder 解析，无需手动展开。初始列表来自 `Build.md`。

当前列表使用 `dnsmasq-full` / `-dnsmasq`、`ip-full` / `-ip-tiny`、`ethtool-full` / `-ethtool` 三组选择，安装完整版本并排除精简版本；包名前的 `-` 是 ImageBuilder 的移除语法。三种完整版本均在 [25.12.5 x86_64 官方 base 仓库](https://downloads.openwrt.org/releases/25.12.5/packages/x86_64/base/) 中。`dnsmasq-full` 增加 DNSSEC、nftset 等编译支持，具体功能仍按 UCI 配置启用；`ethtool-full` 启用 netlink 和详细解码输出。

本机开发工具除 GCC、make 和 Python 外，还显式加入 `pkgconf`、`patch`、`diffutils`、`autoconf`、`automake`，来自 [官方 packages 仓库](https://downloads.openwrt.org/releases/25.12.5/packages/x86_64/packages/)，其依赖由 ImageBuilder 自动带入。

已显式列出原生 IPv6 所需的 `luci-proto-ipv6`（协议配置界面）、`odhcp6c`（WAN DHCPv6 / 前缀委派客户端）和 `odhcpd-ipv6only`（LAN DHCPv6 / RA 服务）。`luci` 原本会通过 `luci-light` 带入 IPv6 界面；官方 x86/64 默认包也已包含这两个 DHCPv6 组件，以及 `netifd`、`dnsmasq`、`firewall4`、`nftables`。当前配置将默认的 `dnsmasq` 替换为 `dnsmasq-full`，保留其余上述默认组件，并使用官方内核的 IPv6 支持。依据：[LuCI 依赖定义](https://github.com/openwrt/luci/blob/128a7812f4be233c5dd7f7466f534fd888785caf/collections/luci-light/Makefile)、[官方目标默认包](https://downloads.openwrt.org/releases/25.12.5/targets/x86/64/profiles.json)。

这里覆盖常规 IPv4/IPv6 双栈、DHCPv6-PD、SLAAC / RA、LAN DHCPv6 和 IPv6 防火墙。`odhcpd-ipv6only` 的名称表示其不负责 DHCPv4，DHCPv4 仍由 `dnsmasq-full` 提供。LAN DHCPv6 / RA 继续交给 `odhcpd-ipv6only`，无需因安装 `dnsmasq-full` 而改用 dnsmasq 承担此职责。6in4、DS-Lite 等特殊接入方式按实际线路再加对应后端；公网 IPv6 连通性仍需安装后结合运营商前缀、接口和防火墙配置验证。

LuCI 中文包按功能拆分，已明确加入以下五个：[官方 LuCI 包目录](https://downloads.openwrt.org/releases/25.12.5/packages/x86_64/luci/)。

| 中文包 | 覆盖界面 |
| --- | --- |
| `luci-i18n-base-zh-cn` | 基础、系统、状态、网络页面，以及 IPv6 / WireGuard 等协议页面 |
| `luci-i18n-firewall-zh-cn` | 防火墙（由 luci 间接安装） |
| `luci-i18n-package-manager-zh-cn` | 软件包管理器（由 luci 间接安装） |
| `luci-i18n-ksmbd-zh-cn` | KSMBD 文件共享 |
| `luci-i18n-dockerman-zh-cn` | Docker 管理 |

IPv6 和 WireGuard 的翻译归入 [LuCI base 翻译目录](https://github.com/openwrt/luci/blob/openwrt-25.12/modules/luci-base/po/zh_Hans/base.po)，无需另加同名协议语言包。以后新增 `luci-app-*` 时，应同时核对并加入对应的 `luci-i18n-*-zh-cn`，仅安装 base 中文包不会自动包含所有应用翻译。

需预置文件时按最终路径放入 `files/`，例如 `files/etc/config/example`。不要提交密码、私钥等敏感配置。默认目录为空。

## Fortran 构建

此任务根据 `Build.md` 重建补丁，而不是依赖未保存的本地 Makefile：

1. 检出锁定的官方 OpenWrt 源码，启用 cross GFortran 与 libgomp，构建工具链。
2. 编译动态链接的 Fortran/OpenMP/REAL(16) 测试，通过工具链自带的 musl 加载器和库目录运行，检查工具链头文件、runtime 和 `.mod` 文件。
3. 准备 SDK 所需 target/package 环境，导出 SDK，再解压为独立目录验证。
4. 在导出的 SDK 中构建 core runtime 与 native GCC 的两个附加包。
5. 按 APK 元数据确认包名、版本与架构，解包检查关键文件、开发链接、本机可执行文件架构及链接用 ELF 的节表。
6. 将五个 APK 与官方 GCC / binutils 安装到独立根目录，在 chroot 中使用本机编译器完成 Fortran/OpenMP/REAL(16) 与 C/OpenMP/Quadmath 测试，并检查动态依赖。

SDK 准备阶段会构建其所需内核和模块，目的是完成 SDK staging；这些文件不会进入第一个任务生成的固件。

导出 SDK 时直接通过 `BASE_FEED` 固定 OpenWrt 源码仓库和提交。不要只在 `target/sdk/install` 阶段追加 `CONFIG_BUILDBOT=y`：[官方工具链规则](https://github.com/openwrt/openwrt/blob/f0a60eee2fe051741c643ea6118718aae1ef17fb/toolchain/Makefile#L59-L69) 会在缺少或不匹配 `.ver_check` 时清理工具链及 target staging，使随后的内核构建报交叉 GCC 不存在。构建全过程应保持相同模式。

工具链构建后和 SDK 解压后均执行上述冒烟测试。测试使用 `toolchain-*/lib/libc.so --library-path toolchain-*/lib` 加载程序，并在日志中列出解析到的动态库；无需在 Ubuntu runner 的 `/lib` 安装 musl。此前强制 `-static` 的测试会在 libgfortran 回溯代码处出现 `_Unwind_GetIPInfo` / `_Unwind_Backtrace` 未定义引用，因此改用与交付的动态 runtime APK 一致的链接方式。这项检查验证动态链接与运行，未验证全静态链接能力。

交付的五个 APK 为：

```text
libgomp-*.apk
libquadmath1-*.apk
libgfortran-*.apk
gcc-fortran-dev-*.apk
gfortran-*.apk
```

`libquadmath` 是 Kconfig/recipe 名，APK 名是 `libquadmath1`。`finclude/`、链接用目标架构共享库及 musl 的 `libpthread.a` 兼容归档从定制 SDK 的 cross 工具链复制；头文件、Fortran/OpenMP/Quadmath 静态库和本机可执行文件来自 native GCC 安装目录。具体补丁见 `patches/fortran/README.md`。

`gcc-fortran-dev` / `gfortran` 的 r8 修复了 r7 的链接问题：原来的 `.so` 开发链接指向 `sstrip` 删除了 ELF 节表的运行库，文件虽存在，`ld` 却报 `file in wrong format`。现在在 GCC 私有目录提供保留节表的 `libgfortran.so`、`libgomp.so`，并将 `/usr/lib/` 的开发链接指向它们；Quadmath 复用官方 GCC 的链接用库。

r9 进一步在 GCC 私有目录补入 SDK 的 `libpthread.a`。musl 在线程实现上使用 libc，但 `-fopenmp` 引入的 `-lpthread` 仍需要这个空归档；两个编译器均可通过默认搜索路径找到它。三个 runtime APK 保持 r5，已有安装只需升级两个 `14.3.0-r9` 附加包。

安装测试用官方软件源下载 GCC 和依赖，记录所用仓库与已安装包版本到 `metadata/fortran-test-repositories.list`、`metadata/fortran-installed-packages.txt`；通过后生成 `metadata/fortran-install-audit.json`。测试关闭包安装脚本，在隔离目录内直接检查编译器工作情况，不添加 SDK 库搜索路径。执行完整 Fortran 构建需要 root 或可无交互调用的 sudo，以运行 chroot 测试。

保留 OpenWrt 官方 `gcc`/binutils 环境。构建过程会因依赖生成其他包，但 Fortran 任务只交付上述五个 APK，不交付修改后的 `gcc` 包。

## 反复构建第三方包

主配置 `config/build.toml` 指定加载哪些插件配置，路径均相对于仓库根目录：

```toml
[third_party]
config_files = [
  "config/third-party/msd-lite.toml",
  "config/third-party/vlmcsd.toml",
  "config/third-party/qbittorrent.toml",
  # "config/third-party/my-service.toml", # 创建该插件配置后可加入
]
```

每个 TOML 定义一个插件组，可以包含服务程序、LuCI、翻译等多个 recipe。添加或切换插件只需调整这个文件列表，其他插件 TOML 可以继续保留在仓库中。列表之外的文件不加载；`config_files = []` 可暂时关闭第三方构建配置，不影响固件和 Fortran 任务。

初始配置 `config/third-party/msd-lite.toml` 的组名为 `msd-lite`，包含：

- [ImmortalWrt packages 的 msd_lite recipe](https://github.com/immortalwrt/packages/tree/master/net/msd_lite)，其程序源码来自 [rozhuk-im/msd_lite](https://github.com/rozhuk-im/msd_lite)。
- [ImmortalWrt 的 luci-app-msd_lite](https://github.com/immortalwrt/luci/tree/master/applications/luci-app-msd_lite)，包含 LuCI 界面和 `luci-i18n-msd_lite-zh-cn`。

`vlmcsd` 使用同一组已锁定的 ImmortalWrt 来源：`net/vlmcsd` 服务配方、JavaScript 版 `applications/luci-app-vlmcsd` 和简体中文包，共三个 APK。没有沿用 mchome 的旧 Lua 界面。2026-10-05 核对的维护情况如下：

| 来源 | 核查结果 |
| --- | --- |
| [mchome 原仓库](https://github.com/mchome/luci-app-vlmcsd/commit/530a6ee0f07522c9540dc09c7559f0486c4c4288) | 最后提交为 2017-03-12 |
| [ImmortalWrt](https://github.com/immortalwrt/luci/commit/526f724a4325d03ddbdab72aeb8d11b9ab2ef0f4) | 2025-02-13 改为 JavaScript，随后修复配置文件加载；当前选用此来源，已有运行状态显示 |
| [Lean / coolsnowwolf](https://github.com/coolsnowwolf/luci/commit/28190ed6720bcd958930ff811e0997635519d9a8) | `openwrt-25.12` 分支有 JavaScript 版，2026-04-23 调整开关默认值；`master` 仍是旧 Lua 版 |
| OpenWrt 官方 / iStoreOS | 官方 LuCI 仓库、iStoreOS 当前 `jjm2473/luci` 的 `istoreos-24.10` 分支中未找到该应用 |

这里更新的是 LuCI 与 OpenWrt 服务集成；ImmortalWrt 服务配方仍使用 Wind4/vlmcsd 的 `2020-03-30` 源码，并包含后续打包与服务修复。

`qbittorrent` 使用 [sbwml/luci-app-qbittorrent](https://github.com/sbwml/luci-app-qbittorrent/tree/739efe95cf38cdfa956cd1c38ddd9f52358a8c6a)，固定为 `739efe95cf38cdfa956cd1c38ddd9f52358a8c6a`：qBittorrent **5.2.4**、Qt **6.12.0**、libtorrent **2.0.15**。一起导入 `qt6base`、`qt6tools`、`rblibtorrent`、`qbittorrent` 和 LuCI 五个配方。必需产物共十个 APK：主程序、LuCI、中文包、`rblibtorrent2.0`、四个 Qt 库（Core / Network / Sql / Xml）及 OpenSSL / SQLite 两个 Qt 插件。Qt 运行库属于本组主产物，需与程序配套安装；其余官方依赖由官方 APK 源提供。

Qt6 同时需要宿主和目标构建，qBittorrent 组会明显比前两个插件慢。首次测试建议单独运行 `targets=qbittorrent`、`jobs=2`。`targets=vlmcsd,qbittorrent` 可只编译本次新增的两组；留空则编译当前启用的三组。

只导入配置指定的 recipe 目录。编译环境、依赖 feeds 和 LuCI 构建框架仍使用对应版本的官方 SDK。脚本兼容相对和官方绝对 `luci.mk` include，保留配方显式声明的包版本，并用锁定提交生成翻译版本和缺省包版本。

添加新插件时新建 `config/third-party/<插件名>.toml`，并将路径加入主配置的 `config_files`。各文件独立声明自己使用的 `[[sources]]`，填写 recipe 仓库 URL 与供更新锁文件使用的 `ref`。多个文件中同名来源的 URL、ref 必须一致，加载时自动去重；若需使用同仓库的不同分支，应使用不同来源名。

每个插件按 `recipes` 的顺序编译；先放服务端程序，再放 LuCI。下面是一个完整的插件配置格式示例，路径和包名应替换为实际值：

```toml
schema_version = 1
name = "my-service"
enabled = false

[[sources]]
name = "immortal-packages"
url = "https://github.com/immortalwrt/packages.git"
ref = "master"

[[sources]]
name = "immortal-luci"
url = "https://github.com/immortalwrt/luci.git"
ref = "master"

[[recipes]]
source = "immortal-packages"
path = "net/my-service"
select = ["my-service"]
expected_apk_names = ["my-service"]

[[recipes]]
source = "immortal-luci"
path = "applications/luci-app-my-service"
luci = true
languages = ["zh_Hans"]
select = ["luci-app-my-service", "luci-i18n-my-service-zh-cn"]
expected_apk_names = ["luci-app-my-service", "luci-i18n-my-service-zh-cn"]
```

`select` 对应 `CONFIG_PACKAGE_*`，`expected_apk_names` 使用最终 APK 内部包名，两者可能不同。LuCI 翻译是隐藏配置项，还需通过 `languages` 指定语言；简体中文是 `zh_Hans`，对应包名后缀 `zh-cn`。

仅供 runner 使用的工具配方可设置 `host_only = true`，并将 `select` 和 `expected_apk_names` 都设为 `[]`，例如 qBittorrent 的 `qt6tools`。脚本对它执行 `host/compile`，不要求产出目标 APK；其他配方仍必须声明非空的包选择及产物列表。

脚本将语言开关写为 `CONFIG_LUCI_LANG_zh_Hans=y`，插件包仍选择 `m`。官方 SDK 的 `Config-build.in` 会把原构建中未启用的语言保存为布尔选项，写 `m` 会被 Kconfig 拒绝，导致中文包丢失。配置完成后会同时检查语言开关和所选 APK，并将解析后的配置保存为 `metadata/sdk.config`；即使必需项检查失败，也能从 Artifact 中查看该文件。

workflow 的 `targets` 使用 TOML 内的 `name`，例如 `msd-lite,my-service`；留空时按 `config_files` 顺序构建其中 `enabled = true` 的插件。`enabled = false` 的插件仍可显式选中，但其 TOML 必须已经列入 `config_files`。因此也可以一次登记所有常用插件，以后只改 workflow 输入来选择本次任务。

同一批次共享的 recipe 只导入、编译一次，所选包和语言取并集。来自不同来源却使用相同目录名的 recipe 会提前报错。`--plan` 输出本次选择的插件名称和配置文件，便于运行前确认。

这里的来源必须包含 **OpenWrt package Makefile**；原始 C/C++ 项目需先准备 recipe。若自定义依赖也不在官方 feeds，需要把它的 recipe 加入同组。recipe 应可独立复制，不能隐式依赖源仓库里未导入的兄弟目录。当前入口面向用户态 APK，未实现第三方 kmod 与官方 kernel ABI 的校验。

第三个 workflow 缓存已校验的官方 SDK 下载和 OpenWrt 的 `dl` 源码下载，不缓存编译目录。每次重新解压 SDK，避免不同插件批次之间混入旧构建结果。

## 固定来源与升级

正常构建只使用 `config/sources.lock.json` 中的完整提交和 SHA256，不追随 `master`。官方 feeds 固定为该 release 的 `feeds.buildinfo` 中的提交。更新第三方 recipe 时，在有 Python 3.11+、Git 和网络的机器运行：

```bash
python3 scripts/update-lock.py --third-party-only
python3 scripts/build.py third-party --plan --targets msd-lite
```

检查锁文件差异后，将配置和锁文件一起提交。仅新增已有来源中的插件配置，无需刷新来源提交。更新脚本与构建使用同一份 `config_files` 加载逻辑，只刷新已加载来源；暂时未加载来源的锁定记录会保留，方便以后切换回来。共用同一来源名的插件也共用其锁定提交，更新该来源会同时影响这些插件。

升级 OpenWrt 时修改 `config/build.toml` 中的 `release`，再运行：

```bash
python3 scripts/update-lock.py
python3 scripts/build.py validate
```

完整更新会重新获取下载哈希、官方源码/feeds 提交和第三方来源提交。GCC/OpenWrt 版本变化可能影响补丁上下文及安装布局，需要复核 `patches/fortran/`；构建会先执行 `git apply --check`，不强行套用失败补丁。目前目标固定为 x86/64 generic，不支持仅改配置切换架构。

固定源码与下载包不等于所有产物字节完全可复现：runner/apt 环境、上游二次下载及构建时间仍可能变化。实际配置、来源和包清单随产物保存。

## 产物与安装

`dist/<任务>/` 包含主产物、`sha256sums`、`metadata/` 和 `logs/build.log`。第三方构建额外生成的依赖包位于 `build-dependencies/`；先用官方源满足依赖，仅按实际需要选用该目录的包，不要整目录批量安装。

在解压后的产物根目录校验：

```bash
sha256sum -c sha256sums
```

目前不维护 APK 签名密钥或自建软件源。在对应版本的 OpenWrt 上，将所需 APK 复制到同一个目录后安装，例如：

```sh
apk update
apk add --allow-untrusted ./libgomp-*.apk ./libquadmath1-*.apk \
  ./libgfortran-*.apk ./gcc-fortran-dev-*.apk ./gfortran-*.apk
```

第三方包组按该组主产物的实际文件名一起安装：msd_lite 和 vlmcsd 各三个 APK，qBittorrent 十个 APK（包含配套 Qt6 / libtorrent 运行库）。不要把其他组或 `build-dependencies/` 整目录混入安装命令。首次安装后需在 LuCI 中配置服务；qBittorrent 的 profile 与下载目录建议放到数据盘。

Fortran 产物还附带本机验证程序。将 `tests/` 一起复制到 OpenWrt，安装后执行：

```sh
sh tests/run-on-openwrt.sh
```

此测试先检查 `gfortran` / `gcc` 能找到带 `.dynsym` 节的开发库及有效的 `libpthread.a`，再使用默认库搜索路径编译、运行 OpenMP 与 Quadmath 示例，并确认程序动态依赖 Fortran / OpenMP / Quadmath 运行库。runner 在隔离安装环境中执行同一测试；它与 cross 工具链测试分别验证 SDK 和最终 APK 两个阶段。

## 本地检查与构建

离线配置检查可在 Windows、Linux 等环境执行（Python 3.11+）：

```bash
python3 scripts/build.py validate
python3 scripts/build.py firmware --plan
python3 scripts/build.py fortran --plan
python3 scripts/build.py third-party --plan --targets msd-lite
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

完整构建需要 Linux x86_64，建议 Ubuntu 24.04。示例：

```bash
bash scripts/prepare-runner.sh third-party
bash scripts/check.sh
bash scripts/build-third-party.sh --targets msd-lite --jobs 2
```

其他入口为 `scripts/build-firmware.sh` 和 `scripts/build-fortran.sh`。准备脚本会安装依赖；仅在 GitHub 托管 runner 上清理预装且本任务不用的 SDK。构建入口拒绝复用已有 `work/<任务>/` 和 `dist/<任务>/`，本地重跑前应保存旧结果并移走对应任务目录。

本地已做 workflow、Shell、Python 和补丁应用检查。Windows 会跳过依赖 Linux ELF 工具的打包测试；这些测试在每个 workflow 中执行。原始手工步骤的成功记录见 `Build.md`，本仓库自动化仍需首次 GitHub 构建和 OpenWrt 本机安装验证。
