# 编译 OpenWrt

> 本文保留原始本地编译记录。GitHub Actions 的当前用法与配置见 [README.md](README.md)：三个独立任务分别生成基础固件、定制 SDK + Fortran APK、基于官方 SDK 的第三方 APK。SDK 产物按需安装，不进入固件；固件分区大小以 `config/build.toml` 为准。

## OpenWrt 定制与维护架构

我们的 OpenWrt 采用 **三层式定制架构**，目标是在保留官方内核和软件源兼容性的同时，满足本机开发环境和第三方组件需求，并尽量降低后续升级维护成本。

### 第一层：ImageBuilder 定制基础固件

使用对应 OpenWrt 正式版本的官方 **ImageBuilder** 生成基础镜像，不自行编译 Linux kernel，从而保持与官方 kernel/kmod ABI 完全一致。

基础固件主要包含：

- x86/64、UEFI、ext4 根文件系统
- 8 GiB rootfs
- LuCI + uhttpd
- nginx-full
- nftables / firewall4
- WireGuard
- Intel I226-V 所需网络支持
- Docker + Dockerman
- KSMBD
- Python
- GCC / G++ 等本机开发环境
- 常用基础工具及必要内核模块

其中部分自行编译的用户态 APK，例如 GFortran，可先通过第三层 SDK 生成.

**原则：基础固件只负责稳定的系统底座和长期需要的核心能力，不自行修改官方 kernel。**

### 第二层：官方软件源直接安装

凡是 OpenWrt 官方仓库已经提供的软件，原则上不再编入基础镜像，而是在系统安装完成后通过：

```bash
apk update
apk add <package>
```

按需安装。

典型包括：

- adblock
- DDNS
- aria2
- frpc / frps
- minidlna
- p910nd
- Wake-on-LAN
- UPnP
- rclone
- cloudflared
- socat
- udpxy
- 其他官方用户态软件
- 以后临时需要的官方 `kmod-*`

由于基础系统保持官方 kernel ABI，因此可以继续直接使用官方 kmod 软件源。

**原则：官方已有的包尽量直接使用官方仓库，减少自行维护。**

### 第三层：SDK 编译自定义组件和第三方插件

对于官方仓库没有提供，或者需要修改编译选项的软件，使用与当前 OpenWrt release 完全对应的官方 **SDK** 单独编译 APK。

主要包括：

- GFortran / libgfortran / libquadmath / libgomp
- Python 开发文件 `python3-dev`
- msd_lite
- qBittorrent
- Passwall / Passwall2
- ShadowsocksR Plus+
- vlmcsd
- 其他第三方 OpenWrt 软件或自行开发的程序

SDK 编译结果可以：

1. 直接安装到运行中的 OpenWrt；
2. 加入自己的 APK 软件源；
3. 在下一次生成固件时交给 ImageBuilder 直接集成。

**原则：只自行维护官方没有的用户态组件，不自行维护 kernel。**

### 总体结构

```text
                    OpenWrt 官方 Release
                           │
            ┌──────────────┴──────────────┐
            │                             │
      官方 ImageBuilder               官方 SDK
            │                             │
            │                      编译自定义 APK
            │                             │
            └──────────────┬──────────────┘
                           │
                    第一层：基础固件
                           │
              ┌────────────┴────────────┐
              │                         │
      第二层：官方 APK            第三层：自维护 APK
        apk install                  SDK build
```

最终目标是形成一套：

> **官方 kernel + 官方软件生态 + 自维护少量用户态扩展**

的 OpenWrt 系统。

这样既能保持官方 `kmod-*` 的兼容性，又能获得 GFortran、qBittorrent、msd_lite 等官方未提供的功能，同时把以后升级到新的 OpenWrt release 的维护成本降到最低。

## 使用 ImageBuilder 生成基础固件

### 下载官方 ImageBuilder

```bash
cd /cdata/build-openwrt

wget \
https://downloads.openwrt.org/releases/25.12.5/targets/x86/64/openwrt-imagebuilder-25.12.5-x86-64.Linux-x86_64.tar.zst

tar --zstd -xf \
openwrt-imagebuilder-25.12.5-x86-64.Linux-x86_64.tar.zst

cd openwrt-imagebuilder-25.12.5-x86-64.Linux-x86_64
```

使用：

```text
PROFILE=generic
```

基础固件主要包含：

```text
LuCI + uhttpd
nginx-full

firewall4 / nftables
WireGuard

kmod-igc                  # Intel I226-V
intel-microcode

KSMBD
Docker / dockerd
luci-app-dockerman

Python3 + pip + setuptools

gcc
make
bash
git
curl

kmod-tun
kmod-nft-socket
kmod-nft-tproxy
kmod-fuse
kmod-usb-printer
```

其中：

```text
nginx   默认关闭
dockerd 默认关闭
```

