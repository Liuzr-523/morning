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
