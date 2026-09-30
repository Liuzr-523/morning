#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按标签抓取当日新闻：每个标准标签各抓 PER_TAG 条（默认 5 条）。

两个用途：
  1) GitHub Actions 兜底：WorkBuddy 定时任务没跑（关机 / 推送失败）时自动补数据
  2) 本地手动执行：`python3 tools/fetch_rss.py`，可加 --force 忽略“今天已有数据”

抓取策略（每标签依次尝试，凑满为止）：
  ① Google News RSS 按关键词搜索（在 Actions 的境外网络里可用）
  ② 固定 RSS 源里挑出命中该标签关键词的条目
实在凑不满就少几条，绝不编造标题或链接。
"""
import datetime
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
LATEST = os.path.join(DATA, "latest.json")

PER_TAG = 5  # 每个标签抓取条数

# 标准标签：与网页 index.html 里的 NEWS_TAGS 保持一致
TAGS = [
    ("ai", ["人工智能", "大模型", "生成式AI", "算力 芯片 AI"]),
    ("tech", ["科技", "航天 卫星", "量子 科研", "新能源 汽车"]),
    ("fin", ["财经", "A股 股市", "央行 利率", "经济 消费"]),
    ("cn", ["国内新闻", "国务院 政策", "时政", "中国 民生政策"]),
    ("intl", ["国际新闻", "联合国", "欧盟", "中东 局势"]),
    ("edu", ["教育", "高考", "高校 大学", "考研 招生"]),
    ("cul", ["文化 文物", "博物馆 非遗", "电影 影视", "文旅 演出"]),
    ("sport", ["体育", "足球 国足", "篮球", "奥运 赛事"]),
    ("life", ["民生", "健康 医疗", "天气 交通", "就业 社保"]),
    # other 是网页上的兜底分类，不专门搜索，只接收确实归不了类的条目
    ("other", []),
]

# 关键词命中规则（用于给固定源的条目分类）
KEYWORDS = [
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

# 固定兜底源（Google News 不可用时）
FEEDS = [
    {"url": "https://www.chinanews.com.cn/rss/scroll-news.xml", "name": "中国新闻网"},
    {"url": "https://www.chinanews.com.cn/rss/finance.xml", "name": "中新网财经"},
    {"url": "https://www.chinanews.com.cn/rss/sports.xml", "name": "中新网体育"},
    {"url": "https://www.chinanews.com.cn/rss/culture.xml", "name": "中新网文化"},
    {"url": "https://feeds.bbci.co.uk/news/world/rss.xml", "name": "BBC News"},
    {"url": "https://feeds.bbci.co.uk/zhongwen/simp/rss.xml", "name": "BBC 中文"},
]


def today():
    return (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)).strftime("%Y-%m-%d")


def now_iso():
    return (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def strip_html(t):
    t = re.sub(r"<[^>]+>", "", t or "")
    return re.sub(r"\s+", " ", t).strip()


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
    """本机（国内网络）抓 Google News 需要代理。若环境没给，就从 macOS 系统设置里读。"""
    if os.environ.get("http_proxy") or os.environ.get("https_proxy"):
        return
    try:
        out = subprocess.run(["scutil", "--proxy"], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return
    if not re.search(r"HTTPEnable\s*:\s*1", out):
        return
    host = re.search(r"HTTPProxy\s*:\s*(\S+)", out)
    port = re.search(r"HTTPPort\s*:\s*(\d+)", out)
    if host and port and port.group(1) != "0":
        p = "http://%s:%s" % (host.group(1), port.group(1))
        os.environ["http_proxy"] = p
        os.environ["https_proxy"] = p
        print("[i] 已启用系统代理 %s" % p)


def fetch(url, timeout=12):
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
            print("[!] 抓取失败 %s (%s)" % (u[:72], e))
            return u, None

    if not urls:
        return out
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for u, body in ex.map(one, urls):
            out[u] = body
    return out


def gnews_url(query):
    q = urllib.parse.quote(query)
    return ("https://news.google.com/rss/search?q=%s&hl=zh-CN&gl=CN&ceid=CN:zh-Hans" % q)


def parse_xml(xml_bytes, default_source, want=None):
    """解析 RSS；want 为标签时，只在该标签下才收（Google News 搜索结果直接全收）"""
    out = []
    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        return out
    for item in root.iter("item"):
        title = strip_html(item.findtext("title") or "")
        link = (item.findtext("link") or "").strip()
        desc = strip_html(item.findtext("description") or "")
        source = default_source
        # Google News 的标题格式：正文标题 - 媒体名
        m = re.search(r"\s+-\s+([^-]{2,30})$", title)
        if m and default_source == "聚合新闻":
            source = m.group(1).strip()
            title = title[: m.start()].strip()
        if not title or not link:
            continue
        # Google News 的 description 只是「标题 + 来源」的重复，去掉
        if desc and (desc.startswith(title) or desc.startswith(title[:30])):
            desc = ""
        tag = tag_of(title + " " + desc)
        if want and tag and tag != want:
            continue
        out.append({
            "title": title[:80],
            "sum": desc[:90],
            "url": link,
            "source": source or "聚合新闻",
            "tag": tag or want or "other",
        })
    return out


def collect():
    """按标签各抓 PER_TAG 条，返回 (news, 统计信息)"""
    news = []
    seen = set()
    stats = {}

    def add(items, tag):
        got = 0
        for it in items:
            k = it["title"][:40]
            if k in seen or not wanted(it, tag):
                continue
            seen.add(k)
            it = dict(it)
            it["tag"] = tag
            news.append(it)
            got += 1
            if got >= PER_TAG:
                break
        return got

    # 一次性并发抓取：每个标签的 Google News 查询 + 固定兜底源
    jobs = []
    for tag, queries in TAGS:
        for q in queries:
            jobs.append((tag, gnews_url(q), "聚合新闻", None))
    for f in FEEDS:
        jobs.append((None, f["url"], f["name"], None))

    print("[i] 并发抓取 %d 个源…" % len(jobs))
    bodies = fetch_all([j[1] for j in jobs])

    # 解析后按 (标签 → 查询顺序) 归位
    gnews_by_tag = {}
    fixed = []
    for tag, url, name, _ in jobs:
        body = bodies.get(url)
        if not body:
            continue
        items = parse_xml(body, name)
        if tag is None:
            fixed += items
        else:
            gnews_by_tag.setdefault(tag, []).extend(items)

    for tag, _queries in TAGS:
        got = add(gnews_by_tag.get(tag, []), tag)
        if got < PER_TAG:                       # 兜底：从固定源里挑命中该标签的
            got += add([x for x in fixed if x.get("tag") == tag], tag)
        stats[tag] = got

    return news, stats


def wanted(it, tag):
    """Google News 搜索结果可能出现跑题条目：标题/摘要没命中该标签关键词就丢掉。
       other 标签本就是兜底，不做限制。"""
    if tag == "other":
        return True
    hit = tag_of(it.get("title", "") + " " + it.get("sum", ""))
    return hit is None or hit == tag


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

    install_proxy()
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