Docker 后续数据目录放独立磁盘，例如：

```text
/opt/docker
```

---

### 建议使用 `packages.txt`

例如：

```text
luci
luci-ssl-openssl
luci-i18n-base-zh-cn
uhttpd
uhttpd-mod-ubus

nginx-full

kmod-igc
intel-microcode
ethtool

wireguard-tools
kmod-wireguard
luci-proto-wireguard

kmod-tun
kmod-nft-socket
kmod-nft-tproxy

block-mount
e2fsprogs
dosfstools
kmod-fuse

ksmbd-server
luci-app-ksmbd

kmod-usb-printer

docker
dockerd
luci-app-dockerman

python3
python3-pip
python3-setuptools

gcc
make

bash
git
curl
ca-bundle
ca-certificates
```

生成变量：

```bash
PACKAGES="$(grep -v '^[[:space:]]*#' packages.txt \
    | grep -v '^[[:space:]]*$' \
    | tr '\n' ' ')"
```

先检查：

```bash
make manifest \
    PROFILE=generic \
    PACKAGES="$PACKAGES" \
    STRIP_ABI=1 \
    > manifest.txt
```

### 生成镜像

```bash
make image \
    PROFILE=generic \
    PACKAGES="$PACKAGES" \
    ROOTFS_PARTSIZE=8192 \
    DISABLED_SERVICES="nginx dockerd" \
    EXTRA_IMAGE_NAME="econwang-charls"
```

最终使用：

```text
openwrt-25.12.5-econwang-charls-x86-64-generic-ext4-combined-efi.img.gz
```

这一方案不重新编译 kernel，因此继续保持官方：

```text
kernel 6.12.94
ABI/vermagic:
a7bc15f451f9652701ba04af9cfb0b95
```

所以系统以后仍可直接：

```bash
apk add kmod-xxx
```

安装官方内核模块。

## 构建支持 GFortran/OpenMP 的 SDK

官方 OpenWrt 25.12.5 SDK 没有 cross `gfortran`，因此无法直接构建 native GFortran。

我们的做法是从官方源码构建一个 **Fortran-enabled SDK**。

### 获取源码

```bash
cd /cdata/build-openwrt

git clone \
    --branch v25.12.5 \
    --depth 1 \
    https://github.com/openwrt/openwrt.git \
    openwrt-25.12.5-fortran

cd openwrt-25.12.5-fortran

./scripts/feeds update -a
./scripts/feeds install -a
```

### 开启 GFortran

配置：

```text
CONFIG_TARGET_x86=y
CONFIG_TARGET_x86_64=y
CONFIG_TARGET_x86_64_DEVICE_generic=y

CONFIG_DEVEL=y
CONFIG_TOOLCHAINOPTS=y

CONFIG_INSTALL_GFORTRAN=y
CONFIG_SDK=y
```

然后：

```bash
make defconfig
```

---

### 开启 OpenMP runtime

修改：

```text
toolchain/gcc/common.mk
```

将：

```make
--disable-libgomp
```

改成：

```make
--enable-libgomp
```

`libquadmath` 不需要额外处理。

### 构建 toolchain

```bash
make -j"$(nproc)" toolchain/install V=s
```

确认：

```bash
TC="$(find staging_dir -maxdepth 1 -type d \
    -name 'toolchain-x86_64_gcc-14.3.0_musl' \
    -print -quit)"
```

应存在：

```text
bin/x86_64-openwrt-linux-musl-gfortran

lib/libgfortran.so*
lib/libgomp.so*
lib/libquadmath.so*

.../include/omp.h
.../include/quadmath.h
```

测试：

```bash
"$TC/bin/x86_64-openwrt-linux-musl-gfortran" --version
```

应得到：

```text
GNU Fortran ... 14.3.0
```

### 完成 SDK 所需 target/package 环境

实际成功的顺序是：

```bash
make -j"$(nproc)" package/compile V=s
make -j1 package/install V=s
make -j"$(nproc)" target/sdk/install V=s
```

如果 kernel package 出现缺少 `.ko`，只重建 kernel：

```bash
make defconfig
make target/linux/clean
make -j"$(nproc)" target/linux/compile V=s
```

不要执行：

```text
make clean
make dirclean
make targetclean
```

以免删除已经成功构建的 Fortran toolchain。

最终得到自维护 SDK，例如：

```text
openwrt-sdk-25.12.5-x86-64-gfortran-openmp.tar.zst
```

## 使用 SDK 编译 GFortran

最终采用的结构是：

```text
OpenWrt core packages
├── libgomp
├── libquadmath1
└── libgfortran

我们维护
├── gcc-fortran-dev
└── gfortran
```

而不是自行维护三个 runtime package。

### OpenWrt core runtime

在 SDK 中选择：

