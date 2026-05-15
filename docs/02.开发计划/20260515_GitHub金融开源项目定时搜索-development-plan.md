# GitHub 金融开源项目定时搜索 开发计划

## 一、需求概述

基于需求说明书 v3.0，核心功能点如下：

1. **GitHub 项目搜索**：Python 脚本调用 GitHub Search API，多关键词 OR 组合 + 多语言分别请求 + 去重 + 排序
2. **可配置筛选过滤**：YAML 配置驱动，含配置校验、可选 `created_after`、`min_keyword_matches` 二次筛选
3. **GitHub Actions 定时调度**：schedule + workflow_dispatch，Git 提交身份为 `github-actions[bot]`
4. **项目用途摘要**：轻量模式取 `description`，预留 `summarize_with_ai()` 扩展入口
5. **结果文件输出**：方式 A（results/）+ 方式 C（docs/ GitHub Pages），含部分成功处理、index.md 全量重建、输出模板

---

## 二、前置条件

| 前置项 | 状态 | 说明 |
|--------|------|------|
| 需求说明书 | ✅ 已完成 | `docs/01.需求编写/20260515_GitHub金融开源项目定时搜索-requirement.md` v3.0 |
| GitHub 仓库 | ✅ 已有 | findBankProject |
| Python 环境 | ✅ Actions 预装 | Python 3.11+，Runner 自带 |
| GitHub Pages | ❌ 需启用 | 仓库 Settings → Pages → Source 设为 `docs/` 目录 |
| `GITHUB_TOKEN` | ✅ Actions 内置 | 无需额外配置，自动注入 |

---

## 三、技术方案

### 3.1 依赖分析

| 依赖 | 用途 | 状态 |
|------|------|------|
| Python 3.11+ | 运行环境 | ✅ 已有（Actions Runner 预装） |
| `requests` | HTTP 调用 GitHub API | ❌ 待引入（`requirements.txt`） |
| `pyyaml` | YAML 配置解析 | ❌ 待引入（`requirements.txt`） |
| GitHub Actions | CI/CD 运行环境 | ✅ 已有 |
| GitHub Pages | 静态站点托管 | ❌ 需启用 |
| `git` | 提交结果文件 | ✅ 已有（Actions Runner 预装） |

### 3.2 核心模块设计

```
scripts/
└── github_search.py          # 唯一核心脚本，内含以下职责模块
    ├── load_config()          # 读取并校验 config/search.yml
    ├── search_repositories()  # 调用 GitHub Search API（含分页、重试、超时）
    ├── deduplicate_results()  # 以 full_name 去重
    ├── filter_by_keywords()   # min_keyword_matches 二次筛选
    ├── sort_results()         # 按 sort_by 排序
    ├── generate_markdown()    # 生成结果 Markdown 文件（results/ + docs/）
    ├── regenerate_index()     # 全量重建 docs/index.md
    ├── summarize_with_ai()    # 预留入口（本期空实现）
    └── main()                 # 主流程编排
```

> 设计原则：单脚本架构，函数式组织，不引入类框架。项目规模小（1 脚本 + 1 配置 + 1 workflow），过度拆分反增维护成本。

### 3.3 关键流程

```
main()
  │
  ├─ 1. load_config()
  │     ├── 读取 config/search.yml
  │     ├── 校验配置项类型与范围
  │     └── 校验失败 → 打印错误 → sys.exit(1)
  │
  ├─ 2. 检测 GITHUB_TOKEN 环境变量
  │     └── 未设置 → 打印警告（继续运行）
  │
  ├─ 3. search_repositories()
  │     ├── 遍历 language 列表，每种语言分别请求
  │     ├── 构造 q 参数：keywords(OR) + stars + pushed + language + fork:false
  │     ├── 分页获取（per_page=100, max_pages 可配）
  │     ├── 单次请求超时 10s，失败重试 2 次（指数退避）
  │     ├── 捕获 403 限速 → 记录日志 → 标记 partial=True
  │     └── 返回 (items_list, partial_flag)
  │
  ├─ 4. deduplicate_results()
  │     └── 以 full_name 为键去重，保留首条
  │
  ├─ 5. filter_by_keywords()
  │     └── 按 min_keyword_matches 过滤 description
  │
  ├─ 6. sort_results()
  │     └── 按 sort_by（默认 stars）降序
  │
  ├─ 7. generate_markdown()
  │     ├── 生成 results/{date}_{trigger}.md（按模板格式）
  │     ├── 生成 docs/{date}.md（同内容，略去触发方式）
  │     └── 统计信息含：API 返回数、过滤后数、去重后数、partial 标注
  │
  ├─ 8. regenerate_index()
  │     ├── 扫描 docs/ 下所有 {YYYY-MM-DD}.md 文件
  │     └── 全量重新生成 docs/index.md（日期倒序链接列表）
  │
  └─ 9. Git 操作（由 workflow 完成，非脚本职责）
        ├── git config user.name/email
        ├── git add + commit + push
        └── push 失败 → git pull --rebase → 重试 push
```

### 3.4 API 设计

脚本内部函数签名（非 HTTP API）：

| 函数 | 签名 | 说明 |
|------|------|------|
| load_config | `load_config(path: str) -> dict` | 读取并校验 YAML 配置，校验失败抛出 SystemExit |
| search_repositories | `search_repositories(config: dict, token: str) -> tuple[list, bool]` | 返回 (去重前项目列表, 是否部分失败) |
| deduplicate_results | `deduplicate_results(items: list) -> list` | 以 full_name 去重 |
| filter_by_keywords | `filter_by_keywords(items: list, min_matches: int) -> list` | 二次关键词筛选 |
| sort_results | `sort_results(items: list, sort_by: str) -> list` | 排序 |
| generate_markdown | `generate_markdown(items: list, config: dict, trigger: str, partial: bool) -> None` | 生成 results/ + docs/ 文件 |
| regenerate_index | `regenerate_index(docs_dir: str) -> None` | 全量重建 index.md |
| summarize_with_ai | `summarize_with_ai(description: str, repo_url: str) -> str` | 预留入口，本期 return description |

