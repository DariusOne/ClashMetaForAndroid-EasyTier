# 两台真机预览版交付（2026-10-30）

按用户选择，本轮以两台已完成有限窗口验收的真机作为预览交付依据。Android 12/15 模拟器的历史失败继续保留，但不作为这两台指定真机预览交付的否决条件，也不改标为通过。其他设备、系统升级以及未测功能仍需要各自验收。

## 交付范围与结果

| 项目 | Android 11 真机 | Android 17 真机 |
| --- | --- | --- |
| 已测机型标识 | Mi 10 Pro | 25060RK16C |
| API / ABI | 30 / arm64-v8a | 37 / arm64-v8a |
| 精确 APK 源码提交 | `07d848b8edae1df68e6ba8d4743bb7051058c38d` | `39ef3fe5c8381dc2c25e0422cca9712866060f4e` |
| APK 最低 SDK / target SDK | 30 / 35 | 31 / 35 |
| 双向 TCP、UDP、ICMP、4 KiB ICMP | 各 5/5 | 各 5/5 |
| 实际接口替换 | 3/3 | 3/3 |
| 交接窗口请求 / 响应 | 4348 / 4322 | 4159 / 4140 |
| 期限内未响应 | 26 | 19 |
| 对端错误来源 / 物理路径旁路 | 0 / 0 | 0 / 0 |
| 测试前后物理路径正对照 | 均通过 | 均通过 |

这是在指定条件下未观察到错误出口，不是零丢包、零中断或全系统兼容的保证。两次验收均为同一虚拟子网的 IPv4 路径，外层由 USB reverse TCP 承载。Android 11 首轮被 MIUI 启动确认阻断，用户允许后完整复测通过；首轮失败记录保留。

详细证据：[Android 11 真机](ANDROID11-PHYSICAL-20261030.md)、[Android 17 真机](PHYSICAL-COMPARISON-20261029.md)。

## Clash Easytier 名称和图标版

两个预览包的应用名称均为 **Clash Easytier**，图标使用用户提供的 PNG 原文件。Android adaptive icon 加入安全区留白；旧单色主题图层已移除，不再显示旧图标。

这次只重建名称与图标资源，并重新签名。每份 APK 的 27 个 DEX、12 个原生库、原始 AndroidManifest.xml、assets 和其余非资源文件均与各自实测基线逐字节相同；既有资源 ID 和非品牌资源值保持一致，非品牌资源文件沿用原字节。没有重新编译网络代码，也没有重新执行网络验收，不能把新 APK 的摘要当成历史实测文件摘要。

| 文件 | SHA-256 |
| --- | --- |
| `clash-easytier-android11-preview.apk` | `90faa07c4e1db51abb1d08b33d433992fe8f947ac0b259ac4b3de7fbc62fb14f` |
| `clash-easytier-android17-preview.apk` | `84b66b14025e30203751008be9a18f97ae13894122b7409017f989dacab6c8fe` |

实测基线摘要仍保存在 `device-preview.json` 的 `tested_baseline_sha256`；旧交付目录和 ZIP 原样保留。资源合并工具为 `scripts/rebrand-preview.py`，构建时固定 Apktool 3.0.3；未来原生构建通过 `app/src/nativeMesh/res/` 使用同一图标，普通上游构建不受影响。

两个包仍使用独立包名 `com.github.metacubex.clash.meshprototype.meta`，可与原版 CMFA、EasyTier 共存。新的本地签名私钥受当前 Windows 用户专有 ACL 保护，不在仓库或交付包内。**它与旧 CI 调试签名不同，不能直接覆盖旧签名原型。** 如已安装旧原型，先导出自己的 YAML/TOML 和需保留的数据，再自行决定是否卸载旧原型后安装新包；安装器不会自动卸载或清数据。

安装器按 API、Android 主版本、arm64 架构和机型匹配，不接受其他组合或模拟器。该检查不含设备序列号，也不能把同型号其他手机、其他固件自动变成已实测。系统升级后应重新核对；不要手动混装来绕过适配检查。

