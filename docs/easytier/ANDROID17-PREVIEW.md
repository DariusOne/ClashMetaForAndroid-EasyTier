# Android 17 预览版交付（2026-10-29）

本页保留旧单设备交付。2026-10-30 用户改为按两台已验收真机交付，当前入口为
[双真机预览说明](TWO-DEVICE-PREVIEW.md)。旧包、APK 与安装器不修改。

按本次选择，先面向 **Android 17 / API 37、arm64 真机**交付有限功能预览包。
安装包与已经在用户手机验收的 APK 完全相同，不重新编译、不修改签名或运行行为。
它是独立应用 `com.github.metacubex.clash.meshprototype.meta`，桌面名称仍为
`CMFA + EasyTier Prototype`，可与原 CMFA、EasyTier 共存，但 Android 同一用户下仍只能启用一个 VPN。

这次交付不等于原整合计划全部完成。当前是原生 IPv4 数据通道预览，正式配置界面尚未完成；
Clash YAML 在应用内导入，EasyTier TOML 通过随包的 USB 工具单独导入。
PR 保留草稿，不合并、不发布为通用正式版。

## 支持范围与 APK 身份

| 项目 | 本次交付 |
| --- | --- |
| 验收平台 | 已测试的一台 Android 17 / API 37 arm64 手机 |
| 安装工具 | 只接受 API 37、arm64-v8a 真机；其他 API、架构或模拟器停止 |
| APK 源码 | `39ef3fe5c8381dc2c25e0422cca9712866060f4e` |
| 测试工具源码 | `ac2d52344005ab891098f286ec8940f28f1673d9` |
| APK SHA-256 | `f6560523b63b9b9a437cd7b20be643dea47be7da538c6c7e86da254e28cf404a` |
| APK manifest | 原样保留 `minSdk=31`、`targetSdk=35` |