```text
CONFIG_PACKAGE_libgomp=m
CONFIG_PACKAGE_libquadmath=m
CONFIG_PACKAGE_libgfortran=m
```

OpenWrt 25.12.5 的 `package/toolchain/Makefile` 对 internal toolchain 缺少 `libgomp/install`，因此补：

```make
define Package/libgomp/install
    $(INSTALL_DIR) $(1)/lib
    $(CP) $(TOOLCHAIN_DIR)/lib/libgomp.so* $(1)/lib/
endef
```

然后：

```bash
make package/toolchain/clean
make package/toolchain/compile V=s
```

得到：

```text
libgomp-14.3.0-r5.apk
libquadmath1-14.3.0-r5.apk
libgfortran-14.3.0-r5.apk
```

### 编译 native `gcc-fortran-dev` 和 `gfortran`

首先：

```bash
./scripts/feeds update base packages
```

保证 native GCC 所需的：

```text
binutils
libtool
gcc
```

recipe 可用。

恢复官方：

```text
feeds/packages/devel/gcc/Makefile
```

然后只做两类修改。

### native GCC 编译选项

```make
TARGET_LANGUAGES:="c,c++,fortran"
```

并将：

```make
--disable-libgomp
--disable-libquadmath
```

改成：

```make
--enable-libgomp
--enable-libquadmath
```

### 增加两个 package

#### `gcc-fortran-dev`

依赖：

```text
gcc
libgomp
libquadmath
libgfortran
```

主要安装：

```text
omp.h
openacc.h

quadmath.h
quadmath_weak.h

libgomp.spec
libgfortran.spec

libgomp.a
libquadmath.a
libgfortran.a
libcaf_single.a

/usr/lib/libgomp.so
/usr/lib/libquadmath.so
/usr/lib/libgfortran.so
```

#### `gfortran`

依赖：

```text
gcc
gcc-fortran-dev
libgomp
libquadmath
libgfortran
```

主要安装：

```text
/usr/bin/gfortran
/usr/bin/x86_64-openwrt-linux-musl-gfortran

/usr/lib/gcc/x86_64-openwrt-linux-musl/14.3.0/f951

finclude/
├── ieee_arithmetic.mod
├── ieee_exceptions.mod
├── ieee_features.mod
├── omp_lib.f90
├── omp_lib.h
├── omp_lib.mod
├── omp_lib_kinds.mod
├── openacc.f90
├── openacc.mod
├── openacc_kinds.mod
└── openacc_lib.h

include/
└── ISO_Fortran_binding.h
```

这里 `finclude` 直接从已经验证正常的 Fortran-enabled SDK toolchain 复制，避免 native GCC 14.3.0 构建遗漏 `omp_lib.mod`。

### 编译

配置：

```text
CONFIG_PACKAGE_libgomp=m
CONFIG_PACKAGE_libquadmath=m
CONFIG_PACKAGE_libgfortran=m
CONFIG_PACKAGE_gcc-fortran-dev=m
CONFIG_PACKAGE_gfortran=m
```

然后：

```bash
make package/feeds/packages/gcc/clean

make -j"$(nproc)" \
    package/feeds/packages/gcc/compile \
    V=s
```

最终生成：

```text
OpenWrt core:
  libgomp-14.3.0-r5.apk
  libquadmath1-14.3.0-r5.apk
  libgfortran-14.3.0-r5.apk

自维护:
  gcc-fortran-dev-14.3.0-r7.apk
  gfortran-14.3.0-r7.apk
```

### 最终安装关系

OpenWrt 上已有：

```text
官方 gcc
官方 g++
官方 binutils
```

额外安装五个 APK：

```bash
apk add --allow-untrusted \
    libgomp-14.3.0-r5.apk \
    libquadmath1-14.3.0-r5.apk \
    libgfortran-14.3.0-r5.apk \
    gcc-fortran-dev-14.3.0-r7.apk \
    gfortran-14.3.0-r7.apk
```

最终形成：

```text
OpenWrt native development environment

官方：
├── gcc
├── g++
└── binutils

OpenWrt core：
├── libgomp
├── libquadmath1
└── libgfortran

自维护：
├── gcc-fortran-dev
└── gfortran
```

这套结构既保留了 **官方 kernel/kmod 兼容性**，又获得了完整的：

```text
C / C++
Fortran
OpenMP
Quadmath
OpenACC Fortran interfaces
```

本机编译环境。

至此，前三步的正式构建链已经打通：

```text
ImageBuilder
     ↓
稳定的官方 kernel 基础固件

Fortran-enabled SDK
     ↓
可重复的第三方/自定义编译环境

SDK packages
     ↓
GFortran + OpenMP + Quadmath
```

后续 `msd_lite`、qBittorrent 等第三层组件都可以继续沿用这个 SDK 体系。
