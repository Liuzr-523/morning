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
import email.utils
import gzip
import json
import os
import re
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

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


# ==================== AI 标签专用：实验室一手 + 论文 ====================
# 用户明确要求：ai 只推实验室 / 厂商官方发布 + arXiv 论文，不要"某媒体写 AI 赋能 XX"。
# 所以 ai 桶完全不走上面的通用新闻源，只用下面三类一手渠道。
AI_PER_TAG = 15        # ai 标签条数
OFFICIAL_DAYS = 10     # 官方博文取最近几天（实验室不是日更，太窄会一条都抓不到）
OFFICIAL_MAX = 7       # 官方最多占几条
MODEL_MAX = 3          # 新模型最多占几条
MODEL_DAYS = 21        # Hugging Face 新模型取最近几天
PAPER_MAX = 8          # 论文最多补几条

# OpenAI RSS 的 category：只保留"发东西/做研究"的，客户故事、公司动态一律不要
OPENAI_OK_CATS = {"Product", "Research", "Engineering", "Release", "API", "Publication",
                  "Safety", "Safety & Alignment", "Security", "ChatGPT", "Guides", "Release notes"}

# 官方博客源。kind=rss 走标准 RSS；anthropic 是官网列表页（它没提供 RSS）
AI_OFFICIAL = [
    {"name": "OpenAI", "url": "https://openai.com/news/rss.xml", "kind": "rss"},
    {"name": "Anthropic", "url": "https://www.anthropic.com/news", "kind": "anthropic"},
    {"name": "Qwen 通义千问", "url": "https://qwenlm.github.io/blog/index.xml", "kind": "rss"},
    {"name": "Google", "url": "https://blog.google/technology/ai/rss/", "kind": "rss",
     "ai_only": True},
    {"name": "微软研究院", "url": "https://www.microsoft.com/en-us/research/feed/",
     "kind": "rss", "ai_only": True},
]

# Hugging Face 上各实验室的官方账号，新模型发布的最权威出处（含腾讯、DeepSeek、智谱、Kimi 等）
HF_ORGS = [
    ("deepseek-ai", "DeepSeek"), ("Qwen", "阿里通义"), ("openai", "OpenAI"),
    ("meta-llama", "Meta"), ("google", "Google"), ("zai-org", "智谱"),
    ("moonshotai", "月之暗面"), ("MiniMaxAI", "MiniMax"), ("tencent", "腾讯"),
    ("mistralai", "Mistral"), ("microsoft", "微软"), ("baichuan-inc", "百川"),
    ("01-ai", "零一万物"), ("stepfun-ai", "阶跃星辰"), ("BAAI", "智源"),
]

# 「赋能 / 落地 / 客户案例」这类一律丢掉（中英文都列）
BAD_WORDS = [
    "赋能", "落地", "产业化", "数字化转型", "助力", "签约", "战略合作", "生态伙伴",
    "白皮书", "市场规模", "应用场景", "智慧", "试点", "示范", "客户成功", "案例",
    "empower", "digital transformation", "transformation", "partners with", "partnership",
    "customer story", "case study", "case studies", "put ai to work", "reimagining",
    "nonprofit", "small business", "webinar", "client experience", "operations",
    "enterprise", "productivity", "donat", "academy", "policy", "regulation",
    "election", "philanthrop", "foundation", "coalition", "task force", "initiative to",
    "frees up", "hours a week", "grow with", "faster with", "with gpt", "with codex",
    "with chatgpt", "boosts", "saves", "2x faster", "are you a", "watch the", "trailer",
    "xprize", "scales claude", "accenture", "barclays", "client experience",
    "customer calls", "of customer", "resolve up to", "with openai", "customer support",
]

# 技术侧关键词：微软研究院这种综合源靠它筛出 AI 相关
TECH_WORDS = [
    "model", "llm", "gpt", "claude", "gemini", "llama", "qwen", "deepseek", "glm", "kimi",
    "mistral", "sora", "weights", "open-source", "open source", "open weights", "benchmark",
    "training", "pretraining", "pre-training", "fine-tun", "inference", "reasoning",
    "agent", "context window", "token", "api", "pricing", "research", "alignment",
    "interpretability", "distillation", "quantization", "moe", "reinforcement learning",
    "rlhf", "eval", "evaluation", "checkpoint", "sota", "architecture", "diffusion",
    "embedding", "gpu", "tpu", "latency", "throughput", "multimodal", "reasoner",
    "transformer", "attention", "neural", "dataset", "论文", "模型", "大模型", "开源",
    "训练", "推理", "智能体", "基准", "架构", "多模态", "权重",
]


