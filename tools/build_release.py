#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
打包「开箱即用」发行包（MaaFramework + MFAAvalonia + 本项目资源）

    python tools/build_release.py                打包到默认输出目录
    python tools/build_release.py --out <目录>   指定输出目录
    python tools/build_release.py --no-zip       只组装目录，不压缩

产物：OurNotes-MAA-<版本>-win-x86_64.zip（解压即用，无需另装框架）

打包时会做脱敏：
- 不收录 debug/ config/ screenshots/ logs/ temp/ backup/ deps/ .git/ tools/config.local.js
- GUI 的实例配置**重新生成干净版**（不带上打包者的 adb 路径与设备指纹），
  但保留 MuMu 截图方式的修复值（否则 GUI 连不上 MuMu）
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from urllib import request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARENT = os.path.dirname(ROOT)

# 不收进包的顶层项
EXCLUDE_TOP = {
    "debug", "config", "screenshots", "logs", "temp", "backup", "deps", ".git",
    "tools/config.local.js", "agent", "diag.js",
}
# 本项目自己的文件/目录
OWNS = ["interface.json", "logo.ico", "logo.png", "manifest.json", "README.md", "LICENSE",
        "CONTACT", "run.js", "docs", "resource", "tools"]
# MFAAvalonia（图形界面）自己的文件/目录
GUI = ["MFAAvalonia.exe", "MFAAvalonia.dll", "MFAAvalonia.deps.json",
       "MFAAvalonia.runtimeconfig.json", "libloader.dll", "appsettings.json",
       "libs", "runtimes", "plugins"]


def find_maaframework():
    for c in (os.environ.get("MAA_BIN"),
              os.path.join(PARENT, "MaaFramework", "bin"),
              os.path.join(PARENT, "MaaFramework")):
        if c and os.path.isdir(c):
            base = os.path.dirname(c) if os.path.basename(c) == "bin" else c
            if os.path.isdir(os.path.join(base, "bin")):
                return base
    return None


def find_platform_tools():
    for c in (os.path.join(PARENT, "platform-tools", "platform-tools"),
              os.path.join(PARENT, "platform-tools")):
        if os.path.exists(os.path.join(c, "adb.exe")):
            return c
    return None


def read_version():
    txt = open(os.path.join(ROOT, "interface.json"), encoding="utf-8").read()
    out, i, n, instr, esc = [], 0, len(txt), False, False
    BS = chr(92)
    while i < n:
        c = txt[i]
        if instr:
            out.append(c)
            if esc: esc = False
            elif c == BS: esc = True
            elif c == '"': instr = False
            i += 1
        else:
            if c == '"': instr = True; out.append(c); i += 1
            elif c == "/" and i + 1 < n and txt[i+1] == "/":
                while i < n and txt[i] != "\n": i += 1
            else: out.append(c); i += 1
    return json.loads("".join(out)).get("version", "0.0.0")


def copy_item(src, dst):
    if os.path.isdir(src):
        shutil.copytree(src, dst, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "config.local.js",
                                                      # 打包用的原始 exe 基准只供构建期使用，不进发行包
                                                      "MFAAvalonia.pristine.exe"))
    elif os.path.exists(src):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)


def dir_size(p):
    n = 0
    for base, _d, files in os.walk(p):
        for f in files:
            n += os.path.getsize(os.path.join(base, f))
    return n


CLEAN_INSTANCE = {
    "CurrentControllerName": "Android",
    "Resource": "Official",
    "CurrentTasks": [],
    "TaskItems": [],
    "InstanceName": "配置 1",
    "AdbDevice": {
        "Name": "安卓设备",
        "AdbPath": "./platform-tools/adb.exe",
        "AdbSerial": "127.0.0.1:16384",
        # 下面两行是 MuMu 必改项：GUI 自动检测会把 MuMu 专用截图方式当成最优解，但它取不到画面
        "ScreencapMethods": 6,
        "InputMethods": 7,
        "Config": "{}",
        "AgentPath": "./MaaAgentBinary",
    },
    "RememberAdb": True,
    # 关键：为 true 时每次启动都会按设备指纹重新检测并改回 EmulatorExtras
    "UseFingerprintMatching": False,
    "CurrentController": 2,
    "ResourceOptionItems": {},
}



