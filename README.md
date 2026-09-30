# 晨间学习台 · 新闻 + 背单词

一个纯静态的单文件网页应用：每日新闻导入 + 艾宾浩斯单词复习。

打开即用，无需注册、无需后端、无需联网（新闻链接跳转除外）。

## 功能

- **今日新闻**：粘贴结构化新闻文本，或拖入 `daily-*.json`，自动解析成带原文链接的卡片
- **英语学习**：单词自测（中文释义 → 拼英文）、今日新词、单词分区、统计与错词本
- **词库分级**：小学 708 / 初中 2194 / 高考 3943 / 四级 4555 / 六级 4344 / 考研 5017，共 2 万余词
  - 每库再分「基础 / 进阶 / 高分」三档，可任意组合
  - 掌握状态以单词为键全局共享：在四级标过「已掌握」的词，切到高考会自动跳过
- **单词分区**：未学 / 学习中 / 今日待复习 / 已掌握，支持搜索与手动移动
- **艾宾浩斯调度**：答对按 1→2→4→7→15→30 天递进，答错归零并次日重考
- **主题**：日间 7 套 + 夜间 6 套，选择自动持久化

## 部署到 GitHub Pages（零基础逐条版）

最终会得到这个网址：`https://Liuzr-523.github.io/morning/`

**要用的文件**：`publish/index.html`（和根目录 `index.html` 是同一份，1.5MB 单文件，已包含全部词库）

### 第 1 步：打开 GitHub Desktop 并登录
- 打开 `/Applications/GitHub Desktop`
- 如果提示登录，选 `Sign in to GitHub.com`，用浏览器授权
- 这一步只能你自己做，别人没法替你登录

### 第 2 步：新建仓库
- `File → New repository…`
- **Name**：`morning`
- **Local Path**：用默认即可（一般是 `~/Documents/GitHub`）
- 勾选 `Initialize this repository with a README`
- 点 `Create repository`

### 第 3 步：把网页放进仓库文件夹
- 菜单栏 `Repository → Show in Finder`（或界面上的 `Show in Finder`）
- 把 `publish/index.html` 拖进打开的文件夹
- 顺便把 `.nojekyll` 也拖进去（Finder 里按 `Cmd + Shift + .` 才看得到隐藏文件）

### 第 4 步：提交
- 回到 GitHub Desktop，左下角 Summary 填 `上线晨间学习台`
- 点 `Commit to main`

### 第 5 步：发布到 GitHub
- 顶部点 `Publish repository`
- **不要**勾 `Keep this code private`（免费版 Pages 必须公开仓库）
- 点 `Publish repository` 确认

### 第 6 步：开启 Pages
- 浏览器打开 `https://github.com/Liuzr-523/morning`
- `Settings` → 左侧 `Pages`
- Source 选 `Deploy from a branch`，Branch 选 `main`、目录选 `/(root)`
- 点 `Save`

### 第 7 步：等它生效
等 1–2 分钟，访问 `https://Liuzr-523.github.io/morning/`

没出来的话去仓库的 `Actions` 标签看有没有红色报错。

---

> **为什么用独立仓库**：不要放进已有的 `liuzr-523.github.io` 博客仓库——那个仓库开了 Jekyll，混放会互相干扰。
>
> `.nojekyll` 的作用是告诉 GitHub 别用 Jekyll 重新处理这个页面。

## 数据说明

- 所有学习进度存在**浏览器 localStorage**，不同浏览器 / 不同设备之间不互通
- 换设备或清缓存会丢失进度，请用「统计 / 数据」页的**导出 / 导入 JSON**做备份
- 页面本身不收集、不上传任何数据

## 与 WorkBuddy 定时任务联动

见同目录上级的 `定时任务-Prompt.md`：让 Agent 每天生成固定格式的 `daily-YYYY-MM-DD.json`，
用户把文件拖进页面即可导入当日新闻与单词。