def http_get(url, timeout=20):
    """带 gzip 解压的抓取（部分站点强制压缩）"""
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (daily-news-bot)", "Accept-Encoding": "gzip"})
    resp = urllib.request.urlopen(req, timeout=timeout)
    body = resp.read()
    if resp.headers.get("Content-Encoding") == "gzip":
        try:
            body = gzip.decompress(body)
        except Exception:
            pass
    return body


def parse_when(s):
    """尽力解析各种日期格式为 UTC datetime，失败返回 None"""
    if not s:
        return None
    s = s.strip()
    try:                                   # RFC 822：Tue, 29 Sep 2026 10:00:00 GMT
        return datetime.datetime(*email.utils.parsedate(s)[:6])
    except Exception:
        pass
    try:                                   # ISO：2026-09-29T10:00:00+00:00
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        pass
    for fmt in ("%b %d, %Y", "%Y-%m-%d", "%d %b %Y"):   # Oct 1, 2026
        try:
            return datetime.datetime.strptime(s, fmt)
        except Exception:
            pass
    return None


def ai_clean(s, n=140):
    t = re.sub(r"<[^>]+>", " ", s or "")
    t = re.sub(r"&[a-z]+;", " ", t)
    return re.sub(r"\s+", " ", t).strip()[:n]


def ai_is_bad(text):
    t = (text or "").lower()
    for w in BAD_WORDS:
        if w in t:
            return True
    return False


def ai_is_tech(text):
    t = (text or "").lower()
    for w in TECH_WORDS:
        if w in t:
            return True
    return False


def ai_from_rss(body, name, ai_only=False):
    """标准 RSS → 条目。OpenAI 额外按 category 过滤掉客户故事类。"""
    out = []
    try:
        root = ET.fromstring(body)
    except Exception:
        return out
    for item in root.iter("item"):
        title = ai_clean(item.findtext("title") or "", 80)
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        cat = (item.findtext("category") or "").strip()
        if name == "OpenAI" and cat and cat not in OPENAI_OK_CATS:
            continue                        # 公司动态 / 客户故事 / 全球事务 → 不要
        desc = ai_clean(item.findtext("description") or "", 150)
        when = parse_when(item.findtext("pubDate"))
        if ai_only and not ai_is_tech(title + " " + desc):
            continue
        out.append({"title": title, "sum": desc, "url": link, "source": name,
                    "tag": "ai", "when": when})
    return out


def ai_from_anthropic(body):
    """Anthropic 官网没有 RSS，从列表页里抓：<a href="/news/x">…<time>日期</time>…<span class=*title*>标题</span>"""
    out = []
    h = body.decode("utf-8", "ignore")
    for m in re.finditer(r'<a href="(/news/[^"#?]+)"[\s\S]{0,900}?</a>', h):
        seg = m.group(0)
        ti = re.search(r'<span class="[^"]*title[^"]*"[^>]*>([^<]+)</span>', seg)
        if not ti:
            continue
        title = ai_clean(ti.group(1), 80)
        tm = re.search(r'<time[^>]*>([^<]+)</time>', seg)
        out.append({"title": title, "sum": "", "url": "https://www.anthropic.com" + m.group(1),
                    "source": "Anthropic", "tag": "ai", "when": parse_when(tm.group(1) if tm else "")})
    return out


def cap_per_source(items, n):
    """同一家最多 n 条：OpenAI 几乎日更，不限制会把 Anthropic / Qwen 全挤掉"""
    cnt, out = {}, []
    for it in items:
        c = cnt.get(it["source"], 0)
        if c >= n:
            continue
        cnt[it["source"]] = c + 1
        out.append(it)
    return out


def ai_official_news(days=OFFICIAL_DAYS):
    """实验室 / 厂商官方博客：并行抓，按时间倒序，过滤赋能类"""
    cutoff = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(days=days)
    out, seen = [], set()

    def one(f):
        try:
            body = http_get(f["url"])
        except Exception as e:
            print("[!] AI 源抓取失败 %s (%s)" % (f["name"], e))
            return []
        if f["kind"] == "anthropic":
            return ai_from_anthropic(body)
        return ai_from_rss(body, f["name"], f.get("ai_only", False))

    with ThreadPoolExecutor(max_workers=len(AI_OFFICIAL)) as ex:
        for items in ex.map(one, AI_OFFICIAL):
            for it in items:
                k = it["title"][:40].lower()
                if k in seen:
                    continue
                if ai_is_bad(it["title"] + " " + it["sum"]):
                    continue
                if it["when"] and it["when"] < cutoff:
                    continue               # 只留最近 days 天的一手消息
                seen.add(k)
                out.append(it)
    out.sort(key=lambda x: x["when"] or datetime.datetime.min, reverse=True)
    return out


