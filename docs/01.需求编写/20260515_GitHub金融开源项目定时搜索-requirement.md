# GitHub 金融/银行业开源项目定时搜索 需求说明书

> 版本：v3.0 | 日期：2026-05-15 | 作者：黄康

## 一、功能概述

基于 **GitHub Actions** 定时（或手动）从 GitHub 搜索金融业/银行业相关开源项目，使用 **Python** 脚本调用 GitHub Search API，按可配置的筛选条件过滤，结果以 Markdown 文件提交回仓库并发布到 GitHub Pages，实现零服务器成本的金融科技开源项目情报收集。

---

## 二、用户场景

| 场景 | 角色 | 前置条件 | 操作 | 期望结果 |
|------|------|----------|------|----------|
| 每日自动搜集 | 技术负责人 | GitHub Actions workflow 已启用，schedule 已配置 | 无需人工干预，Actions 每日自动运行 | 仓库 `results/` 目录新增当日文件，GitHub Pages 自动更新 |
| 手动即时搜索 | 开发人员 | 想立即获取最新项目情报 | 在 GitHub Actions 页面点击 "Run workflow" 按钮 | 即时生成搜索结果文件并发布 |
| 调整筛选条件 | 运维人员 | 当前筛选条件不满足需求 | 修改仓库中的配置文件（`config/search.yml`）提交即可 | 下次运行按新条件执行 |
| 在线浏览结果 | 团队成员 | 想查看历史搜索结果 | 访问 GitHub Pages 站点 | 看到按日期组织的搜索结果页面 |

---

## 三、功能需求

### 3.1 GitHub 项目搜索（P0）

- **描述**：Python 脚本调用 GitHub Search API，按关键词搜索金融/银行业相关的开源仓库
- **输入**：
  - 搜索关键词：`banking`、`fintech`、`financial`（关键字列表可配置）
  - 编程语言：Java、Python（可配置，支持多语言）
- **输出**：符合条件的仓库列表（JSON 结构化数据）
- **业务规则**：
  - 使用 GitHub REST API v3 的 `/search/repositories` 端点
  - 单次请求最多返回 100 条，支持分页获取，本期上限 300 条（3 页），可配置
  - 使用 `GITHUB_TOKEN`（Actions 内置）或 Personal Access Token（Secrets 存储）认证，提升限速至 30 次/分钟
  - **关键词组合逻辑**：多个关键词以 OR 语义组合（`q=banking+fintech+financial`），即仓库描述中含任一关键词即命中；为提升精准度，脚本提供可选的二次筛选——按 `min_keyword_matches` 配置项（默认 1）过滤描述中至少包含 N 个关键词的仓库
  - **多语言搜索**：GitHub API 的 `language:` 限定符仅支持单一语言，不支持逗号分隔多语言。脚本遍历配置中的语言列表，**每种语言分别发起搜索请求**，再合并结果并去重
  - **结果排序**：配置中增加 `sort_by` 项（默认 `stars`），API 请求时传入 `sort` 参数；输出文件中项目按 Star 数降序排列
  - **结果去重**：多关键词或多语言分别搜索后，同一仓库可能重复出现。以仓库 `full_name`（如 `apache/fineract`）为唯一标识进行去重，仅保留一条记录

### 3.2 可配置筛选过滤（P0）

- **描述**：对搜索结果按配置文件中的条件过滤
- **输入**：搜索结果原始 JSON
- **输出**：符合所有筛选条件的项目列表
- **业务规则**：
  - 最低 Star 数（如 ≥ 100，通过 API 查询参数传递）
  - 最近更新时间（如 `pushed:>=2026-01-01`，通过 API 查询参数传递）
  - 编程语言（如 `language:Java`，通过 API 查询参数传递，脚本遍历语言列表逐个请求）
  - 以上三项均在 `config/search.yml` 中配置，修改后提交即生效
  - 默认排除 Fork 仓库（`fork:false`）
  - **可选过滤**：`created_after`（仓库创建时间，如 `>=2025-01-01`），作为可选配置项，本期默认不启用
  - **配置校验**：脚本启动时先校验配置项的类型与取值范围（如 `min_stars` 必须为非负整数），校验失败则打印明确错误信息并退出，不发起 API 请求

### 3.3 GitHub Actions 定时调度（P0）

- **描述**：通过 GitHub Actions workflow 实现自动/手动触发
- **输入**：
  - 定时触发：`schedule` cron 表达式（默认每日 UTC 18:00，即北京时间凌晨 2:00）
  - 手动触发：`workflow_dispatch` 事件
- **输出**：触发 Python 搜索脚本执行
- **业务规则**：
  - 使用 `.github/workflows/search.yml` 定义 workflow
  - `schedule` 支持 cron 精确到分钟，北京时间 = UTC + 8
  - `workflow_dispatch` 可在 GitHub 网页端一键触发
  - GitHub Actions 免费额度：公开仓库无限制，私有仓库 2000 分钟/月
  - **Git 提交身份**：Workflow 中 `git commit` 使用 `github-actions[bot]` 作为提交者（`user.name: github-actions[bot]`，`user.email: 41898282+github-actions[bot]@users.noreply.github.com`）
  - **Token 检测**：脚本启动时检测 `GITHUB_TOKEN` 环境变量是否已设置，若未设置则打印警告信息（将以匿名低限速运行），但不阻止执行

