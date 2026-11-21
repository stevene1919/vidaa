# VIDAA Smart TV 智能电视 Home Assistant 集成

<p align="center">
  <a href="../../README.md"><img src="https://img.shields.io/badge/🇬🇧_English-gray?style=flat-square" alt="English"></a>
  <a href="README.de.md"><img src="https://img.shields.io/badge/🇩🇪_Deutsch-gray?style=flat-square" alt="Deutsch"></a>
  <a href="README.it.md"><img src="https://img.shields.io/badge/🇮🇹_Italiano-gray?style=flat-square" alt="Italiano"></a>
  <a href="README.fr.md"><img src="https://img.shields.io/badge/🇫🇷_Français-gray?style=flat-square" alt="Français"></a>
  <a href="README.ru.md"><img src="https://img.shields.io/badge/🇷🇺_Русский-gray?style=flat-square" alt="Русский"></a>
  <a href="README.uk.md"><img src="https://img.shields.io/badge/🇺🇦_Українська-gray?style=flat-square" alt="Українська"></a>
  <a href="README.zh-CN.md"><img src="https://img.shields.io/badge/🇨🇳_简体中文-blue?style=flat-square" alt="简体中文"></a>
  <a href="README.es.md"><img src="https://img.shields.io/badge/🇪🇸_Español-gray?style=flat-square" alt="Español"></a>
  <a href="README.pl.md"><img src="https://img.shields.io/badge/🇵🇱_Polski-gray?style=flat-square" alt="Polski"></a>
</p>

