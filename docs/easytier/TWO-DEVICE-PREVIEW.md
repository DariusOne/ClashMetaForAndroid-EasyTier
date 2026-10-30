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

## 同包保留两份原 APK

本包不重新编译、不改签名，也不把一个 APK 当成在两台设备上都已测过。安装器分别选择各自实测的原文件：

- `cmfa-easytier-android11-preview.apk`：SHA-256 `01906d5b2366e24fe993f1f09d27a84f21eb3a415e716c713435785b2b9bee4f`。
- `cmfa-easytier-android17-preview.apk`：SHA-256 `f6560523b63b9b9a437cd7b20be643dea47be7da538c6c7e86da254e28cf404a`。

两个 APK 都使用独立包名 `com.github.metacubex.clash.meshprototype.meta`，可与原版 CMFA、EasyTier 共存。Android 11 桌面名称仍为 **CMFA + EasyTier A11 Diagnostic**；Android 17 仍为 **CMFA + EasyTier Prototype**。保留这些标签是为了交付相同二进制文件；本轮明确接受它们作为有限范围预览，仍不是通用 Release。

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

两份 APK 的完整源码分别位于本仓库的上表提交，锁定子模块和补丁保持对应版本。上游许可证位于 `licenses/`。本包不承诺稳定发布签名；以后更换构建签名可能无法覆盖安装，工具不会绕过签名校验。
