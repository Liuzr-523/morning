#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RSS 兜底抓取：当 WorkBuddy 定时任务没跑（电脑关机 / 推送失败）时，
由 GitHub Actions 调用本脚本，直接从 RSS 抓当日新闻补写 data/latest.json。

行为：
  - data/latest.json 的 date 已是今天 -> 什么都不做，退出 0
  - 否则抓取 RSS -> 写 data/latest.json + data/archive/<date>.json
"""
import datetime
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
LATEST = os.path.join(DATA, "latest.json")

# 中文源优先，英文源补充
FEEDS = [
    {"url": "https://www.chinanews.com.cn/rss/scroll-news.xml", "name": "中国新闻网", "lang": "zh", "take": 3},
    {"url": "https://feeds.bbci.co.uk/news/world/rss.xml", "name": "BBC News", "lang": "en", "take": 2},
]


def today():
    return (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).strftime("%Y-%m-%d")


def now_iso():
    return (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def strip_html(t):
    t = re.sub(r"<[^>]+>", "", t or "")
    t = re.sub(r"\s+", " ", t).strip()
    return t


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (daily-news-bot)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def parse(xml_bytes, feed):
    out = []
    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        return out
    for item in root.iter("item"):
        title = strip_html((item.findtext("title") or ""))
        link = (item.findtext("link") or "").strip()
        desc = strip_html(item.findtext("description") or "")
        if not title or not link:
            continue
        out.append({
            "title": title[:80],
            "sum": desc[:90],
            "url": link,
            "source": feed["name"],
            "tag": feed["lang"],
        })
        if len(out) >= feed["take"]:
            break
    return out


def main():
    t = today()
    if os.path.exists(LATEST):
        try:
            old = json.load(open(LATEST, encoding="utf-8"))
            if str(old.get("date")) == t and old.get("news"):
                print("[i] data/latest.json 已是 %s 的数据，跳过" % t)
                return 0
        except Exception:
            pass

    news = []
    for f in FEEDS:
        try:
            news += parse(fetch(f["url"]), f)
        except Exception as e:
            print("[!] 抓取失败 %s: %s" % (f["name"], e))
    if not news:
        print("[x] 所有 RSS 源都抓不到，放弃写入")
        return 1

    obj = {
        "date": t,
        "generatedAt": now_iso(),
        "generator": "github-actions-rss",
        "news": news,
    }
    os.makedirs(DATA, exist_ok=True)
    with open(LATEST, "w", encoding="utf-8") as fp:
        json.dump(obj, fp, ensure_ascii=False, indent=2)
    os.makedirs(os.path.join(DATA, "archive"), exist_ok=True)
    with open(os.path.join(DATA, "archive", t + ".json"), "w", encoding="utf-8") as fp:
        json.dump(obj, fp, ensure_ascii=False, indent=2)
    print("[v] 已写入 %d 条 %s 的新闻（RSS 兜底）" % (len(news), t))
    return 0


if __name__ == "__main__":
    sys.exit(main())
