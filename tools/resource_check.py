#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
资源检查 / 更新检查工具（海外源优先）

机制：
  ① 仓库侧发布一份 manifest.json（记录每个资源文件的毫秒时间戳）
  ② 客户端本地存 manifest_cache.json
  ③ 拉远端 manifest 与本地实际文件比对，只重新下载"变了/新增"的文件
  ④ 更新源分「海外源」(GitHub 直连) 与「国内源」(镜像)

本工具把这套机制落地成命令行，供本项目的资源与用户端自查：

  用法（在项目根目录下跑）:
    python tools/resource_check.py                 全套检查（本地完整性 + 远端版本 + 清单比对）
    python tools/resource_check.py --local         只做本地完整性检查（离线可用，不联网）
    python tools/resource_check.py --make-manifest 生成 manifest.json（仓库/CI 侧发布用）
    python tools/resource_check.py --source cn     走国内镜像源
    python tools/resource_check.py --json          机器可读输出

  退出码: 0=一切正常/已是最新   2=有更新或发现资源问题   3=网络/配置错误

仅用标准库，Python 3.7+ 均可（含 UOS 自带的 3.7）。
"""

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
from urllib import request, error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESOURCE_DIR = os.path.join(ROOT, "resource")
PIPELINE_DIR = os.path.join(RESOURCE_DIR, "pipeline")
IMAGE_DIR = os.path.join(RESOURCE_DIR, "image")
INTERFACE = os.path.join(ROOT, "interface.json")
MANIFEST = os.path.join(ROOT, "manifest.json")
CACHE = os.path.join(ROOT, "manifest_cache.json")

# 海外源 / 国内源
SOURCES = {
    "overseas": {
        "name": "海外源 (GitHub 直连)",
        "api": "https://api.github.com",
        "raw": "https://raw.githubusercontent.com",
    },
    "cn": {
        "name": "国内源 (ghproxy 镜像)",
        "api": "https://api.github.com",          # api 仍走 GitHub（无镜像）
        "raw": "https://ghproxy.net/https://raw.githubusercontent.com",
    },
}

TIMEOUT = 15


def get_token():
    """取 GitHub 令牌：优先 GITHUB_TOKEN 环境变量，其次 `gh auth token`（私有仓库必须带）"""
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        return tok.strip()
    try:
        r = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return None


# ---------------------------------------------------------------- 基础工具
def strip_json_comments(text):
    """去掉 // 行注释（保留字符串内的 //），使带注释的 interface.json 可解析"""
    out, i, n, instr, esc = [], 0, len(text), False, False
    while i < n:
        c = text[i]
        if instr:
            out.append(c)
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                instr = False
            i += 1
        else:
            if c == '"':
                instr = True
                out.append(c)
                i += 1
            elif c == "/" and i + 1 < n and text[i + 1] == "/":
                while i < n and text[i] != "\n":
                    i += 1
            else:
                out.append(c)
                i += 1
    return "".join(out)


def load_interface():
    with open(INTERFACE, encoding="utf-8") as f:
        return json.loads(strip_json_comments(f.read()))


def http_get(url, timeout=TIMEOUT, headers=None, token=None):
    h = {"User-Agent": "ournotes-maa-resource-check/1.0"}
    if token:
        h["Authorization"] = "Bearer %s" % token
    if headers:
        h.update(headers)
    req = request.Request(url, headers=h)
    with request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def api_get_json(url, token=None):
    """走 GitHub API 取 JSON（私有仓库必须带 token）"""
    return json.loads(http_get(url, headers={"Accept": "application/vnd.github+json"}, token=token))


def api_get_file(owner, repo, path, branch, token):
    """走 GitHub contents API 取单个文件文本（私有仓库 raw 域名取不到，只能这样）"""
    url = "%s/repos/%s/%s/contents/%s?ref=%s" % (SOURCES["overseas"]["api"], owner, repo, path, branch)
    d = api_get_json(url, token)
    if isinstance(d, dict) and d.get("content"):
        return base64.b64decode(d["content"]).decode("utf-8", "replace")
    raise RuntimeError("contents API 返回了意外结构")