---

## 四、开发任务清单

### 阶段一：基础框架（P0）

| 序号 | 任务 | 优先级 | 验证标准 |
|------|------|--------|----------|
| 1 | 创建 `config/search.yml` 配置文件 | P0 | 包含所有配置项，格式正确可被 PyYAML 解析 |
| 2 | 创建 `scripts/requirements.txt` | P0 | 包含 requests、pyyaml |
| 3 | 实现 `load_config()`：读取 + 校验配置 | P0 | 合法配置正常返回；非法配置打印错误并退出 |
| 4 | 实现 `search_repositories()`：单语言单页请求 | P0 | 调用 GitHub API 返回 JSON，含超时与重试 |
| 5 | 实现分页获取（max_pages 可配） | P0 | 可获取最多 300 条（3 页） |
| 6 | 实现多语言遍历请求 | P0 | 配置 2 种语言时分别请求并合并 |

### 阶段二：数据处理（P0）

| 序号 | 任务 | 优先级 | 验证标准 |
|------|------|--------|----------|
| 7 | 实现 `deduplicate_results()` | P0 | 同一 full_name 仅保留一条 |
| 8 | 实现 `filter_by_keywords()` | P0 | min_keyword_matches=2 时，描述中仅含 1 个关键词的仓库被过滤 |
| 9 | 实现 `sort_results()` | P0 | 按 Star 数降序排列 |
| 10 | 实现 `summarize_with_ai()` 空实现 | P0 | 直接返回 description，description 为空返回"无描述" |

### 阶段三：输出与部署（P0）

| 序号 | 任务 | 优先级 | 验证标准 |
|------|------|--------|----------|
| 11 | 实现 `generate_markdown()`：results/ 输出 | P0 | 文件命名、内容格式与模板一致 |
| 12 | 实现 `generate_markdown()`：docs/ 输出 | P0 | 生成 docs/{date}.md |
| 13 | 实现 `regenerate_index()` | P0 | index.md 列出所有历史日期链接（倒序） |
| 14 | 实现 `main()` 流程编排 | P0 | 串联完整流程 |
| 15 | 创建 `.github/workflows/search.yml` | P0 | schedule + workflow_dispatch，含 git 操作步骤 |
| 16 | 实现 GITHUB_TOKEN 检测与警告 | P0 | 未设置时打印警告但不退出 |
| 17 | 实现部分成功处理 | P0 | 分页部分失败时保存已有结果，标注"数据获取不完整" |
| 18 | 实现输出目录自动创建 | P0 | results/ 和 docs/ 不存在时自动创建 |

### 阶段四：Git 操作与异常处理（P0）

| 序号 | 任务 | 优先级 | 验证标准 |
|------|------|--------|----------|
| 19 | Workflow 中配置 git 提交身份 | P0 | user.name=github-actions[bot] |
| 20 | Workflow 中实现 git push 失败重试 | P0 | pull --rebase 后重试 push |
| 21 | 实现 API 403 限速捕获 | P0 | 记录日志，不崩溃 |
| 22 | 实现搜索结果为空处理 | P0 | 生成文件注明"本次搜索无符合条件的结果" |

### 阶段五：集成验证（P0）

| 序号 | 任务 | 优先级 | 验证标准 |
|------|------|--------|----------|
| 23 | 本地端到端测试 | P0 | 手动运行脚本，生成完整结果文件 |
| 24 | GitHub Actions 手动触发测试 | P0 | workflow_dispatch 运行成功，仓库出现结果文件 |
| 25 | GitHub Pages 可访问性验证 | P0 | 浏览器访问索引页和结果页 |

---

## 五、注意事项

| 类别 | 要点 |
|------|------|
| API 限速 | 搜索接口独立限速 10 次/分钟（有认证）。多语言搜索时需注意请求间隔，2 种语言 + 各 3 页 = 6 次请求，在限额内 |
| 配置安全 | `GITHUB_TOKEN` 严禁硬编码，仅通过环境变量 `secrets.GITHUB_TOKEN` 注入 |
| 编码问题 | Windows 本地开发时注意文件编码统一为 UTF-8，Markdown 文件不含 BOM |
| Git 冲突 | 定时任务与手动触发可能同日运行，文件覆盖策略已明确（后一次覆盖），但 git push 时需处理远端新提交 |
| GitHub Pages | 需在仓库 Settings 中启用，Source 选择 `docs/` 目录；首次部署后可能需几分钟生效 |
| 部分成功 | 分页失败时保存已有数据，不可因第 2 页失败丢弃第 1 页结果 |
| 指数退避 | 重试间隔：首次 5 秒，第二次 10 秒（5 * 2^1），避免连续请求加剧限速 |

---

## 六、文件清单

| 文件路径 | 操作 | 说明 |
|----------|------|------|
| `config/search.yml` | 新建 | 搜索配置文件 |
| `scripts/github_search.py` | 新建 | 核心搜索脚本 |
| `scripts/requirements.txt` | 新建 | Python 依赖 |
| `.github/workflows/search.yml` | 新建 | GitHub Actions workflow |
| `results/.gitkeep` | 新建 | 占位文件，确保目录被 Git 追踪 |
| `docs/index.md` | 新建 | GitHub Pages 首页（初始为空索引） |

---
> 编写：黄康 | 日期：2026-05-15
