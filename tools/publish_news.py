#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发布当日新闻数据包：校验 -> 归档 -> 提交 -> 推送

用法：
    python3 tools/publish_news.py                 # 校验 + 提交 + 推送
    python3 tools/publish_news.py --no-push       # 只提交，不推送（无凭据 / 离线时用）
    python3 tools/publish_news.py --allow-stale   # 允许 data/latest.json 的日期不是今天

前置：由 WorkBuddy 定时任务把当日新闻写好到 data/latest.json
退出码：0 成功 / 1 校验失败 / 2 提交或推送失败
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
LATEST = os.path.join(DATA, "latest.json")
ARCHIVE = os.path.join(DATA, "archive")


def today():
    """北京时间（UTC+8）的今天"""
    return (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).strftime("%Y-%m-%d")


def log(msg):
    print(msg, flush=True)


def run(cmd, env=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env=e)
    return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()


def git(*args, **kw):
    return run(["git"] + list(args), **kw)


def sys_proxy():
    """读取 macOS 系统代理，git 在某些网络下必须显式走代理才能连上 github.com"""
    rc, out, _ = run(["scutil", "--proxy"])
    if rc != 0:
        return None
    if not re.search(r"HTTPEnable\s*:\s*1", out):
        return None
    host = re.search(r"HTTPProxy\s*:\s*(\S+)", out)
    port = re.search(r"HTTPPort\s*:\s*(\d+)", out)
    if host and port and port.group(1) != "0":
        return "http://%s:%s" % (host.group(1), port.group(1))
    return None


def push():
    env = {"GIT_TERMINAL_PROMPT": "0"}   # 禁止交互式弹框要密码
    rc, out, err = run(["git", "push", "origin", "HEAD"], env=env)
    if rc == 0:
        return True, out or "已推送"
    prx = sys_proxy()
    if prx:
        rc2, out2, err2 = run(["git", "-c", "http.proxy=" + prx, "push", "origin", "HEAD"], env=env)
        if rc2 == 0:
            return True, "已推送（经由系统代理 %s）" % prx
        err = err2
    return False, err or out


def validate(obj, allow_stale):
    if not isinstance(obj, dict):
        return "顶层必须是 JSON 对象"
    if "news" not in obj or not isinstance(obj["news"], list):
        return "缺少 news 数组"
    if not obj.get("date"):
        return "缺少 date 字段"
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(obj["date"])):
        return "date 格式必须是 YYYY-MM-DD"
    if not allow_stale and str(obj["date"]) != today():
        return "date=%s 不是今天（%s）。若确有需要请加 --allow-stale" % (obj["date"], today())
    if not obj["news"]:
        return "news 为空"
    for i, n in enumerate(obj["news"]):
        if not isinstance(n, dict) or not str(n.get("title", "")).strip():
            return "第 %d 条新闻缺少 title" % (i + 1)
        u = str(n.get("url", "")).strip()
        if u and not u.startswith("http"):
            return "第 %d 条新闻的 url 不合法：%s" % (i + 1, u)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--allow-stale", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(LATEST):
        log("[x] 找不到 %s —— 请先让定时任务生成它" % LATEST)
        return 1
    try:
        obj = json.load(open(LATEST, encoding="utf-8"))
    except Exception as e:
        log("[x] data/latest.json 不是合法 JSON：%s" % e)
        return 1

    err = validate(obj, args.allow_stale)
    if err:
        log("[x] 校验失败：%s" % err)
        return 1
    log("[v] 校验通过：%s，%d 条新闻" % (obj["date"], len(obj["news"])))

    os.makedirs(ARCHIVE, exist_ok=True)
    arc = os.path.join(ARCHIVE, obj["date"] + ".json")
    with open(arc, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    log("[v] 已归档 -> data/archive/%s.json" % obj["date"])

    rc, out, err = git("add", "data")
    if rc != 0:
        log("[x] git add 失败：%s" % err)
        return 2
    rc, out, _ = git("diff", "--cached", "--quiet")
    if rc == 0:
        log("[i] 内容与上次一致，无需提交")
        if args.no_push:
            return 0
        ok, msg = push()
        log(("[v] " if ok else "[x] ") + msg)
        return 0 if ok else 2

    msg = "news(%s): %d 条当日新闻" % (obj["date"], len(obj["news"]))
    rc, out, err = git("commit", "-m", msg)
    if rc != 0:
        log("[x] git commit 失败：%s" % err)
        return 2
    log("[v] 已提交：%s" % msg)

    if args.no_push:
        log("[i] --no-push：已跳过推送，请在 GitHub Desktop 点 Push")
        return 0

    ok, msg = push()
    log(("[v] " if ok else "[x] ") + msg)
    if not ok:
        log("[!] 提交已保存在本地。推送失败通常是缺少凭据，见 README「一次性凭据配置」。")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