### 3.4 项目用途摘要（P0）

- **描述**：获取每个项目的简要用途说明
- **输入**：GitHub API 返回的仓库信息（含 `description` 字段）
- **输出**：每个项目附带一句用途说明
- **业务规则**：
  - **本期（轻量模式）**：直接使用 GitHub API 返回的 `description` 字段
  - 若 `description` 为空，标注为"无描述"
  - **预留扩展**：Python 脚本预留 `summarize_with_ai()` 函数入口，后续可对接 LLM 抓取 README 生成中文摘要

### 3.5 结果文件输出（P0）

- **描述**：搜索结果生成 Markdown 文件，提交回仓库并发布到 GitHub Pages
- **输入**：过滤后的项目列表
- **输出**：
  - 仓库 `results/` 目录下的 Markdown 文件
  - GitHub Pages 自动渲染的静态页面
- **业务规则**：
  - **方式 A — 提交回仓库**：
    - 输出目录：`results/`
    - 文件命名：`{YYYY-MM-DD}_{触发方式}.md`，如 `2026-05-15_SCHEDULED.md`、`2026-05-15_MANUAL.md`
    - 同日同触发方式多次运行：后一次覆盖前一次结果（仅保留最新）
    - Workflow 自动 `git add` → `git commit` → `git push`
    - 若输出目录不存在，脚本自动创建
  - **方式 C — GitHub Pages**：
    - 生成 `docs/index.md` 作为首页（列出所有历史搜索日期链接）
    - 生成 `docs/{YYYY-MM-DD}.md` 作为每日结果页（同日多次运行覆盖，仅保留最新）
    - `docs/index.md` 的维护方式：每次运行时扫描 `docs/` 目录下所有日期文件，**全量重新生成**索引页
    - 本期使用 GitHub Pages 原生 Markdown 渲染（零配置），不引入 Jekyll 主题或 MkDocs
    - 若输出目录不存在，脚本自动创建
  - **部分成功处理**：若分页获取中部分页面失败（如第 1 页成功、第 2 页超时），仍保存已获取的部分结果，在文件统计信息中标注"数据获取不完整"
  - 文件内容至少包含：
    - 搜索时间、搜索条件摘要
    - 项目列表（序号、项目名、Star 数、语言、更新时间、用途描述、URL）
    - 统计信息（搜索到多少条、过滤后多少条、去重后多少条）
  - 历史文件暂不做自动清理
  - **输出文件模板**：

```markdown
# GitHub 金融开源项目搜索报告

- **搜索时间**：2026-05-15 18:00 UTC
- **搜索条件**：关键词=banking+fintech+financial | 语言=Java,Python | 最低Star=100 | 排序=stars
- **数据统计**：API返回 256 条，过滤后 189 条，去重后 175 条

| # | 项目名 | ⭐ Stars | 语言 | 最近更新 | 用途描述 |
|---|--------|---------|------|----------|----------|
| 1 | [apache/fineract](https://github.com/apache/fineract) | 1200 | Java | 2026-05-10 | 金融服务平台 |
```

---

## 四、非功能需求

| 维度 | 要求 |
|------|------|
| 性能 | 单次搜索（含分页）应在 60 秒内完成（GitHub Actions Runner 环境） |
| 安全 | GitHub Token 使用 Actions 内置 `secrets.GITHUB_TOKEN` 或自定义 Secrets，**严禁硬编码** |
| 可用性 | 搜索失败不阻塞 pipeline，记录日志，下次调度照常执行 |
| 数据量 | 每次搜索结果 ≤ 300 条，单文件大小 ≤ 500 KB |
| 可维护性 | 搜索参数通过 `config/search.yml` 配置，Python 脚本与配置分离 |
| 零成本 | 公开仓库 GitHub Actions 免费无限使用，GitHub Pages 免费托管 |
| 超时与重试 | 单次 API 请求超时 10 秒；失败后重试最多 2 次，间隔 5 秒（指数退避） |
| 日志 | v1 仅依赖 GitHub Actions 运行日志，不做持久化；v2 可考虑写入文件或外部日志服务 |

---

## 五、约束与依赖

### 5.1 前置依赖

| 依赖项 | 说明 |
|--------|------|
| GitHub Actions | 免费 CI/CD 运行环境，Ubuntu Runner |
| GitHub REST API v3 | `/search/repositories` 端点 |
| GitHub Pages | 静态站点托管（需在仓库 Settings 启用） |
| Python 3.x | GitHub Actions Ubuntu Runner 预装 |
| PyYAML | Python YAML 配置文件解析（`pip install pyyaml`） |
| requests | Python HTTP 库（`pip install requests`） |

### 5.2 边界条件