def ver_tuple(s):
    """把 v4.11.1 / 4.11 之类规整成可比较的元组"""
    s = (s or "").strip().lstrip("vV")
    parts = re.findall(r"\d+", s)
    return tuple(int(p) for p in parts) if parts else (0,)


def cmp_ver(a, b):
    ta, tb = ver_tuple(a), ver_tuple(b)
    n = max(len(ta), len(tb))
    ta = ta + (0,) * (n - len(ta))
    tb = tb + (0,) * (n - len(tb))
    return (ta > tb) - (ta < tb)


# ---------------------------------------------------------------- 本地完整性
def local_check():
    """离线也能跑：查 pipeline 的悬空引用 + 缺失的模板图"""
    problems = []
    infos = []

    if not os.path.isdir(PIPELINE_DIR):
        return ["找不到 pipeline 目录: %s" % PIPELINE_DIR], []

    pipelines = {}
    for fn in sorted(os.listdir(PIPELINE_DIR)):
        if not fn.endswith(".json"):
            continue
        p = os.path.join(PIPELINE_DIR, fn)
        try:
            with open(p, encoding="utf-8") as f:
                pipelines[fn] = json.load(f)
        except Exception as e:
            problems.append("[JSON] %s 解析失败: %s" % (fn, e))

    # 所有节点的名字集合（用于跨文件引用检查）
    all_names = set()
    for d in pipelines.values():
        all_names.update(d.keys())

    BUILTIN = {"MaintenanceStop"}          # 框架内建/外部节点
    for fn, d in pipelines.items():
        for node, cfg in d.items():
            if not isinstance(cfg, dict):
                continue
            for key in ("next", "on_error", "interrupt"):
                for ref in (cfg.get(key) or []):
                    if ref not in all_names and ref not in BUILTIN:
                        problems.append("[悬空引用] %s 的节点 %s.%s → %s 不存在" % (fn, node, key, ref))
            # 模板图是否存在
            if cfg.get("recognition") in ("TemplateMatch", "FeatureMatch") and cfg.get("template"):
                t = cfg["template"]
                if not os.path.exists(os.path.join(IMAGE_DIR, t)):
                    problems.append("[缺模板] %s 的节点 %s 引用的图片 %s 不存在" % (fn, node, t))

    infos.append("pipeline 文件 %d 个，节点合计 %d 个" % (len(pipelines), len(all_names)))
    if os.path.isdir(IMAGE_DIR):
        imgs = [x for x in os.listdir(IMAGE_DIR) if x.lower().endswith((".png", ".jpg", ".bmp"))]
        infos.append("模板图 %d 张" % len(imgs))
    return problems, infos


# ---------------------------------------------------------------- manifest
# 清单除 resource/ 外，还要带上这两个：它们是"要分发的东西"，改图标/改任务定义时
# 用户端也应该能通过清单比对发现
EXTRA_FILES = ["interface.json", "logo.ico"]


def scan_files():
    """扫描 resource/ 及根目录的待分发文件 → {相对项目根的路径: 毫秒时间戳}（用 mtime）"""
    files = {}
    for rel in EXTRA_FILES:
        p = os.path.join(ROOT, rel)
        if os.path.exists(p):
            files[rel.replace("\\", "/")] = int(os.path.getmtime(p) * 1000)
    for base, _dirs, names in os.walk(RESOURCE_DIR):
        for n in names:
            if n.startswith("."):
                continue
            p = os.path.join(base, n)
            rel = os.path.relpath(p, ROOT).replace("\\", "/")
            files[rel] = int(os.path.getmtime(p) * 1000)
    return files


