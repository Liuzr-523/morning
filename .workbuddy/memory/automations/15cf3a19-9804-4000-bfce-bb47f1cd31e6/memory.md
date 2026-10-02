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

## 2026-10-02
- 未命中前置条件（本地 date 仍为 2026-10-01）→ 正常执行全流程。
- fetch_rss.py --force 抓到 45 条（9 个标签各 5 条，**other 恒为 0**：脚本不会主动打兜底标签，这是常态，需靠搜索补）。
- WebSearch 补 5 条 other（娱乐/社会奇闻/动物趣闻），均取自搜索结果实际 URL。注意：搜索引擎索引滞后，今晨 6:30 查询 dated 仍显示 2026-10-01，10-02 新稿很少。
- publish_news.py 退出码 **2**：校验通过、已本地提交 `db1c062`，推送失败 —— `fatal: could not read Username for 'https://github.com'`。
  - 根因是 **GitHub 凭据缺失/失效**（remote 为 https://github.com/Liuzr-523/morning.git，credential.helper=osxkeychain 但取不到用户名），**不是代理问题**，重跑脚本不会自愈。
  - 需用户在 GitHub Desktop 点 Push，或重新在钥匙串/凭据助手里配置 GitHub 账号。
- **下午复查发现分支已分叉**：远端多出 `b4b789c news: RSS 兜底补写当日新闻`（Actions 当日 09:46 自己推的一版，45 条、9 标签、无 other）。
  - 处理：`git reset --hard origin/main` 丢掉本地那份，改写为「远端 45 条 + 我的 5 条 other」= 50 条，经 publish_news.py 重新提交为 `f1ca6ed`。
  - 结果：本地 = origin/main + 1，**可快进推送**，待用户点 Push。
- **两条重要教训（下次必看）**：
  1. 本仓库 daily 流程由 GitHub Actions 在**当天上午**自行产出并推送。本地定时任务若跑在其之前（如 06:30），必然与 Actions 分叉 → 一律先 `git fetch` 看 behind，behind 就把 Actions 版当底座、只在上面补 other 标签，别硬推自己那版。
  2. 本机 **没有可用的 GitHub 推送凭据**（无 gh CLI、无 GITHUB_TOKEN、osxkeychain 里无 github.com 记录），`git push` 必失败且不会自愈；推送只能由用户在 GitHub Desktop 完成。用 GitHub connector 的 push_files 虽然可写远端，但要内联 20KB+ 全文，不可取。

## 2026-10-01
- 命中前置条件：date=2026-10-01，共 50 条，10 个标签各 5 条（ai/tech/fin/cn/intl/edu/cul/sport/life/other）。
- generator=github-actions-rss（说明本次数据由仓库的 GitHub Actions RSS 流程产出，而非本地 fetch_rss.py）。
- 工作区干净，`main...origin/main` 无 ahead/behind，已有提交 `909de2a news(2026-10-01): 50 条当日新闻` 且已推送。
- 结论：跳过抓取、跳过补充、跳过 publish_news.py，未改动任何文件。
- 注意：该仓库新闻已改由 GitHub Actions 自动产出，本地定时任务大概率只起"兜底/校验"作用；若 Actions 正常，本地几乎总命中"已跑过"分支。
