#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
环境自检 / 依赖下载

用法（在项目根目录下跑）:
    python tools/setup_env.py              自检并报告（默认）
    python tools/setup_env.py --download   下载缺失的依赖到 deps/（不自动安装）
    python tools/setup_env.py --dry-run    只显示"会下载什么"，不实际下载
    python tools/setup_env.py --json       机器可读输出

说明：
- 只检查、只下载，**绝不代替你安装**（解压路径、是否覆盖由你决定）
- 模拟器本身无法自动安装（各家模拟器差异大），工具只负责检查并提示
- 只用标准库，Python 3.7+ 可跑
"""

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from urllib import request, error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEPS = os.path.join(ROOT, "deps")

# 各依赖的 GitHub 仓库与目标产物名（已按实际 release 产物核对）
GH_DEPS = {
    "maaframework": {
        "repo": "MaaXYZ/MaaFramework",
        "label": "MaaFramework（运行框架 / 命令行执行器）",
        "asset": re.compile(r"^MAA-win-x86_64-.*\.zip$"),
    },
    "mfaa": {
        "repo": "MaaXYZ/MFAAvalonia",
        "label": "MFAAvalonia（图形界面）",
        "asset": re.compile(r"^MFAAvalonia-.*-win-x64\.zip$"),
    },
}
PLATFORM_TOOLS_URL = "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"
DOTNET_URL = "https://aka.ms/dotnet/10.0/windowsdesktop-runtime-win-x64.exe"
# MFAAvalonia v2.16.2 的 runtimeconfig.json 里 tfm = net10.0 → 要求 .NET 10
# （只装 .NET 6/8/9 是不够的；检查时要取"最高版本"再比，不能拿第一个匹配）
DOTNET_REQUIRED = (10, 0)


def run(cmd, timeout=20):
    """跑一条命令，返回 (退出码, 标准输出+错误)"""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, shell=isinstance(cmd, str))
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return 127, "找不到命令"
    except subprocess.TimeoutExpired:
        return 124, "超时"
    except Exception as e:
        return 1, str(e)


def read_config_local():
    """从 tools/config.local.js 里粗略读取三个值（不引 JS，纯正则）"""
    p = os.path.join(ROOT, "tools", "config.local.js")
    out = {}
    if not os.path.exists(p):
        return out
    t = open(p, encoding="utf-8", errors="replace").read()
    for key in ("MAA_BIN", "ADB_PATH", "ADB_ADDR"):
        m = re.search(key + r"\s*:\s*['\"]([^'\"]+)['\"]", t)
        if m:
            out[key] = m.group(1).replace("\\\\", "\\")
    return out


def find_adb(cfg):
    """按 环境变量 → config.local.js → PATH 的顺序找 adb"""
    cand = []
    if os.environ.get("ADB_PATH"):
        cand.append(os.environ["ADB_PATH"])
    if cfg.get("ADB_PATH"):
        cand.append(cfg["ADB_PATH"])
    if shutil.which("adb"):
        cand.append(shutil.which("adb"))
    for c in cand:
        if c == "adb" or os.path.exists(c):
            return c
    return None


def api_json(url, token=None):
    h = {"User-Agent": "ournotes-maa-setup/1.0", "Accept": "application/vnd.github+json"}
    if token:
        h["Authorization"] = "Bearer %s" % token
    req = request.Request(url, headers=h)
    with request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def get_token():
    t = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if t:
        return t.strip()
    rc, out = run(["gh", "auth", "token"], timeout=10)
    return out.strip() if rc == 0 and out.strip() else None


def resolve_asset(spec, token):
    """查最新 release，返回匹配的产物 (tag, name, url, size)"""
    d = api_json("https://api.github.com/repos/%s/releases/latest" % spec["repo"], token)
    tag = d.get("tag_name", "?")
    for a in d.get("assets", []):
        if spec["asset"].match(a["name"]):
            return tag, a["name"], a["browser_download_url"], a.get("size", 0)
    return tag, None, None, 0


def download(url, dest, label):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    print("    开始下载 %s" % label)
    t0 = time.time()
    try:
        req = request.Request(url, headers={"User-Agent": "ournotes-maa-setup/1.0"})
        with request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            got = 0
            step = 0
            while True:
                buf = r.read(65536)
                if not buf:
                    break
                f.write(buf)
                got += len(buf)
                if total and got - step > total // 10:
                    step = got
                    print("      %5.1f%%  (%.1f/%.1f MB)" % (100.0 * got / total, got / 1048576.0, total / 1048576.0))
        print("    完成 %s → %s（%.1f MB，%.1fs）" % (label, dest, os.path.getsize(dest) / 1048576.0, time.time() - t0))
        return True
    except Exception as e:
        print("    ✗ 下载失败：%s" % e)
        if os.path.exists(dest):
            os.remove(dest)
        return False


def our_release():
    """读 interface.json 的 github 字段，返回 (owner, repo, 最新 release 信息)"""
    try:
        txt = open(os.path.join(ROOT, "interface.json"), encoding="utf-8").read()
        m = re.search(r'"github"\s*:\s*"([^"]+)"', txt)
        if not m:
            return None, None, None
        m2 = re.search(r"github\.com[/:]([^/]+)/([^/#?\"]+)", m.group(1))
        if not m2:
            return None, None, None
        owner, repo = m2.group(1), m2.group(2).removesuffix(".git")
        d = api_json("https://api.github.com/repos/%s/%s/releases/latest" % (owner, repo), get_token())
        return owner, repo, d
    except Exception:
        return None, None, None


def resolve_bundle(rel):
    """从我们自己的 release 里找开箱即用发行包"""
    if not rel:
        return None
    for a in (rel.get("assets") or []):
        if re.match(r"^OurNotes-MAA-.*-win-x86_64\.zip$", a["name"]):
            return rel.get("tag_name", "?"), a["name"], a["browser_download_url"], a.get("size", 0)
    return None


def is_admin():
    """Windows 下判断当前是否管理员"""
    if platform.system() != "Windows":
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


# ------------------------------------------------------------------ 各项检查
def check_python():
    v = sys.version_info
    ok = v >= (3, 7)
    return ok, "Python %d.%d.%d" % (v[0], v[1], v[2]), "需要 3.7 以上"


def check_adb(cfg):
    adb = find_adb(cfg)
    if not adb:
        return False, "未找到", "把 adb 放进 PATH，或在 tools/config.local.js 里写 ADB_PATH"
    rc, out = run([adb, "version"], timeout=15)
    if rc != 0:
        return False, "找到 %s 但执行失败：%s" % (adb, out.strip()[:80]), "检查文件是否完整"
    ver = ""
    m = re.search(r"version\s+([\d.]+)", out)
    if m:
        ver = m.group(1)
    return True, "%s（%s）" % (adb, ver or "版本未知"), ""


def check_device(cfg):
    """检查是否已连接安卓设备（模拟器）"""
    adb = find_adb(cfg)
    if not adb:
        return None, "跳过（adb 不可用）", "先解决 adb"
    rc, out = run([adb, "devices"], timeout=15)
    if rc != 0:
        return None, "adb devices 执行失败", "检查 adb"
    serials = [l.split()[0] for l in out.split("\n")[1:]
               if l.strip() and "\t" in l and l.split()[1] == "device"]
    if not serials:
        return False, "没有已连接的设备", "启动模拟器，并确认已开启 ADB 调试（adb devices 能看到）"

    s = serials[0]
    _rc, model = run([adb, "-s", s, "shell", "getprop", "ro.product.model"], timeout=20)
    model = (model or "").strip()
    return True, "已连接 %s（型号 %s）" % (s, model or "未读到"), ""


def check_maaframework(cfg):
    bin_dir = os.environ.get("MAA_BIN") or cfg.get("MAA_BIN")
    if not bin_dir:
        cand = os.path.join(os.path.dirname(ROOT), "MaaFramework", "bin")
        bin_dir = cand if os.path.isdir(cand) else None
    if not bin_dir or not os.path.isdir(bin_dir):
        return False, "未找到", "用 --download 下载后解压，或在 tools/config.local.js 里写 MAA_BIN"
    marks = [f for f in os.listdir(bin_dir) if f in ("MaaNode.node", "MaaPiCli.exe")]
    if not marks:
        return False, "目录存在但没有 MaaNode.node / MaaPiCli.exe", "确认解压到正确位置"
    return True, "%s（含 %s）" % (bin_dir, "、".join(marks)), ""


def check_mfaa():
    exe = os.path.join(ROOT, "MFAAvalonia.exe")
    if os.path.exists(exe):
        return True, exe, ""
    return False, "未找到（图形界面是可选组件）", "需要图形界面时用 --download 下载并解压到项目根目录"


def check_dotnet():
    if platform.system() != "Windows":
        return None, "跳过（非 Windows）", ""
    rc, out = run(["dotnet", "--list-runtimes"], timeout=25)
    if rc != 0:
        return False, "未装 .NET 或不在 PATH", "仅图形界面需要：下载安装 .NET %d Desktop Runtime" % DOTNET_REQUIRED[0]
    vers = []
    for l in out.split("\n"):
        if "Microsoft.WindowsDesktop.App" in l:
            m = re.search(r"Microsoft\.WindowsDesktop\.App\s+(\d+)\.(\d+)\.(\d+)", l)
            if m:
                vers.append((int(m.group(1)), int(m.group(2)), int(m.group(3))))
    if not vers:
        return False, "装了 .NET 但没有 Desktop Runtime", "仅图形界面需要：下载安装 .NET %d Desktop Runtime" % DOTNET_REQUIRED[0]
    best = max(vers)
    ok = best >= DOTNET_REQUIRED
    detail = "WindowsDesktop.App %d.%d.%d" % best
    if not ok:
        detail += "（低于所需的 %d.0）" % DOTNET_REQUIRED[0]
    return ok, detail, "" if ok else "仅图形界面需要：下载安装 .NET %d Desktop Runtime" % DOTNET_REQUIRED[0]


# ------------------------------------------------------------------ 主流程
def main():
    ap = argparse.ArgumentParser(description="环境自检 / 依赖下载")
    ap.add_argument("--check", action="store_true", help="只自检（默认）")
    ap.add_argument("--download", action="store_true", help="下载缺失的依赖到 deps/")
    ap.add_argument("--bundle", action="store_true",
                    help="直接下载「开箱即用发行包」（内含 MFAAvalonia + MaaFramework + platform-tools）")
    ap.add_argument("--dry-run", action="store_true", help="只显示会下载什么")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    cfg = read_config_local()
    report, results = {}, []
    for key, fn in (("python", check_python), ("adb", lambda: check_adb(cfg)),
                    ("device", lambda: check_device(cfg)),
                    ("maaframework", lambda: check_maaframework(cfg)),
                    ("mfaa", check_mfaa), ("dotnet", check_dotnet)):
        try:
            ok, detail, howto = fn()
        except Exception as e:
            ok, detail, howto = False, "检查出错：%s" % e, ""
        results.append({"key": key, "ok": ok, "detail": detail, "howto": howto})
        report[key] = {"ok": ok, "detail": detail, "howto": howto}

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        names = {"python": "Python", "adb": "adb", "device": "设备连接",
                 "maaframework": "MaaFramework", "mfaa": "MFAAvalonia（可选）", "dotnet": ".NET Desktop Runtime（可选）"}
        print("=" * 64)
        print("环境自检")
        print("=" * 64)
        for r in results:
            mark = "✅" if r["ok"] is True else ("⚠️ " if r["ok"] is None else "❌")
            print("  %s %-30s %s" % (mark, names[r["key"]], r["detail"]))
            if r["ok"] is False and r["howto"]:
                print("      → %s" % r["howto"])
        need = [r for r in results if r["ok"] is False and r["key"] in ("adb", "device", "maaframework", "mfaa", "dotnet")]
        print()
        if need:
            print("有 %d 项缺失。两种补法：" % len(need))
            print("  python tools/setup_env.py --download   # 逐个下官方组件")
            print("  python tools/setup_env.py --bundle     # 直接下「开箱即用发行包」")
            print("                                         # （内含 MFAAvalonia + MaaFramework + platform-tools）")
        else:
            print("环境就绪 ✅")
        print()
        print("说明：模拟器本身需要你自行安装（各家模拟器差异大，无法自动装）；")
        print("      本工具只做「检查 + 下载」，不代替你安装。")
        _o, _r, _rel = our_release()
        if _rel:
            print()
            print("发行包：https://github.com/%s/%s/releases" % (_o, _r))
            _b = resolve_bundle(_rel)
            if _b:
                print("        最新 %s —— %s（%.1f MB）" % (_b[0], _b[1], _b[3] / 1048576.0))

    # ---------- 下载发行包 ----------
    if args.bundle:
        print()
        print("=" * 64)
        print("下载开箱即用发行包%s" % ("（演练）" if args.dry_run else ""))
        print("=" * 64)
        _o, _r, _rel = our_release()
        b = resolve_bundle(_rel)
        if not b:
            print("  ✗ 取不到发行包（仓库还没有 release；私有仓库需带令牌）")
            return 1
        tag, bname, burl, bsize = b
        print("  %s：%s（%.1f MB）" % (tag, bname, bsize / 1048576.0))
        print("  内含 MFAAvalonia + MaaFramework + platform-tools，解压即用")
        print("  下载位置：%s" % DEPS)
        if args.dry_run:
            return 0
        ok = download(burl, os.path.join(DEPS, bname), "发行包 %s" % tag)
        print()
        print("解压后双击 MFAAvalonia.exe 即可使用（模拟器仍需你自备）。" if ok else "下载失败。")
        return 0 if ok else 1

    if not (args.download or args.dry_run):
        return 0

    # ---------- 下载 ----------
    print()
    print("=" * 64)
    print("依赖下载%s" % ("（演练，不实际下载）" if args.dry_run else ""))
    print("=" * 64)
    token = get_token()
    plan = []

    for key, spec in GH_DEPS.items():
        if report[key]["ok"] is True:
            print("  · %s 已就绪，跳过" % spec["label"])
            continue
        try:
            tag, name, url, size = resolve_asset(spec, token)
        except Exception as e:
            print("  ⚠️ %s 查询失败：%s" % (spec["label"], e))
            continue
        if not url:
            print("  ⚠️ %s 最新版 %s 里没有匹配的产物" % (spec["label"], tag))
            continue
        plan.append((url, os.path.join(DEPS, name), "%s %s" % (spec["label"], tag), size))

    if report["adb"]["ok"] is False:
        plan.append((PLATFORM_TOOLS_URL, os.path.join(DEPS, "platform-tools-latest-windows.zip"),
                     "Android platform-tools（adb）", 0))
    if report["dotnet"]["ok"] is False:
        plan.append((DOTNET_URL, os.path.join(DEPS, "windowsdesktop-runtime-win-x64.exe"),
                     ".NET Desktop Runtime 安装包", 0))

    if not plan:
        print("  没有需要下载的（或全部已就绪）")
        return 0

    print()
    for url, dest, label, size in plan:
        print("  → %-52s %s" % (label, ("%.1f MB" % (size / 1048576.0)) if size else ""))
        print("      %s" % os.path.basename(dest))

    if args.dry_run:
        print()
        print("（--dry-run：以上仅为计划，未实际下载）")
        return 0

    print()
    okn = 0
    for url, dest, label, size in plan:
        if download(url, dest, label):
            okn += 1
    print()
    print("下载完成 %d/%d，文件在 %s" % (okn, len(plan), DEPS))

    # .NET 安装包：有管理员权限就直接静默安装
    dn = os.path.join(DEPS, "windowsdesktop-runtime-win-x64.exe")
    if os.path.exists(dn):
        print()
        if is_admin():
            print(".NET Desktop Runtime：检测到管理员权限，开始静默安装…")
            rc, out = run([dn, "/install", "/quiet", "/norestart"], timeout=900)
            print("  安装程序退出码 %d（0=成功；3010=成功但需重启；1602=被取消）" % rc)
        else:
            print(".NET Desktop Runtime：安装包已下好，但没有管理员权限，请右键「以管理员身份运行」：")
            print("  %s" % dn)

    print()
    print("接下来（需要你手动做）：")
    print("  1. 把 MaaFramework 的 zip 解压到项目同级目录（解压后 bin/ 里应有 MaaNode.node）")
    print("  2. 若要图形界面，把 MFAAvalonia 的 zip 解压到项目根目录（与 interface.json 同级）")
    print("  3. platform-tools 解压后，把 adb.exe 路径填进 tools/config.local.js 的 ADB_PATH")
    print("  4. .NET 运行时是 exe 安装包，双击安装（需管理员权限）")
    print("  5. 模拟器请自行安装并开启 ADB 调试")
    print()
    print("做完再跑一次：python tools/setup_env.py")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
