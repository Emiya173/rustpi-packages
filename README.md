# Emiya rustpi binary repository

面向 Orange Pi 5 Plus 的 Arch Linux ARM 签名二进制源，由 GitHub Actions 构建。
板子只需使用 `paru` 或 `sudo pacman -Syu`，无需编译。

| 包 | 维护内容 |
| --- | --- |
| `linux-aarch64-emiya-rustpi` | 跟随 ALARM 的内核与配置，附加 USB-C DisplayPort 补丁 |
| `linux-aarch64-emiya-rustpi-headers` | 同次构建的 ARM64 headers 与构建工具 |
| `linux-aarch64-emiya-rustpi-rknpu` | 同次构建、严格匹配内核版本的 RKNN 驱动 |
| `ffmpeg` | ALARM FFmpeg 加 V4L2 Request 和 NV15 下载补丁，保留原功能 |
| `jellyfin-ffmpeg-system-rustpi` | Jellyfin 调用系统 FFmpeg 硬解的参数适配器 |
| `emiya-rustpi-keyring` | 软件源公钥 |

## 更新方式

每六小时检查 ALARM 内核和 FFmpeg 打包源码；输入变化时在 GitHub ARM64
runner 的隔离 ALARM 根目录中原生构建，不使用 Docker，也不使用 rustpi 的
系统库快照。内核、headers、RKNPU 属于同一组，发布前检查版本、依赖、ARM64
工具、DTB 和外部模块构建。FFmpeg 检查硬解后端是否编入，以及软件编码能力。

补丁无法应用、关键配置缺失、编译或检查失败时不发布，旧源继续可用。
DP、V4L2 Request 和 RKNPU 补丁固定在已验证的来源；上游 API 出现不兼容
变化时仍需维护补丁，CI 不会自动猜测如何修改驱动。

包和数据库均使用专用 Ed25519 签名。先上传完整 draft release，再将它公开并
设为 latest；客户端不会看到只发布了一半的内核组。同版本的已发布二进制不会
被替换；每个包保留两个旧版本供缓存下载，历史 release 也保留。

初始 release 使用这台机器已经通过硬件验证的本地构建。后续 Actions 能验证
构建和软件接口，不能代替实机验证 USB-C DP、VPU 和 NPU。软件源不会自动
登录机器、升级系统、重启或中断录音。

## 接入

公钥指纹：`936E1ED81F1B219DA3F4D2260BBC591DA9D66626`。

将 `keys/emiya-rustpi.asc` 与 `client/install-repository.sh` 放在同一目录，
检查脚本后以 root 执行。它验证仓库签名，安装 keyring，在 `[core]` 前加入：

```ini
[emiya-rustpi]
SigLevel = Required
Server = https://github.com/Emiya173/rustpi-packages/releases/latest/download
```

源的优先级让定制 FFmpeg 不会被普通仓库版本覆盖。新版适配包还要求
`ffmpeg-rustpi` 虚拟依赖。随后正常执行 `paru`；内核升级后在合适的时间重启。
不要单独更新内核三件套中的一个包，也不要绕过依赖或禁用签名检查。

## 维护

`sources.lock.json` 保存初始源码来源；每轮 Actions 的 recipes artifact 保存
那次使用的完整源码锁定、PKGBUILD 和补丁。release 的签名 `manifest.json`
记录实际发布版本、来源、摘要和构建组。

手动运行 **Build and publish repository**：`force` 强制构建，`publish=false`
只验证不发布。PR 只能构建，拿不到发布凭据。构建任务只读仓库，签名密钥只在
独立发布任务中可用。签名私钥不在仓库；使用 GitHub Secrets
`REPO_SIGNING_KEY`、`REPO_SIGNING_PASSPHRASE`。CI 只持有签名子密钥，
主密钥保留在维护者本地；签名子密钥有效期两年。

修改同一上游版本的内核补丁或 NPU 提交时，提高 `ci/pins.json` 的
`kernel_revision`；修改 FFmpeg 补丁时提高 `ffmpeg_revision`；修改适配器或
keyring 时提高其 PKGBUILD 版本。发布器拒绝未经版本递增的配方替换。

本地维护工具通过 `nix develop` 提供。真正的 CI 构建在 GitHub 上运行，
不会在本机启动容器来模拟 Actions。仓库脚本采用 MIT 许可；Linux、FFmpeg、
各补丁及上游代码保留原作者和原许可证。