---

## 新闻每天自动更新（06:30）

### 架构：谁在什么时候做什么

```
每天 06:30  WorkBuddy 定时任务 ──搜索当天新闻──> 写 data/latest.json ──> git commit + push
                                                                              │
每天 06:35  GitHub Actions（云端）──若当天数据缺失──> 用 RSS 补写 ──> 自动 push │
                                                                              ▼
                                              GitHub Pages 把仓库当静态站点发布
                                                                              │
                                            网页打开时 fetch data/latest.json ─┘
```

**关键点**：GitHub Pages 只能放静态文件，它自己不会"跑任务"。所以定时任务必须跑在别处——
主任务跑在 WorkBuddy（能搜索、能写内容），兜底任务跑在 GitHub 云端（不怕你电脑关机）。

### 定时任务创建在哪 / 配置在哪个文件

| 任务 | 创建位置 | 配置文件 | 时间写法 |
|---|---|---|---|
| 主任务（生成新闻） | WorkBuddy 应用 →「自动化」面板 | 数据存 `~/.workbuddy`，日志 `~/.workbuddy/logs/automation.log` | RRULE：`FREQ=DAILY;BYHOUR=6;BYMINUTE=30` |
| 兜底任务（RSS 补写） | 随仓库一起提交 | `.github/workflows/daily-news.yml` | cron：`cron: '35 22 * * *'` |
| 本机 cron（可选） | `crontab -e` | — | `30 6 * * * cd /Users/liuzirui/Documents/GitHub/morning && /usr/bin/python3 tools/publish_news.py` |

⚠️ **GitHub Actions 的 cron 用 UTC**。北京时间 = UTC+8，所以北京时间 06:30 要写成 `30 22 * * *`（前一天 22:30 UTC）。
另外 GitHub 的定时任务不保证准点，通常延迟 0–15 分钟，负载高时可能跳过——所以它只作兜底。

### 新闻数据格式

主数据 `data/latest.json`（每天覆盖）：

```json
{
  "date": "2026-09-30",
  "generatedAt": "2026-09-30T06:30:12+08:00",
  "generator": "workbuddy-daily-news",
  "news": [
    {"title":"标题","sum":"一句话摘要","url":"https://原文链接","source":"新华社","tag":"科技"}
  ]
}
```

- `date` 必须是**北京时间**当天；`url` 必须是真实链接（脚本会校验，缺 title 或以非 http 开头会报错）
- 每天同时归档一份到 `data/archive/<date>.json`，前端回退时用
- `generator` 字段区分来源：`workbuddy-daily-news`（AI 生成）或 `github-actions-rss`（RSS 兜底）

### 标签（用户可以只看自己关心的领域）

页面在新闻列表上方显示一排标签，点一下就只看这一类（**可多选**），勾选结果存在浏览器本地（`S.newsTags`），换个浏览器/换个人互不影响。

**标准标签只有 10 个，写数据时请从中选，不要自造词**（自造词会落进「其他」）：

| tag | 含义 | tag | 含义 |
|---|---|---|---|
| `ai` | AI / 大模型 / 算力 | `edu` | 教育 / 高考 |
| `tech` | 科技 / 航天 / 新能源 | `cul` | 文化 / 文物 / 影视 |
| `fin` | 财经 / 股市 / 楼市 | `sport` | 体育 / 赛事 |
| `cn` | 国内 / 时政 | `life` | 生活 / 民生 / 健康 |
| `intl` | 国际 / 海外 | `other` | 兜底（尽量少用） |

归类逻辑在 `index.html` 的 `tagOf()`：
1. 标题/摘要/来源命中 AI 关键词 → `ai`（AI 优先，方便单独关注）
2. 数据自带的 `tag` 命中标准值或常见别名（民生→`life`、时政→`cn`…）→ 用该值
3. 再按其它关键词猜；都猜不到 → `other`