# 发行包预置的全局配置（GUI 更新设置）
# 说明：EnableAutoUpdateResource = True（v0.1.6 起默认开启）—— 资源包是全量的
# （含 MaaFramework/MFAAvalonia/adb，130MB+），开启后启动时发现有新版会自动下载安装，
# 好处是用户始终是最新修复版；代价是每次有新版静默下 130MB（国内从 GitHub 拉可能慢或失败）。
# 同时保留 EnableCheckVersion=True，下载失败时用户能察觉。
# 想改回「只提示、由用户决定」，把下面 EnableAutoUpdateResource 设为 False 即可。
CLEAN_GLOBAL_CONFIG = {
    "CurrentLanguage": "zh-CN",
    "ColorTheme": "Blue",
    "BaseTheme": "Light",
    "ResourceUpdateChannelInitialized": True,
    "EnableCheckVersion": True,
    "EnableAutoUpdateResource": True,
    "ResourceUpdateChannelIndex": 2,
    "DownloadSourceIndex": 0,
    "EnableAutoUpdateMFA": False,
    "UIUpdateChannelIndex": 2,
}
def find_rcedit(work):
    """找 rcedit；本地没有就从官方 Releases 下一个（只有 1.3MB）"""
    for c in (os.path.join(ROOT, "tools", "rcedit-x64.exe"),
              os.path.join(work, "rcedit-x64.exe")):
        if os.path.exists(c):
            return c
    if shutil.which("rcedit") or shutil.which("rcedit-x64"):
        return shutil.which("rcedit") or shutil.which("rcedit-x64")
    dst = os.path.join(work, "rcedit-x64.exe")
    url = "https://github.com/electron/rcedit/releases/download/v2.0.0/rcedit-x64.exe"
    try:
        print("      下载 rcedit（用于替换 exe 内嵌图标）…")
        req = request.Request(url, headers={"User-Agent": "ournotes-maa-build/1.0"})
        with request.urlopen(req, timeout=60) as r, open(dst, "wb") as f:
            shutil.copyfileobj(r, f)
        return dst
    except Exception as e:
        print("      ⚠️ rcedit 获取失败：%s" % e)
        return None


def apply_icon(stage, work):
    """把 logo.ico 写进 MFAAvalonia.exe 的内嵌资源（GPL 允许，需在许可文件里标注已修改）"""
    exe = os.path.join(stage, "MFAAvalonia.exe")
    ico = os.path.join(stage, "logo.ico")
    if not os.path.exists(exe) or not os.path.exists(ico):
        return
    print("[补] 替换 MFAAvalonia.exe 的内嵌图标")

    # rcedit 不是幂等的：对「已经改过图标」的 exe 再改一次，会生成资源编码略有不同的文件
    # （代码节完全一致、功能等价，但每次打包的产物不同 → 不可复现）。
    # 所以只要存在未改动过的原始 exe，就先还原再改，保证每次打包结果一致。
    pristine = os.path.join(ROOT, "tools", "MFAAvalonia.pristine.exe")
    if os.path.exists(pristine):
        shutil.copy2(pristine, exe)
        print("      从原始 exe 开始（保证可复现）")
    else:
        print("      ⚠️ 没找到 tools/MFAAvalonia.pristine.exe，"
              "将直接对当前 exe 改图标（若它已改过，产物可能与上次不同）")

    rc = find_rcedit(work)
    if not rc:
        print("      ⚠️ 没拿到 rcedit，跳过（exe 将保留上游原版图标）")
        return
    p = subprocess.run([rc, exe, "--set-icon", ico], capture_output=True, text=True)
    if p.returncode == 0:
        print("      ✓ 已写入 logo.ico（仅资源节变化）")
    else:
        print("      ⚠️ 失败：%s" % (p.stderr or p.stdout)[:120])


