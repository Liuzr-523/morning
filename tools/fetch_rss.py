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

# 中文源优先，英文源补充；tag 为兜底分类（标题命中更具体的标签时以其为准）
FEEDS = [
    {"url": "https://www.chinanews.com.cn/rss/scroll-news.xml", "name": "中国新闻网", "lang": "zh", "take": 3, "tag": "cn"},
    {"url": "https://feeds.bbci.co.uk/news/world/rss.xml", "name": "BBC News", "lang": "en", "take": 2, "tag": "intl"},
]

# 与网页内 NEWS_TAGS 保持一致：ai / tech / fin / cn / intl / edu / cul / sport / life
TAGS = [
    ("ai", ["ai", "人工智能", "大模型", "生成式", "gpt", "机器学习", "深度学习", "智能体", "openai", "英伟达", "算力", "artificial intelligence"]),
    ("tech", ["科技", "科学", "航天", "卫星", "火箭", "量子", "互联网", "数码", "机器人", "新能源", "电池", "5g", "6g"]),
    ("fin", ["财经", "经济", "金融", "股市", "a股", "楼市", "房价", "贷款", "利率", "消费", "财报", "营收", "央行", "economy", "market"]),
    ("cn", ["国内", "时政", "政策", "国务院", "印发", "部署", "会议", "条例", "规划"]),
    ("intl", ["国际", "全球", "海外", "美国", "欧盟", "欧洲", "日本", "韩国", "联合国", "俄乌", "中东", "world"]),
    ("edu", ["教育", "高考", "中考", "大学", "高校", "考研", "学生", "教师", "学校", "招生"]),
    ("cul", ["文化", "文物", "遗产", "博物馆", "影视", "电影", "演出", "艺术", "文旅", "非遗"]),
    ("sport", ["体育", "足球", "篮球", "国足", "奥运", "赛事", "世界杯", "亚运", "夺冠", "联赛"]),
    ("life", ["民生", "健康", "医疗", "医保", "天气", "交通", "旅游", "美食", "养老", "就业", "社保"]),
]


def tag_of(text):
    """按标题/摘要猜标准标签；猜不到返回 None（交给 feed 的兜底 tag）"""
    t = (text or "").lower()
    for key, words in TAGS:
        for word in words:
            if len(word) <= 5 and re.match(r"^[a-z0-9]+$", word):
                if re.search(r"(^|[^a-z0-9])%s([^a-z0-9]|$)" % re.escape(word), t):
                    return key
            elif word in t:
                return key
    return None


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
            "tag": tag_of(title + " " + desc) or feed.get("tag", "other"),
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
