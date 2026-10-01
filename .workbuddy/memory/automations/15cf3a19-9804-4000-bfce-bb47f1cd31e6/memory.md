# 晨间学习台 · 每日新闻抓取发布 — 执行记录

## 判定前置条件（每次先做）
先检查 `data/latest.json` 的 `date` 是否为当天、`news` 总数是否 >= 30、各标签是否都 >= 3。
三者同时满足 → 当天已跑过，直接结束，不要重复抓取/重复提交。
判定命令（一步到位）：
```
cd /Users/liuzirui/Documents/GitHub/morning && /usr/bin/python3 -c "
import json;from collections import Counter
d=json.load(open('data/latest.json'));n=d.get('news',[])
print(d.get('date'), len(n), dict(Counter(x.get('tag') for x in n)))"
```
再 `git status -sb` 确认 main 与 origin/main 是否同步（无 ahead 即已推送）。

## 2026-10-01
- 命中前置条件：date=2026-10-01，共 50 条，10 个标签各 5 条（ai/tech/fin/cn/intl/edu/cul/sport/life/other）。
- generator=github-actions-rss（说明本次数据由仓库的 GitHub Actions RSS 流程产出，而非本地 fetch_rss.py）。
- 工作区干净，`main...origin/main` 无 ahead/behind，已有提交 `909de2a news(2026-10-01): 50 条当日新闻` 且已推送。
- 结论：跳过抓取、跳过补充、跳过 publish_news.py，未改动任何文件。
- 注意：该仓库新闻已改由 GitHub Actions 自动产出，本地定时任务大概率只起"兜底/校验"作用；若 Actions 正常，本地几乎总命中"已跑过"分支。