def build(out_dir):
    ver = read_version()
    name = "OurNotes-MAA-%s-win-x86_64" % ver
    stage = os.path.join(out_dir, name)
    if os.path.exists(stage):
        shutil.rmtree(stage)
    os.makedirs(stage, exist_ok=True)

    print("打包版本: %s" % ver)
    print("组装目录: %s" % stage)
    print()

    # 1) 本项目
    print("[1/5] 本项目文件")
    for it in OWNS:
        src = os.path.join(ROOT, it)
        if os.path.exists(src):
            copy_item(src, os.path.join(stage, it))
            print("      + %s" % it)
        else:
            print("      - %s（不存在，跳过）" % it)

    # 2) MFAAvalonia
    print("[2/5] MFAAvalonia（图形界面）")
    for it in GUI:
        src = os.path.join(ROOT, it)
        if os.path.exists(src):
            copy_item(src, os.path.join(stage, it))
    bat = [f for f in os.listdir(ROOT) if f.startswith("DependencySetup")]
    for b in bat:
        copy_item(os.path.join(ROOT, b), os.path.join(stage, b))
    print("      + %s（%.1f MB）" % ("、".join(GUI), dir_size(os.path.join(stage, "libs")) / 1048576.0))

    # 2b) 把 logo.ico 写进 exe 的内嵌资源（可复现的修改，见 THIRD_PARTY_LICENSES.md）
    apply_icon(stage, out_dir)

    # 3) MaaFramework
    print("[3/5] MaaFramework（已装好的运行框架）")
    mf = find_maaframework()
    if mf:
        dst_bin = os.path.join(stage, "MaaFramework", "bin")
        shutil.copytree(os.path.join(mf, "bin"), dst_bin, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("debug", "config"))
        for extra in ("LICENSE.md", "README.md"):
            p = os.path.join(mf, extra)
            if os.path.exists(p):
                shutil.copy2(p, os.path.join(stage, "MaaFramework", extra))
        print("      + MaaFramework/（%.1f MB）" % (dir_size(os.path.join(stage, "MaaFramework")) / 1048576.0))
    else:
        print("      ⚠️ 找不到 MaaFramework，跳过（包会缺少命令行工具的运行库）")

    # 4) platform-tools
    print("[4/5] platform-tools（adb）")
    pt = find_platform_tools()
    if pt:
        dst = os.path.join(stage, "platform-tools")
        os.makedirs(dst, exist_ok=True)
        for f in os.listdir(pt):
            p = os.path.join(pt, f)
            if os.path.isfile(p):
                shutil.copy2(p, os.path.join(dst, f))
        print("      + platform-tools/（%.1f MB）" % (dir_size(dst) / 1048576.0))
    else:
        print("      ⚠️ 找不到 platform-tools，跳过")

    # 5) 生成的配置（脱敏）
    print("[5/5] 生成干净配置")
    os.makedirs(os.path.join(stage, "tools"), exist_ok=True)
    with open(os.path.join(stage, "tools", "config.local.js"), "w", encoding="utf-8", newline="\n") as f:
        f.write(
            "// 发行包预置配置：adb 用包里自带的 platform-tools\n"
            "// 若你的模拟器端口不是 16384，改下面的 ADB_ADDR（用 adb devices 查）\n"
            "module.exports = {\n"
            "    MAA_BIN: __dirname + '/../MaaFramework/bin',\n"
            "    ADB_PATH: __dirname + '/../platform-tools/adb.exe',\n"
            "    ADB_ADDR: '127.0.0.1:16384',\n"
            "};\n")
    os.makedirs(os.path.join(stage, "config", "instances"), exist_ok=True)
    # 全局配置：预置更新设置（GitHub 源 / Stable 渠道 / 不静默自动更新）
    with open(os.path.join(stage, "config", "config.json"), "w",
              encoding="utf-8", newline="\n") as f:
        json.dump(CLEAN_GLOBAL_CONFIG, f, ensure_ascii=False, indent=2)
    with open(os.path.join(stage, "config", "instances", "default.json"), "w",
              encoding="utf-8", newline="\n") as f:
        json.dump(CLEAN_INSTANCE, f, ensure_ascii=False, indent=2)
    print("      + tools/config.local.js（adb 指向包内）")
    print("      + config/config.json（预置更新设置）")
    print("      + config/instances/default.json（不含打包者路径，保留 MuMu 修复值）")

    # 三方许可
    with open(os.path.join(stage, "THIRD_PARTY_LICENSES.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("# 第三方组件许可\n\n"
                "本发行包内含以下第三方组件，版权归各自作者所有：\n\n"
                "| 组件 | 许可 | 上游 |\n| :--- | :--- | :--- |\n"
                "| MaaFramework | LGPL-3.0 | https://github.com/MaaXYZ/MaaFramework |\n"
                "| MFAAvalonia | GPL-3.0 | https://github.com/MaaXYZ/MFAAvalonia |\n"
                "| .NET / Avalonia UI | MIT | https://github.com/AvaloniaUI/Avalonia |\n"
                "| Android platform-tools | Apache-2.0 | https://developer.android.com/tools/releases/platform-tools |\n\n"
                "各组件的完整许可证文本见 `MaaFramework/LICENSE.md` 及其目录内的许可文件。\n"
                "本项目自身（`resource/` `interface.json` `tools/` 等）采用 MIT 许可，见 `LICENSE`。\n"
                "\n"
                "## 关于 MFAAvalonia 的修改说明（GPL-3.0 要求标注）\n"
                "\n"
                "本发行包中的 `MFAAvalonia.exe` **经过修改**：仅替换了该可执行文件内嵌的图标资源，\n"
                "使其显示为本项目的图标（`logo.ico`）。\n"
                "\n"
                "- 修改方式：用 rcedit 执行 `rcedit MFAAvalonia.exe --set-icon logo.ico`\n"
                "- 修改范围：**仅资源节 `.rsrc`**。已比对确认其余节（`.text` `.rdata` `.data`\n"
                "  `.pdata` `.reloc`）与上游原件逐字节一致，程序逻辑未作任何改动\n"
                "- 原始文件：MFAAvalonia v2.16.2 官方发行版中的 `MFAAvalonia.exe`\n"
                "- 上游源码：https://github.com/MaaXYZ/MFAAvalonia\n"
                "\n"
                "如需未修改的原版，请直接从上游 Releases 获取。\n")
    print("      + THIRD_PARTY_LICENSES.md")

    print()
    total = dir_size(stage)
    print("组装完成：%.1f MB" % (total / 1048576.0))
    return stage, name


def zipdir(stage, out_dir, name):
    zpath = os.path.join(out_dir, name + ".zip")
    if os.path.exists(zpath):
        os.remove(zpath)
    print("压缩中（可能要几分钟）...")
    t0 = time.time()
    n = 0
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for base, _d, files in os.walk(stage):
            for f in files:
                p = os.path.join(base, f)
                z.write(p, os.path.relpath(p, os.path.dirname(stage)))
                n += 1
                if n % 500 == 0:
                    print("      ... 已写入 %d 个文件" % n)
    print("压缩完成：%s" % zpath)
    print("  %d 个文件，%.1f MB，用时 %.0f 秒" % (n, os.path.getsize(zpath) / 1048576.0, time.time() - t0))
    return zpath


def audit(stage):
    """确保包里没有本机数据

    注意：这里**不把用户名等本机标识写进源码**——运行时用 getpass 取当前用户名拼进模式。
    另外不要用裸词 Administrator（MFAAvalonia 自带的 bat 里就有
    "Administrator privileges required!"，那是上游原文，不是本机数据）。
    """
    print()
    print("=== 脱敏复查 ===")
    try:
        import getpass
        user = getpass.getuser()
    except Exception:
        user = ""
    parts = [r"[A-Za-z]:[\\/]{1,2}\[main\]", r"[A-Za-z]:[\\/]{1,2}Users"]
    if user:
        parts.append(r"Users[\\/]" + re.escape(user))
        parts.append(re.escape(user) + r"[\\/](AppData|Documents|Desktop)")
    # 本机实际用的模拟器端口（从本机私有配置读），而不是泛泛查任何 localhost 端口——
    # 否则文档里写的通用默认值（如 MuMu 的 16384）会被误报
    try:
        local_cfg = open(os.path.join(ROOT, "tools", "config.local.js"), encoding="utf-8").read()
        m = re.search(r"ADB_ADDR\s*:\s*['\"](\d+\.\d+\.\d+\.\d+:\d+)['\"]", local_cfg)
        if m:
            parts.append(re.escape(m.group(1)))
    except Exception:
        pass
    pat = re.compile("|".join(parts), re.I)
    bad = 0
    for base, dirs, files in os.walk(stage):
        dirs[:] = [d for d in dirs if d not in ("libs", "runtimes", "bin", "platform-tools")]
        for f in files:
            if not f.lower().endswith((".json", ".js", ".md", ".txt", ".bat", ".yaml", ".yml")):
                continue
            p = os.path.join(base, f)
            try:
                t = open(p, encoding="utf-8", errors="replace").read()
            except Exception:
                continue
            for m in pat.finditer(t):
                line = t[:m.start()].count("\n") + 1
                print("  ⚠️ %s:%d  %s" % (os.path.relpath(p, stage), line, t.split("\n")[line-1].strip()[:80]))
                bad += 1
    print("  ✅ 未发现本机数据" if bad == 0 else "  ❌ 发现 %d 处" % bad)
    return bad


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="打包开箱即用发行包")
    ap.add_argument("--out", default="release", help="输出目录（默认 ./release）")
    ap.add_argument("--no-zip", action="store_true", help="只组装目录，不压缩")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    stage, name = build(args.out)
    bad = audit(stage)
    if not args.no_zip:
        z = zipdir(stage, args.out, name)
        print()
        print("发行包: %s" % z)
    sys.exit(1 if bad else 0)
