# Openwrt Dev

功能需求

- 路由基本功能
- full nginx
- uhttpd用于luci界面
- wireguard
- 完整的编译环境，make，gcc, gfortran等
- python环境
- 完整的luci界面
- open-box <https://github.com/liandu2024/Open-Box>
- ShadowSocksR Plus+ <https://github.com/fw876/helloworld>
- passwall
- 打印服务器
- kms服务器
- adblock
- 动态dns
- aria2
- frp服务端和客户端
- minidlna
- Ksmbd网络共享
- 组播转换msd_lite
- 网络唤醒服务
- upnp
- qbittorrent
- rclone
- Cloudflare 零信任隧道
- socat

## gfortran

OpenWrt core 本身已经正式定义了：
libgfortran
libgomp
libquadmath

例如 libgfortran 会直接从 toolchain 中提取 libgfortran.so.*，libquadmath 和 libgomp 也有标准 package definition。GitHub
所以以后我们完全可以把结构进一步正规化成：
OpenWrt core packages
├── libgomp
├── libquadmath
└── libgfortran

我们的 package
├── GCC OpenMP/Quadmath 开发文件
└── gfortran frontend

这会更符合 OpenWrt 原生 package 体系。