**安装清单的最低版本没有改成 37。** 这是为了交付已经实测的同一文件，保留其 Android
兼容行为；交付支持范围由安装工具及本说明限制。手动旁加载虽然可能被旧系统允许，
不代表旧系统受支持。Android 12/15 已有接口交接反例，不应在这些平台使用本预览。
未来 Android 版本、其他机型及 x86_64 均需另行验收，不能从一次手机测试推断兼容。
Android 官方分别解释了 [minSdk 与 targetSdk](https://developer.android.com/guide/topics/manifest/uses-sdk-element)，
两者不能与“已通过哪些设备测试”混为一谈。

## 包内文件与安装

需要电脑上的 Python 3.11 或以上，以及 Android Platform Tools 的 `adb`。
本包不下载或捆绑来源不明的 ADB，不包含用户订阅、组网密钥、测试网络或调试签名私钥。

在解压目录运行，默认只离线核对 APK，不连接手机：

```text
python android17_preview.py
```

连接已允许 USB 调试的 Android 17 手机后：

```text
python android17_preview.py --device-check
python android17_preview.py --install
```

若 ADB 不在 PATH，可在以上命令中加 `--adb "ADB 可执行文件的完整路径"`。
有多台已授权设备时，必须用 `--serial` 指定，不会擅自选设备。
安装仅执行独立原型包的 `install -r`，不启动 VPN、不导入配置、不改原 CMFA/EasyTier。
如果签名不匹配会停止，工具不会卸载、清数据或覆盖原应用。原型中已有重要数据时应先自行导出，
不要为解决签名冲突直接卸载。

## 分别导入两个配置

1. 在 **CMFA + EasyTier Prototype** 的“配置”中导入自己的 Clash/Mihomo YAML，并选中它。
2. 在电脑准备独立的 EasyTier TOML 副本。网络名、网络密钥、已知节点地址使用自己的组网配置，
   不要发到聊天。给手机分配未占用的虚拟地址；首版只验收了虚拟地址处于同一子网的 IPv4 布局。
3. 停止原型 VPN，再从系统应用信息页“强行停止”**独立原型**。不要停止或清理原应用的数据。
4. 通过以下工具把明确指定的 TOML 送入原型私有目录；内容通过标准输入传递，不进入命令行：

```text
python prepare-packet-harness.py --adb "ADB 路径" --serial "设备序列号" --profile "你的 TOML 完整路径"
```

5. 打开独立原型，从正常的 VPN 开关启动，并亲自确认 Android 的 VPN 授权。
   使用组网内的虚拟 IPv4 地址访问已经配置好的对端。

TOML 的 `[flags]` 需使用原生包通道，不能设置 `no_tun=true`、`use_smoltcp=true`；
MTU 限定 1280–1380，可使用 `mtu=1380`。主机管理入口、文件导入、默认路由、出口节点、
手机端发布代理网段等配置被原生校验器拒绝。不要照搬电脑的完整系统管理配置。
原型失败时使用固定错误码，不应把含网络密钥的 TOML 或原始日志公开上传。

当前原生组网只处理其管理的目的地址，其他私网及公网仍遵循 Clash 的规则。
不要为了组网把所有内网地址统一改成 DIRECT。应用内“系统 HTTP 代理”须保持关闭：
本预览验收的是 Android VPN 的原生 IP 包路径，HTTP/SOCKS 入口尚未接入相同组网分流。
不要求启用系统始终开启 VPN、锁定模式或修改原应用的分应用设置。

## 实际测试与限制

| 已完成项目 | 结果 |
| --- | --- |
| 真实接口替换 | 3/3 |
| 普通应用 TCP/UDP、Java NIO 与 AF_INET 探针 | 4,159 次尝试、4,140 次回复 |
| 对端错误来源、直接路径旁路 | 均为 0 |
| 测试前后直接路径阳性对照 | 四种模式均通过 |
| 双向 TCP / UDP / ICMP | 各 5/5 |
| 双向 4 KiB ICMP | 各 5/5 |

19 次请求未得到回复；通过的是该有限窗口内未观察到错误出口，并非“零丢包”或任意场景无缝的保证。
本轮普通应用测试使用 USB 承载的 TCP 外层连接；其他历史的 Wi-Fi TCP、规则和发现测试
应分别按其 APK、测试条件理解，不能合并声称所有传输已验收。

以下仍未完成或存在已知问题：

- 不同虚拟子网的基础连接曾失败，原因未定位，不能按已支持交付。
- 正式的 EasyTier 配置编辑、模式切换、冲突处理界面以及手机生成器输出。
- DNS/Fake-IP 解析后的组网分流、HTTP/SOCKS 入口。
- 完整 IPv6、UDP/STUN/QUIC 外层传输、蜂窝网络、DHCP/动态路由及长时间运行验收。
- 与原版 CMFA/EasyTier 的同条件接口替换对照。

详见 [真机证据](PHYSICAL-COMPARISON-20261029.md)。最新 `ac2d523` 的 CI 已完成：
[普通构建成功](https://github.com/DariusOne/ClashMetaForAndroid-EasyTier/actions/runs/40841763377)，
[原生构建及主机测试成功，但 API 31 切换失败](https://github.com/DariusOne/ClashMetaForAndroid-EasyTier/actions/runs/40841757177)。
本次不交付这份后续 CI 的新 APK，也不把 Android 12 的失败改标为通过。

## 退出与回退

在独立原型内停止 VPN，再打开原 CMFA 或 EasyTier。原应用的配置、数据和系统设置未被交付工具修改。
确认不再需要原型内的资料后，可从 Android 设置卸载这个独立原型；原应用不会随之删除。

## 源码与许可

交付包包含许可证与版本清单。完整对应源码及锁定子模块见
[APK 对应提交](https://github.com/DariusOne/ClashMetaForAndroid-EasyTier/tree/39ef3fe5c8381dc2c25e0422cca9712866060f4e)，
测试证据、安装工具和后续改动位于 `feat/easytier-native` 分支。
这份调试 APK 没有稳定发布签名承诺，后续不同 CI 签名可能无法直接覆盖安装；安装工具不会绕过签名检查。