所以**旧数据不用改**：即使 `tag` 写的是"民生""科技"这类词，也能自动归到标准标签。
`tools/fetch_rss.py` 里有一份同样的词表，保证 RSS 兜底的新闻也带标签。

### 前端怎么读

打开页面时按优先级尝试，谁先成功用谁：

1. `data/latest.json`（日期是今天 → 显示「今日已更新」）
2. `data/archive/<今天>.json`（日期不是今天 → 显示「今日尚未更新，正在显示 X 月 X 日的数据」）
3. 浏览器本地缓存（上次成功的内容 → 显示「离线缓存」）
4. 都没有 → 显示「获取失败」并提示展开手动导入

页面顶部状态条会明确告诉你**数据是哪一天的、谁来生成的**，不会再出现"看着像新的其实是旧的"。

### 手动触发一次（验证用）

```bash
cd /Users/liuzirui/Documents/GitHub/morning
/usr/bin/python3 tools/publish_news.py          # 校验+归档+提交+推送
/usr/bin/python3 tools/publish_news.py --no-push # 只提交不推送
```

兜底任务也可以手动触发：GitHub 仓库页面 → `Actions` → `daily-news` → `Run workflow`。

脚本退出码：`0` 成功 / `1` 数据校验失败 / `2` 提交或推送失败（提交会保留在本地）。

### 没按时执行 / 失败了怎么查

| 现象 | 先查这里 |
|---|---|
| 网页显示「今日尚未更新」 | 说明拿到的是旧文件：看 GitHub 仓库里 `data/latest.json` 的 `date` 字段是不是今天 |
| 仓库里根本没有当天文件 | WorkBuddy 自动化没跑成：看 `~/.workbuddy/logs/automation.log`；确认 06:30 电脑没关机、WorkBuddy 在运行 |
| 文件在本地但线上没有 | 推送失败：在仓库目录跑 `git status -sb`，显示 `ahead N` 就是没推上去 |
| 推送报 could not read Username | 缺凭据，见下面的 PAT 配置 |
| 推送报 HTTP2 framing / CONNECT 502 | 网络代理问题，脚本已自动尝试系统代理；仍失败就手动跑 `git -c http.proxy=http://127.0.0.1:6696 push` |
| Actions 没跑 | GitHub → Actions 页面看运行记录；免费账号仓库 60 天无任何提交时会自动停用定时任务 |
| 兜底也没补上 | 手动跑 `python3 tools/fetch_rss.py` 看 RSS 源是否还能抓 |

**三层兜底保证网站不会空**：WorkBuddy 没跑 → Actions 用 RSS 补；Actions 也失败 → 前端显示昨天的存档 + 明确提示；全都失败 → 还能手动导入。

### 一次性凭据配置（不配也能用，配了才零点击）

不配 PAT 时：自动化会生成并**提交到本地**，你在 GitHub Desktop 点一下 `Push` 即可上线；
同时 GitHub Actions 的 RSS 兜底**不受影响**，网站照样每天自动更新。

想做到完全零点击，创建一个 Personal Access Token 并存进钥匙串：

1. GitHub 网页 → 右上角头像 → `Settings` → `Developer settings` → `Personal access tokens` → `Tokens (classic)` → `Generate new token (classic)`
2. 勾 `repo`（或细粒度 token 只勾 `morning` 仓库的 `Contents: Read and write`），过期选 `No expiration`
3. 生成后**复制那串 token**（关掉页面就看不见了）
4. 在终端执行下面两条（把 `<TOKEN>` 换成刚复制的串）：

```bash
git config --global credential.helper osxkeychain
printf 'protocol=https\nhost=github.com\nusername=Liuzr-523\npassword=<TOKEN>\n' | git credential-osxkeychain store
```

5. 验证：`cd /Users/liuzirui/Documents/GitHub/morning && /usr/bin/python3 tools/publish_news.py` 应输出「已推送」