[![HACS](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/hacs/default)
[![Documentation](https://img.shields.io/badge/docs-stevene.enuff.com-blue.svg)](https://stevene.enuff.com/vidaa)
[![GitHub Release](https://img.shields.io/github/v/release/stevene1919/vidaa)](https://github.com/stevene1919/vidaa/releases)
[![Support on Ko-fi](https://img.shields.io/badge/Support%20on-Ko--fi-FF5E5B?style=flat&logo=ko-fi&logoColor=white)](https://ko-fi.com/stevene_)

[![打开 Home Assistant 并在 HACS 中打开该仓库。](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=stevene1919&repository=vidaa&category=integration)

专为运行 **VIDAA OS** 操作系统的智能电视和投影仪（海信 Hisense、东芝 Toshiba、Loewe、飞利浦 Philips、夏普 Sharp、JVC、TOPTRO 及合作授权品牌）打造的 Home Assistant 原生集成。

通过客户端证书**直接连接**电视内置的 MQTT 代理服务器（TLS 端口 `36669`），实现毫秒级本地推送状态更新、媒体播放控制、应用启动、局域网唤醒（Wake-on-LAN）以及虚拟遥控器功能，无需任何云端连接或第三方网关桥接。

---

## 🔰 快速入门（新手教程）

只需 3 个简步，3 分钟内完成设置：

### 1️⃣ 通过 Marketplace (HACS) 安装
点击下方按钮（或在 Marketplace (HACS) 中搜索 **VIDAA Smart TV** → 集成 → 下载）：

[![打开 Marketplace (HACS)](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=stevene1919&repository=vidaa&category=integration)

### 2️⃣ 客户端证书（浏览器一键上传或手动放置）
VIDAA 电视要求在 36669 端口进行双向 TLS 认证。
- **✨ 浏览器一键上传（推荐）：** 添加集成时，Home Assistant 会自动检查本地证书。若未检测到，只需在浏览器中直接上传官方安装包（`.apk` 或 `.xapk`）、PKCS#12 密钥包（`client_mobile_android.p12`、`El.p12`、`3R.p12`、`toshiba.p12`）或合并的 `.pem` 文件！Home Assistant 将在内存中全自动解压、解密并安全保存证书。
- **手动放置与自定义路径：** 您也可以将 `client_mobile_android.p12`、`El.p12`、`3R.p12` 或 `hisense.crt` + `hisense.key` 放置于 `/config/ssl/`（系统自动发现），或在配置界面中勾选并指定自定义文件路径。

> [!TIP]
> **需要图文分步指导？**  
> 请参阅 **[新手快速入门指南](../quick_start_beginners.md)** 获取完整截图教程（高级 PEM 证书和 OpenSSL 命令请参阅 [SSL 证书指南](../certificates.md)）。

### 3️⃣ 屏幕 PIN 码配对
1. 重启 Home Assistant（`配置` → `系统` → `重新启动`）。
2. 前往 **配置 → 设备与服务 → 添加集成**，搜索 **VIDAA Smart TV**。
3. 输入电视的局域网 IP 地址，点击 **提交**。
4. 在弹出窗口中输入电视屏幕上显示的 **4 位数字 PIN 码** 即可完成配对！

> [!IMPORTANT]
> **电视前置要求 — 开启智能/联网服务**：  
> 电视必须已开启**智能/联网服务**并同意隐私条款（`设置 → 支持/系统 → 法律声明/智能服务`）。如果未开启，VIDAA OS 会在配对时阻止屏幕弹出 4 位数 PIN 码。  
> *(隐私提示：配对完成后，在路由器端禁止电视访问外网/互联网是完全安全的；Home Assistant 本地控制 100% 离线运行)。*

> [!TIP]
> **排错基准 — 使用官方手机 App 测试**：  
> 如果电视屏幕始终不显示 4 位数 PIN 码或配对失败，可以使用官方 **VIDAA** App 测试电视连接（[苹果 iOS App Store](https://apps.apple.com/us/app/vidaa/id1526408639) 或 [谷歌 Play Store](https://play.google.com/store/apps/details?id=com.universal.remote.multi)）。如果官方 App 同样无法连接，请检查电视端是否已开启智能服务。*测试完成后，请务必在手机后台彻底关闭该 App，避免占用单一连接会话导致 Home Assistant 配对失败！*

---

## 📺 支持的电视品牌与型号

官方支持**所有搭载 VIDAA OS 系统的智能电视**（通过**屏幕 4 位 PIN 码**配对）：

- 📺 **海信 Hisense**（U6、U7、U8、UX、A6、A7 系列——U4 至 U8，2018 至 2026+ 年款）
- 📺 **Loewe**（We. SEE、stellar 等 VIDAA OS 系列）
- 📺 **东芝 Toshiba**（C350、M550、Z670 等 VIDAA 机型）
- 📺 **飞利浦 Philips / TPV**（OLED、The One、PUS 等搭载 VIDAA 系统的电视）
- 📺 **夏普 Sharp、JVC、Metz、Schneider、Telefunken、Beko** 及其他授权品牌
- 📽️ **TOPTRO**（搭载 VIDAA 系统的便携式智能投影仪）

---

## ✨ 核心特性

- **100% 局域网本地控制 (`iot_class: local_push`)**：完全脱机运行，无云端依赖，支持隔离的 IoT VLAN。
- **便捷的浏览器证书与 App 上传管线**：直接在 Home Assistant 网页端上传官方 `.apk`/`.xapk` 包、PKCS#12 密钥库（`.p12`/`.pfx`）或 `.pem` 证书，支持全内存解压、内置密码解密与品牌自动识别，完全无需命令行或 Samba 共享。
- **媒体播放器 (`media_player`)**：开关机、音量调节、输入源切换、频道切换、应用快速启动及上下文按键（电视模式换台、应用内切歌）。
- **画质与音效调节 (`select` 与 `number`)**：图像模式（`标准`、`影院`、`动态`、`体育`、`Filmmaker`）、亮度、对比度与背光微调；声音模式与音频输出设备切换。
- **专用虚拟遥控器 (`remote`)**：方向导航键、数字键、主页/菜单、四色按键及自定义长按连发。
- **开机自动化触发器 (`device_trigger`)**：原生支持 `vidaa.turn_on` 触发器，用于自动化控制智能插座通电或发送局域网唤醒。

---

## 📚 官方文档库

| 文档指南 | 说明 |
| :--- | :--- |
| 🔰 **[新手快速入门指南](../quick_start_beginners.md)** | 2 分钟极速新手指南，浏览器拖拽上传即配对。 |
| ⚙️ **[配置与选项说明](../parameters.md)** | 所有配置参数与选项菜单详解。 |
| ⚡ **[电源与待机设置](../power_and_standby_settings.md)** | 待机模式、快速开机与防止配对令牌失效配置。 |
| 📱 **[Lovelace 仪表盘与卡片](../lovelace_cards.md)** | 遥控器卡片、快捷按钮与界面范例。 |
| 🛠️ **[服务与自动化示例](../services_and_automations.md)** | 观影模式、输入源自动切换及按键宏 YAML 示例。 |
| 🔒 **[高级 SSL 证书](../certificates.md)** | 证书路径、自建 PEM 证书与 OpenSSL 命令行操作。 |
| 🧪 **[CLI 测试与诊断工具](../cli_tools.md)** | 独立排错工具（`scripts/test_client.py`、`scripts/diag.sh`）。 |
| 🩺 **[故障排除与排错指南](../troubleshooting.md)** | 网络连接、证书认证及配对失败排查方案。 |
