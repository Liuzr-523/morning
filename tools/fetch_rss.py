#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按标签抓取当日新闻：每个标准标签各抓 PER_TAG 条（默认 5 条）。

只用**国内可直连**的 RSS 源。原因：早期版本走 Google News RSS，抓到的链接
指向 news.google.com，国内打不开（实测 12 秒超时），等于新闻点不动。

两个用途：
  1) GitHub Actions 兜底：WorkBuddy 定时任务没跑（关机 / 推送失败）时自动补数据
  2) 本地手动执行：`python3 tools/fetch_rss.py`，可加 --force 忽略"今天已有数据"

流程：并发抓全部源 → 逐条用关键词归类 → 归不出的用该源的主标签兜底 →
按标签分桶，每桶取 PER_TAG 条（同一桶内按来源轮流，避免被一个源包圆）。
实在凑不满就少几条，绝不编造标题或链接。
"""
import datetime
import json
import os
import re
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
LATEST = os.path.join(DATA, "latest.json")

PER_TAG = 5  # 每个标签抓取条数

# 标准标签：与网页 index.html 里的 NEWS_TAGS / TAG_OTHER 保持一致
TAG_ORDER = ["ai", "tech", "fin", "cn", "intl", "edu", "cul", "sport", "life", "other"]

# 关键词命中规则（顺序即优先级）。英文短词按词边界匹配，中文直接包含。
KEYWORDS = [
    ("ai", ["ai", "人工智能", "大模型", "生成式", "gpt", "chatgpt", "gemini", "机器学习",
            "深度学习", "智能体", "openai", "英伟达", "算力", "artificial intelligence"]),
    ("tech", ["科技", "科学", "航天", "卫星", "火箭", "量子", "互联网", "数码", "机器人",
              "新能源", "电池", "芯片", "5g", "6g", "手机", "电脑"]),
    ("fin", ["财经", "经济", "金融", "股市", "a股", "楼市", "房价", "贷款", "利率", "消费",
             "财报", "营收", "央行", "economy", "market"]),
    ("cn", ["国内", "时政", "政策", "国务院", "印发", "部署", "条例", "规划", "视察"]),
    ("intl", ["国际", "全球", "海外", "美国", "欧盟", "欧洲", "日本", "韩国", "联合国",
              "俄乌", "中东", "world"]),
    ("edu", ["教育", "高考", "中考", "大学", "高校", "考研", "学生", "教师", "学校", "招生", "职业教育"]),
    ("cul", ["文化", "文物", "遗产", "博物馆", "影视", "电影", "演出", "艺术", "文旅", "非遗"]),
    ("sport", ["体育", "足球", "篮球", "国足", "奥运", "赛事", "世界杯", "亚运", "夺冠", "联赛"]),
    ("life", ["民生", "健康", "医疗", "医保", "天气", "交通", "旅游", "美食", "养老", "就业", "社保"]),
]

# 国内可直连的源。prefer = 该源的主标签（关键词归不出类时的兜底）
FEEDS = [
    {"url": "https://www.chinanews.com.cn/rss/scroll-news.xml", "name": "中新网", "prefer": "cn"},
    {"url": "https://www.chinanews.com.cn/rss/society.xml", "name": "中新网社会", "prefer": "life"},
    {"url": "https://www.chinanews.com.cn/rss/world.xml", "name": "中新网国际", "prefer": "intl"},
    {"url": "https://www.chinanews.com.cn/rss/finance.xml", "name": "中新网财经", "prefer": "fin"},
    {"url": "https://www.chinanews.com.cn/rss/sports.xml", "name": "中新网体育", "prefer": "sport"},
    {"url": "https://www.chinanews.com.cn/rss/culture.xml", "name": "中新网文化", "prefer": "cul"},
    {"url": "https://www.chinanews.com.cn/rss/edu.xml", "name": "中新网教育", "prefer": "edu"},
    {"url": "https://www.chinanews.com.cn/rss/health.xml", "name": "中新网健康", "prefer": "life"},
    {"url": "https://www.ithome.com/rss/", "name": "IT之家", "prefer": "tech"},
    {"url": "https://www.geekpark.net/rss", "name": "极客公园", "prefer": "ai"},
]

CST = datetime.timezone(datetime.timedelta(hours=8))


def today():
    return datetime.datetime.now(CST).strftime("%Y-%m-%d")


def now_iso():
    return datetime.datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def strip_html(t):
    t = re.sub(r"<[^>]+>", " ", t or "")
    return re.sub(r"\s+", " ", t).strip()


def clean_sum(desc, title):
    """摘要清洗：去 HTML → 去电头（"中新网X月X日电 (记者…)"）→ 截断。
    去掉电头后若太短，说明正文就在电头里，则回退保留原文。"""
    s = strip_html(desc)
    if not s:
        return ""
    if s.startswith(title[:20]):
        s = s[len(title[:20]):].strip()
    # 「电」必须出现才当电头，否则会误吃掉 "IT之家 10 月 1 日" 只留下 "消息，"
    headless = re.sub(r"^[^，。；]*?\d+\s*月\s*\d+\s*日电\s*(\([^)]*\)\s*)?", "", s)
    headless = re.sub(r"^(IT之家|快科技|cnbeta)\s*\d+\s*月\s*\d+\s*日消息[，,]?\s*", "", headless)
    headless = headless.strip(" ，,。;；")
    if len(headless) >= 15:
        s = headless
    # 正文没抓到、只剩记者署名时不显示（比显示 "实习生 张皓宇" 强）
    if len(s) < 45 and re.search(r"^(记者|实习生|通讯员|编辑|文/|来源[:：])", s):
        return ""
    return s[:90]


def tag_of(text):
    t = (text or "").lower()
    for key, words in KEYWORDS:
        for word in words:
            if len(word) <= 5 and re.match(r"^[a-z0-9]+$", word):
                if re.search(r"(^|[^a-z0-9])%s([^a-z0-9]|$)" % re.escape(word), t):
                    return key
            elif word in t:
                return key
    return None


def install_proxy():
    """本机网络受限时的兜底：从 macOS 系统设置里读代理。正常情况不需要。"""
    if os.environ.get("http_proxy") or os.environ.get("https_proxy"):
        return False
    try:
        out = subprocess.run(["scutil", "--proxy"], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return False
    if not re.search(r"HTTPEnable\s*:\s*1", out):
        return False
    host = re.search(r"HTTPProxy\s*:\s*(\S+)", out)
    port = re.search(r"HTTPPort\s*:\s*(\d+)", out)
    if host and port and port.group(1) != "0":
        p = "http://%s:%s" % (host.group(1), port.group(1))
        os.environ["http_proxy"] = p
        os.environ["https_proxy"] = p
        print("[i] 已启用系统代理 %s 重试" % p)
        return True
    return False


def fetch(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (daily-news-bot)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_all(urls, workers=8):
    """并发抓取，失败返回 None，避免被单个慢源拖住"""
    from concurrent.futures import ThreadPoolExecutor
    out = {}

    def one(u):
        try:
            return u, fetch(u)
        except Exception as e:
            print("[!] 抓取失败 %s (%s)" % (u[:60], e))
            return u, None

    if not urls:
        return out
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for u, body in ex.map(one, urls):
            out[u] = body
    return out


def parse_xml(xml_bytes, source, prefer):
    """解析 RSS，返回条目列表；归不出标签时用 prefer 兜底"""
    out = []
    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        return out
    for item in root.iter("item"):
        title = strip_html(item.findtext("title") or "")
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        if link.startswith("http://"):
            link = "https://" + link[7:]      # 页面是 https，尽量给安全链接
        desc = clean_sum(item.findtext("description") or "", title)
        tag = tag_of(title + " " + desc) or prefer
        out.append({
            "title": title[:80],
            "sum": desc,
            "url": link,
            "source": source,
            "tag": tag,
        })
    return out


def interleave(items):
    """同一标签内按来源轮流，避免 5 条全来自同一个源"""
    groups, order = {}, []
    for it in items:
        s = it["source"]
        if s not in groups:
            groups[s] = []
            order.append(s)
        groups[s].append(it)
    out, i = [], 0
    while len(out) < len(items):
        for s in order:
            if i < len(groups[s]):
                out.append(groups[s][i])
        i += 1
    return out


def collect():
    """按标签各抓 PER_TAG 条，返回 (news, 统计信息)"""
    bodies = fetch_all([f["url"] for f in FEEDS])
    buckets, seen = {}, set()
    for f in FEEDS:
        body = bodies.get(f["url"])
        if not body:
            continue
        for it in parse_xml(body, f["name"], f["prefer"]):
            k = it["title"][:40]
            if k in seen:
                continue
            seen.add(k)
            buckets.setdefault(it["tag"], []).append(it)

    news, stats = [], {}
    for tag in TAG_ORDER:
        take = interleave(buckets.get(tag, []))[:PER_TAG]
        news += take
        stats[tag] = len(take)
    return news, stats


def main():
    t = today()
    force = "--force" in sys.argv
    if not force and os.path.exists(LATEST):
        try:
            old = json.load(open(LATEST, encoding="utf-8"))
            if str(old.get("date")) == t and old.get("news"):
                print("[i] data/latest.json 已是 %s 的数据，跳过（加 --force 可强制重抓）" % t)
                return 0
        except Exception:
            pass

    news, stats = collect()
    if not news:                      # 全挂了才考虑走代理重试
        print("[!] 直连全部失败，尝试代理…")
        if install_proxy():
            news, stats = collect()
    print("[i] 各标签条数: " + " ".join("%s=%d" % (k, v) for k, v in stats.items()))
    if not news:
        print("[x] 所有源都抓不到，放弃写入")
        return 1

    obj = {
        "date": t,
        "generatedAt": now_iso(),
        "generator": "github-actions-rss",
        "perTag": PER_TAG,
        "news": news,
    }
    os.makedirs(DATA, exist_ok=True)
    with open(LATEST, "w", encoding="utf-8") as fp:
        json.dump(obj, fp, ensure_ascii=False, indent=2)
    os.makedirs(os.path.join(DATA, "archive"), exist_ok=True)
    with open(os.path.join(DATA, "archive", t + ".json"), "w", encoding="utf-8") as fp:
        json.dump(obj, fp, ensure_ascii=False, indent=2)
    print("[v] 已写入 %d 条 %s 的新闻" % (len(news), t))
    return 0


if __name__ == "__main__":
    sys.exit(main())