def make_manifest():
    files = scan_files()
    try:
        ver = load_interface().get("version", "")
    except Exception:
        ver = ""
    data = {
        "version": ver,
        "generated_at": int(time.time() * 1000),
        "generator": "ournotes-maa tools/resource_check.py",
        "files": files,
    }
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
    print("已生成 %s（%d 个文件，version=%s）" % (MANIFEST, len(files), ver))
    return 0


def compare_manifest(remote, source):
    """远端 manifest vs 本地实际文件 → 需要更新的项"""
    local = scan_files()
    rf = (remote or {}).get("files") or {}
    add, mod, gone = [], [], []
    for path, rmt in rf.items():
        if path not in local:
            add.append(path)
        elif int(local[path]) != int(rmt):
            mod.append(path)
    for path in local:
        if path not in rf:
            gone.append(path)
    return local, rf, add, mod, gone


# ---------------------------------------------------------------- 远端
def remote_version(gh, src, token=None):
    """返回 (owner, repo, tag 或 None, 说明文字)。

    ⚠️ 只有在真的取到一个"像版本号"的 tag 时才返回 tag；取不到就返回 None，
    绝不要把错误文字当成版本号丢给比较逻辑（否则会误报"发现新版本"）。
    """
    m = re.search(r"github\.com[/:]([^/]+)/([^/#?]+)", gh or "")
    if not m:
        return None, None, None, "interface.json 的 github 字段无法解析: %r" % gh
    owner, repo = m.group(1), m.group(2)
    repo = repo[:-4] if repo.endswith(".git") else repo

    try:
        data = api_get_json("%s/repos/%s/%s/releases/latest" % (src["api"], owner, repo), token)
        tag = data.get("tag_name") or data.get("name")
        if tag:
            return owner, repo, tag, "来自 latest release"
    except error.HTTPError as e:
        if e.code in (401, 403, 404):
            pass          # 可能是私有仓库没带 token，或还没有 release → 继续试 tags
        else:
            return owner, repo, None, "取 release 失败：HTTP %s" % e.code
    except Exception as e:
        return owner, repo, None, "取 release 失败：%s" % e

    try:
        tags = api_get_json("%s/repos/%s/%s/tags" % (src["api"], owner, repo), token)
        if tags:
            return owner, repo, tags[0].get("name"), "来自 tag 列表"
        return owner, repo, None, "仓库还没有任何 tag / release"
    except error.HTTPError as e:
        if e.code in (401, 403, 404):
            return owner, repo, None, "取不到（私有仓库需带令牌，或仓库还没有 tag/release）"
        return owner, repo, None, "取 tags 失败：HTTP %s" % e.code
    except Exception as e:
        return owner, repo, None, "取 tags 失败：%s" % e