## 安装与配置

需要 Python 3.11+ 和可信来源的 Android Platform Tools / ADB。本包不包含用户订阅、组网密钥、设备序列号、instrumentation 测试包或签名私钥。

在解压目录运行：

```text
python device_preview.py
python device_preview.py --device-check
python device_preview.py --install
```

第一条只离线校验两份 APK。第二条只读检查手机并选择对应文件。第三条安装该独立应用；不会启动 VPN、导入配置、清数据或卸载任何应用。

如果 ADB 不在 PATH，加 `--adb "ADB完整路径"`。有多台已授权设备时，加 `--serial "指定设备序列号"`，工具不会自行猜测；日志不回显设备标识。两份 APK 都必须通过摘要检查，随后才接触手机。若出现签名不匹配，安装会停止，不自动卸载原型；有旧原型资料时先自行导出。

分别配置两个引擎：

1. 在独立原型中导入自己的 Clash/Mihomo YAML，并选中它。
2. 准备独立 EasyTier TOML，使用自己的网络身份及不冲突的虚拟 IPv4 地址；首版只交付同一虚拟子网的已测布局。
3. 停止并强行停止**独立原型**，再运行下列工具。TOML 内容通过标准输入写入应用私有目录，不写进命令参数或日志。

```text
python prepare-packet-harness.py --adb "ADB路径" --serial "指定设备序列号" --profile "EasyTier TOML完整路径"
```

4. 打开对应独立原型，从正常 VPN 开关启动，亲自允许系统 VPN 授权。Android 同一用户下仍只能有一个 VPN 所有者。

TOML 不使用 `no_tun=true`、`use_smoltcp=true`；MTU 为 1280–1380。默认路由、出口节点、手机端发布代理网段及主机管理选项不在这份原生校验器的允许范围。正式 EasyTier 配置编辑界面尚未完成，USB 导入是当前预览方式。

仅 EasyTier 管理的地址进入组网，其他私网、公网继续按 Clash 原配置执行，不统一添加 DIRECT。保留现有分应用和私网绕过语义；不要求始终开启 VPN 或 lockdown。应用中的系统 HTTP 代理保持关闭，HTTP/SOCKS 入口尚未接入相同组网分流。

## 未完成范围及回退

当前交付是原生 IPv4 数据通道预览，完整整合仍未完成：

- 不同虚拟子网连接存在未解决失败。
- DNS/Fake-IP 解析后的分流、HTTP/SOCKS、完整 IPv6、UDP/STUN/QUIC 外层、蜂窝切换及长时间运行尚未完成相应验收。
- DHCP/动态发布路由、完整配置编辑和模式切换界面、手机生成器输出仍待完成。
- 两台设备并未完成所有原版应用的同条件对照，也不能承诺所有游戏广播发现均可用。

历史 [Android 11 模拟器](ANDROID11-HANDOVER.md)、[Android 12/15 模拟器](ANDROID12-SUPPORT.md)失败保留，用于后续兼容排查；不能归因成“GitHub 有问题”，也不能据此否定两台真机已经完成的有限验收。

回退时停止独立原型 VPN，再打开原 CMFA 或 EasyTier。确认无需保留原型资料后，可手动卸载独立原型。交付包和安装器不修改原应用数据；PR 保持 Draft，不发布通用正式版。旧 Android 17 交付目录及 ZIP 原样保留，属于历史单设备交付。

## 来源与许可

`device-preview.json` 锁定每台设备对应 APK、源码提交和私密验收结果摘要。`SHA256SUMS.txt` 覆盖本包文件。`build-verification/` 保留构建阶段验证记录，其中 `device_validated=false` 表示该记录生成于真机验收之前；实际真机结果见上表及对应报告。

两份 APK 的执行代码源码分别位于本仓库的上表提交，锁定子模块和补丁保持对应版本；本轮品牌资源与合并工具保存在当前分支。上游许可证位于 `licenses/`。后续同系列本地重打包保留当前签名密钥；CI 自动构建不自动获得该私钥，不能视作相同签名。
