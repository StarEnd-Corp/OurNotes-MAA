<p align="center">
  <img src="logo.png" width="200" alt="OurNotes MAA">
</p>

<h1 align="center">OUR NOTES 挂机助手</h1>

<p align="center">
  <img src="https://img.shields.io/github/stars/StarEnden/OurNotes-MAA?label=Stars" alt="Stars">
  <img src="https://img.shields.io/github/commit-activity/m/StarEnden/OurNotes-MAA?label=Commit%20Activity" alt="Commit Activity">
  <img src="https://img.shields.io/github/last-commit/StarEnden/OurNotes-MAA?label=Last%20Commit" alt="Last Commit">
  <img src="https://img.shields.io/github/license/StarEnden/OurNotes-MAA?label=License" alt="License">
</p>

《BanG Dream! Our Notes》的自动化助手，基于 [MaaFramework](https://github.com/MaaXYZ/MaaFramework)。

**自动进入歌曲 → 打歌期间不进行操作 → 结算后自动重打**，另有日常领奖、跳过演出等任务。

> ⚠️ **风险提示**：脚本类自动化操作游戏可能违反游戏服务条款，存在账号风险，请自行评估使用。
> 作者不对任何账号损失负责。

## 功能

**挂机**

- 启动游戏（自动从标题页推进到主界面）
- 挂机打歌：打歌期间不进行操作；可设 0 火无限刷

**每日领奖**

- TWG 积分＋每日奖励
- 商店每日 Live Boost
- 通行证 pt（每日，适配多个通行证的情况）
- 任务奖励（每日·常规）
- 礼物盒奖励
- 录音室奖励

**其他**

- 使用跳过进行演出：可选跳过次数（1~3）与 LIVE BOOST 消耗档位
- 资源检查 / 更新

## 环境要求

| 项 | 要求 |
| :--- | :--- |
| 运行框架 | [MaaFramework](https://github.com/MaaXYZ/MaaFramework)，提供命令行执行器与核心库 |
| 图形界面（可选） | [MFAAvalonia](https://github.com/MaaXYZ/MFAAvalonia)，需 .NET 10 Desktop Runtime |
| 设备 | 安卓模拟器（实测 MuMu Player 12），分辨率建议 1920×1080 或 1280×720 |
| adb | Android platform-tools，需能在命令行调用 |
| Python（仅资源检查用） | 3.7+，只用标准库，无需第三方依赖 |

## 安装与配置

从 [Releases](../../releases) 下载最新版本的压缩包（`OurNotes-MAA-<版本>-win-x86_64.zip`），
解压到任意目录即可。

**本仓库不含任何本机路径或设备地址**。如果你用的是仓库源码而不是发行包，需要自己补齐依赖：

- **图形界面**：在 MFAAvalonia 的「设备连接」里选 adb 路径与 `127.0.0.1:<端口>`（会存到 `config/` 下）
- **命令行脚本**（可选）：把 `tools/config.local.js.example` 复制成 `tools/config.local.js` 再填
- 也可以跑 `python tools/setup_env.py` 做环境自检（缺失的组件会告诉你从哪下）

> 常见模拟器端口：MuMu 12 = `16384`，夜神 = `62001`，雷电 = `5555`。

## 运行

> 下面是从 **Release 下载发行包**后的完整流程。

### 第 1 步 · 启动

双击解压目录里的 `MFAAvalonia.exe`。

若提示缺少运行库，先运行目录里的 `DependencySetup_依赖库安装_win.bat`
（需要 .NET 10 Desktop Runtime 与 VC++ 运行库）。

### 第 2 步 · 连上模拟器

1. 先**启动你的安卓模拟器**并进入游戏，确认模拟器已开启 ADB 调试
2. 在 MFAAvalonia 的「设备连接」里选设备，首次会自动检测
3. 连不上就手工填：adb 路径选解压目录里的 `platform-tools/adb.exe`，
   地址填 `127.0.0.1:<端口>`（用 `adb devices` 查，MuMu 12 常见是 `16384`）

> ⚠️ **MuMu 用户注意**：界面会自动把 MuMu 专用的 `EmulatorExtras` 截图方式当成最优解写进配置，
> 但实测取不到画面。**发行包里的配置已经改好**（`ScreencapMethods=6`、`InputMethods=7`、
> `UseFingerprintMatching=false`）；若你自己配过设备，请确认这三项没被改回去。
> 详见[开发日志](docs/开发日志.md)。

### 第 3 步 · 勾选任务并开始

在任务列表里勾选要跑的任务（日常那几项默认已勾选），点「开始」。

- 首次启动游戏会先处理客户端的数据下载弹窗，耗时较长，属正常
- 「挂机打歌（不进行操作）」默认不勾选，需要时手动打开
- 建议先只勾一项试跑，确认识别正常后再全开

### 第 4 步 · 出问题时

界面里有运行日志；更详细的过程日志与识别截图在解压目录的 `debug/` 下，
可据此定位是哪个环节没识别到。

## 资源检查 / 更新

`tools/resource_check.py`（Python 3.7+，只用标准库）可检查资源是否完整、以及有没有新版本：

```bash
python tools/resource_check.py          # 全套检查
python tools/resource_check.py --local  # 只做本地体检（离线可用）
```

会检查流程文件能否解析、有没有指向不存在节点的引用、识别用的模板图有没有缺失；
联网时还会对比远端资源清单，告诉你要更新哪些文件。退出码 `0` 正常 / `2` 有更新或有问题。

## 已知问题

- 选曲依赖封面图匹配；游戏更新换了封面就需要重做素材
- 模拟器分辨率变更后需重新裁剪素材（请保持 1920×1080 或 1280×720）
- 识别不准时，可查看 `debug/` 下的日志与识别可视化图定位是哪个环节失败

## 开发日志

改动记录、实测数据、流程设计与脚本说明都在 **[docs/开发日志.md](docs/开发日志.md)**。