def remote_manifest(owner, repo, src, branch="main", token=None):
    """先试 raw 域名（公开仓库无需令牌），失败再走 contents API（私有仓库只有这条路）"""
    url = "%s/%s/%s/%s/manifest.json" % (src["raw"], owner, repo, branch)
    try:
        return json.loads(http_get(url)), url + "（raw）"
    except Exception:
        pass
    try:
        txt = api_get_file(owner, repo, "manifest.json", branch, token)
        return json.loads(txt), "contents API"
    except error.HTTPError as e:
        if e.code in (401, 403, 404):
            return None, "raw 与 contents API 都取不到（私有仓库需带令牌；或仓库里还没有 manifest.json）"
        return None, "contents API HTTP %s" % e.code
    except Exception as e:
        return None, "raw 与 contents API 都失败：%s" % e


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser(description="资源检查 / 更新检查（海外源优先）")
    ap.add_argument("--local", action="store_true", help="只做本地完整性检查，不联网")
    ap.add_argument("--make-manifest", action="store_true", help="生成 manifest.json 后退出")
    ap.add_argument("--source", choices=list(SOURCES), default="overseas",
                    help="更新源：overseas=海外源(GitHub) / cn=国内镜像")
    ap.add_argument("--branch", default="main", help="仓库分支（默认 main）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    if args.make_manifest:
        return make_manifest()

    src = SOURCES[args.source]
    report = {"source": src["name"], "problems": [], "infos": [], "update": None}
    rc = 0

    # ---- ① 本地完整性 ----
    problems, infos = local_check()
    report["problems"] = problems
    report["infos"] = infos

    # ---- ② 远端版本 + 清单 ----
    if not args.local:
        try:
            iface = load_interface()
        except Exception as e:
            report["problems"].append("读 interface.json 失败: %s" % e)
            iface = {}
        local_ver = iface.get("version", "")
        gh = iface.get("github", "")
        report["local_version"] = local_ver

        token = get_token()
        owner, repo, tag, vnote = remote_version(gh, src, token)
        report["remote_version"] = tag
        report["remote_note"] = vnote
        if owner and repo:
            report["repo"] = "%s/%s" % (owner, repo)
            # 只有拿到"像版本号"的 tag 才比较；拿不到就只是告知，绝不误报更新
            if tag and re.match(r"^v?\d", tag):
                if cmp_ver(local_ver, tag) < 0:
                    report["update"] = {"type": "version", "local": local_ver, "remote": tag}
                    rc = 2
                else:
                    report["infos"].append("版本已是最新（%s）" % local_ver)
            else:
                report["infos"].append("远端版本：%s" % (vnote or "取不到"))

            rm, note = remote_manifest(owner, repo, src, args.branch, token)
            report["manifest_source"] = note
            if rm:
                local, rf, add, mod, gone = compare_manifest(rm, src)
                report["manifest"] = {"remote_files": len(rf), "local_files": len(local),
                                      "to_add": add, "to_modify": mod, "not_in_remote": gone}
                if add or mod:
                    rc = 2
            else:
                report["infos"].append("远端 manifest 取不到：%s" % note)

    # ---- 输出 ----
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return rc

    print("=" * 62)
    print("资源检查报告    源: %s" % report["source"])
    print("=" * 62)
    for i in report["infos"]:
        print("  · %s" % i)
    if report.get("local_version") is not None:
        rv = report.get("remote_version")
        print("  · 本地版本: %s    远端版本: %s%s" % (
            report.get("local_version"),
            rv if rv else "未取到",
            "" if rv else "（%s）" % report.get("remote_note", "")))
    print()

    m = report.get("manifest")
    if m:
        print("【资源清单比对】远端 %d 个文件 / 本地 %d 个文件" % (m["remote_files"], m["local_files"]))
        if m["to_add"]:
            print("  需要新增 %d 个：" % len(m["to_add"]))
            for p in m["to_add"][:20]:
                print("     + %s" % p)
        if m["to_modify"]:
            print("  需要更新 %d 个：" % len(m["to_modify"]))
            for p in m["to_modify"][:20]:
                print("     ~ %s" % p)
        if m["not_in_remote"]:
            print("  本地有、远端没有 %d 个（多半是你本地改过）：" % len(m["not_in_remote"]))
            for p in m["not_in_remote"][:10]:
                print("     ? %s" % p)
        if not (m["to_add"] or m["to_modify"]):
            print("  ✅ 资源文件与远端一致")
        print()

    if report["problems"]:
        print("【本地完整性问题】%d 条" % len(report["problems"]))
        for p in report["problems"]:
            print("  ❌ %s" % p)
    else:
        print("✅ 本地完整性检查通过（无悬空引用、无缺失模板图）")

    print()
    if report.get("update"):
        u = report["update"]
        print("⚠️  发现新版本: %s → %s，建议更新" % (u["local"], u["remote"]))
    elif report.get("update") is None and not args.local:
        print("✅ 版本检查完成")
    print("退出码 %d（0=正常 2=有更新/有问题 3=网络或配置错误）" % rc)
    return rc


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