| 项目 | 限制 |
|------|------|
| GitHub API 单次返回 | 100 条/页，本期上限 300 条（3 页） |
| GitHub API 限速 | 有认证 30 次/分钟（`GITHUB_TOKEN`），搜索接口独立限速 10 次/分钟 |
| Actions 单次运行时限 | 6 小时（远超实际需要） |
| 输出文件 | 按日累积，暂不做自动清理 |
| 本期不涉及 | 数据库存储、Web 管理界面、邮件推送、代码下载与分析、AI 摘要 |

---

## 六、验收标准

- [ ] **场景1：每日自动搜索** → 配置好 `schedule` cron 后，Actions 每日自动运行，仓库 `results/` 出现当日文件，GitHub Pages 可在线浏览
- [ ] **场景2：手动触发搜索** → 在 Actions 页面点击 "Run workflow"，即时生成结果文件并推送
- [ ] **场景3：筛选条件生效** → 修改 `config/search.yml` 中的 `min_stars` 后提交，下次运行仅返回满足条件的项目
- [ ] **场景4：GitHub Pages 可访问** → 浏览器访问 `https://{username}.github.io/{repo}/` 看到历史搜索结果索引页
- [ ] **场景5：多语言搜索** → 配置 `language: [Java, Python]`，脚本分别发起请求并合并去重，结果无重复仓库
- [ ] **场景6：结果排序** → 输出文件中项目按 Star 数降序排列
- [ ] **异常1：API 限速** → 脚本捕获 403 限速错误，记录日志，workflow 标记为 failure（不影响下次调度）
- [ ] **异常2：搜索结果为空** → 生成文件注明"本次搜索无符合条件的结果"，不报错
- [ ] **异常3：push 冲突** → 若远程有新提交，脚本先 `git pull --rebase` 再 push
- [ ] **异常4：部分页面获取失败** → 保存已获取的部分结果，文件中标注"数据获取不完整"
- [ ] **异常5：配置文件缺失或损坏** → 脚本打印明确错误信息（如"配置文件不存在"或"min_stars 必须为非负整数"），非静默失败
- [ ] **异常6：GITHUB_TOKEN 未设置** → 脚本打印警告信息，以匿名低限速继续运行
- [ ] **异常7：输出目录不存在** → 脚本自动创建 `results/` 和 `docs/` 目录
- [ ] **异常8：Git push 失败（非冲突原因）** → 记录错误日志，不阻塞整个 workflow
- [ ] **输出文件格式** → 打开生成的 `.md` 文件，内容结构与模板一致，排版正常

---

## 七、文件结构

```
findBankProject/
├── .github/
│   └── workflows/
│       └── search.yml          # GitHub Actions workflow 定义
├── config/
│   └── search.yml              # 可配置的搜索参数
├── scripts/
│   ├── github_search.py        # 核心搜索脚本
│   └── requirements.txt        # Python 依赖
├── results/                    # 搜索结果文件（A：提交回仓库）
│   ├── 2026-05-15_SCHEDULED.md
│   └── 2026-05-15_MANUAL.md
├── docs/                       # GitHub Pages 站点（C）
│   ├── index.md                # 首页：历史记录索引
│   └── 2026-05-15.md           # 每日结果页
└── README.md
```

---

## 八、确认决策记录

| 序号 | 问题 | 决策 |
|------|------|------|
| 1 | 运行方式 | GitHub Actions（零服务器） |
| 2 | 实现语言 | Python |
| 3 | 搜索关键词 | `banking`、`fintech`、`financial` |
| 4 | 每日搜索时刻 | UTC 18:00（北京时间凌晨 2:00） |
| 5 | 历史文件保留 | 暂不做自动清理 |
| 6 | 单次搜索上限 | 300 条（3 页），可配置 |
| 7 | 结果输出方式 | A（提交回仓库 `results/`）+ C（GitHub Pages `docs/`） |
| 8 | 关键词组合语义 | OR（广撒网），可通过 `min_keyword_matches` 二次筛选提升精准度 |
| 9 | 多语言实现方式 | 遍历语言列表分别请求，合并去重 |
| 10 | 结果去重策略 | 以仓库 `full_name` 为唯一标识去重 |
| 11 | 结果排序 | 默认按 Star 数降序（`sort_by: stars`） |
| 12 | 同日多次触发 | 后一次覆盖前一次结果，仅保留最新 |
| 13 | 部分成功处理 | 保存已获取的部分结果，标注"数据获取不完整" |
| 14 | docs/index.md 维护 | 每次运行全量扫描重新生成 |
| 15 | GitHub Pages 渲染方式 | 原生 Markdown 渲染（零配置），不引入 Jekyll/MkDocs |
| 16 | Git 提交身份 | `github-actions[bot]` |
| 17 | API 超时与重试 | 单次超时 10 秒，重试 2 次，指数退避 |
| 18 | 日志持久化 | v1 仅 Actions 日志，v2 可扩展 |

---
> 编写：黄康 | 日期：2026-05-15