def ai_model_news(days=MODEL_DAYS):
    """Hugging Face 官方 API：各实验室最近公开的权重。真正的一手，且能覆盖腾讯/智谱等国内厂商。"""
    cutoff = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(days=days)
    out = []

    def one(org):
        try:
            body = http_get("https://huggingface.co/api/models?author=%s"
                            "&sort=createdAt&direction=-1&limit=5&full=false" % org[0], timeout=15)
            rows = json.loads(body)
        except Exception as e:
            print("[!] HF 模型接口失败 %s (%s)" % (org[0], e))
            return []
        items = []
        for m in rows:
            mid = m.get("modelId") or m.get("id") or ""
            when = parse_when((m.get("createdAt") or "")[:19])
            if not mid or not when or when < cutoff:
                continue
            name = mid.split("/")[-1]
            kind = m.get("pipeline_tag") or "模型"
            items.append({
                "title": "%s：%s 发布新模型（开源权重）" % (org[1], name),
                "sum": "发布于 %s · %s · %s 下载" % (when.strftime("%Y-%m-%d"), kind,
                                                 m.get("downloads") or 0),
                "url": "https://hf-mirror.com/models/" + mid,   # 国内直连镜像
                "source": org[1], "tag": "ai", "when": when})
        return items

    with ThreadPoolExecutor(max_workers=8) as ex:
        for items in ex.map(one, HF_ORGS):
            out += items
    out.sort(key=lambda x: x["when"] or datetime.datetime.min, reverse=True)
    return out


def ai_paper_news(maxn=PAPER_MAX):
    """论文：Hugging Face 每日热门（社区投票）优先，抓不到就退回 arXiv 最新。"""
    today = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d")
    out = []
    try:
        rows = json.loads(http_get("https://huggingface.co/api/daily_papers?date=%s" % today, timeout=15))
        for r in rows[:maxn]:
            p = r.get("paper") or {}
            pid = p.get("id") or ""
            title = ai_clean(p.get("title") or "", 80)
            if not pid or not title:
                continue
            out.append({
                "title": title,
                "sum": ai_clean(p.get("ai_summary") or p.get("summary") or "", 150),
                "url": "https://hf-mirror.com/papers/" + pid,
                "source": "arXiv · " + pid, "tag": "ai",
                "when": parse_when((p.get("publishedAt") or today)[:19])})
        if out:
            return out
    except Exception as e:
        print("[!] HF 每日论文失败 (%s)，改用 arXiv" % e)

    try:                                   # 兜底：arXiv cs.AI/cs.CL/cs.LG 最新
        url = ("http://export.arxiv.org/api/query?search_query="
               "cat:cs.AI+OR+cat:cs.CL+OR+cat:cs.LG&sortBy=submittedDate"
               "&sortOrder=descending&max_results=%d" % maxn)
        root = ET.fromstring(http_get(url, timeout=25))
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for e in root.findall("a:entry", ns):
            title = ai_clean(e.findtext("a:title", "", ns), 80)
            aid = (e.findtext("a:id", "", ns) or "").rsplit("/", 1)[-1]
            if not title or not aid:
                continue
            out.append({"title": title, "sum": ai_clean(e.findtext("a:summary", "", ns), 150),
                        "url": "https://arxiv.org/abs/" + aid, "source": "arXiv · " + aid,
                        "tag": "ai", "when": parse_when(e.findtext("a:published", "", ns))})
    except Exception as e:
        print("[!] arXiv 兜底也失败 (%s)" % e)
    return out


def ai_news():
    """ai 桶 = 官方发布 → 新模型 → 论文，凑到 AI_PER_TAG 条；按来源轮流，避免被一家包圆。"""
    official = cap_per_source(ai_official_news(), 3)[:OFFICIAL_MAX]
    models = ai_model_news()[:MODEL_MAX]
    news = interleave(official + models)
    need = AI_PER_TAG - len(news)
    papers = ai_paper_news(max(PAPER_MAX, need))[:need] if need > 0 else []
    news = (news + papers)[:AI_PER_TAG]
    for it in news:
        it.pop("when", None)
    print("[i] AI 构成: 官方 %d / 新模型 %d / 论文 %d → 共 %d"
          % (len(official), len(models), len(papers), len(news)))
    return news


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
    """按标签各抓条数：ai 走专用一手源（AI_PER_TAG 条），其余走国内新闻源（PER_TAG 条）"""
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
            if it["tag"] == "ai":
                continue               # ai 交给实验室一手源，媒体稿一律不进这个桶
            seen.add(k)
            buckets.setdefault(it["tag"], []).append(it)

    news, stats = [], {}
    for tag in TAG_ORDER:
        if tag == "ai":
            take = ai_news()
        else:
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
