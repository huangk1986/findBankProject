---
trigger: always_on
---

# findBankProject 项目全局概览
更新时间: 2026-05-15

## 项目简介

findBankProject 是一个基于 GitHub Actions 的自动化工具，定时从 GitHub 搜索金融业/银行业相关开源项目，使用 Python 脚本调用 GitHub Search API，结果以 Markdown 文件提交回仓库并发布到 GitHub Pages，实现零服务器成本的开源项目情报收集。

## 技术方案

- **运行环境**：GitHub Actions（Ubuntu Runner，免费）
- **开发语言**：Python 3.11+
- **触发方式**：`schedule`（每日定时）+ `workflow_dispatch`（手动触发）
- **数据源**：GitHub REST API v3 `/search/repositories`
- **结果输出**：仓库 `results/` 目录 + GitHub Pages `docs/` 目录
- **配置管理**：YAML 配置文件 `config/search.yml`

## 项目结构

```
findBankProject/
├── .github/
│   └── workflows/
│       └── search.yml              # GitHub Actions workflow 定义（定时/手动触发）
├── config/
│   └── search.yml                  # 搜索配置（关键词、筛选条件、输出设置）
├── scripts/
│   ├── github_search.py            # 核心搜索脚本
│   └── requirements.txt            # Python 依赖（requests、pyyaml）
├── results/                        # 搜索结果 Markdown 文件（提交回仓库）
│   └── {YYYY-MM-DD}_{TRIGGER}.md
├── docs/                           # GitHub Pages 站点源文件
│   ├── index.md                    # 首页：历史搜索记录索引
│   └── {YYYY-MM-DD}.md             # 每日搜索结果页
├── docs/01.需求编写/
│   └── 20260515_GitHub金融开源项目定时搜索-requirement.md
├── docs/02.开发计划/
│   └── 20260515_GitHub金融开源项目定时搜索-development-plan.md
├── docs/03.业务审查结果/             # 业务审查报告（待 review-business-logic 生成）
└── README.md
```

## 核心流程

```
GitHub Actions 触发 (schedule / workflow_dispatch)
    ↓
Python 脚本 (scripts/github_search.py)
    ├── 1. 读取并校验 config/search.yml 配置
    ├── 2. 遍历语言列表，每种语言分别调用 GitHub Search API（分页、重试、超时）
    ├── 3. 以 full_name 去重
    ├── 4. 按 min_keyword_matches 二次筛选
    ├── 5. 按 sort_by 排序（默认 stars 降序）
    ├── 6. 提取 description 作为项目用途摘要（预留 summarize_with_ai 扩展入口）
    ├── 7. 生成 results/{date}_{trigger}.md
    ├── 8. 生成 docs/{date}.md（GitHub Pages）
    └── 9. 全量扫描重建 docs/index.md 索引页
    ↓
Git Steps
    ├── git add → commit → push（结果提交回仓库）
    └── GitHub Pages 自动部署（docs/ 目录变更自动触发）
```

## 配置说明

`config/search.yml` 可配置项：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `keywords` | 搜索关键词列表（OR 语义） | `banking, fintech, financial` |
| `language` | 编程语言列表（遍历分别搜索） | `Java, Python` |
| `min_stars` | 最低 Star 数 | `100` |
| `pushed_after` | 最近更新时间 | `2026-01-01` |
| `created_after` | 仓库创建时间下限（可选，本期不启用） | — |
| `sort_by` | 排序方式（stars / updated / forks） | `stars` |
| `max_pages` | 最大分页数（每页 100 条） | `3` |
| `min_keyword_matches` | 二次关键词匹配数筛选 | `1` |
| `output_dir` | 结果输出目录 | `results/` |
| `docs_dir` | GitHub Pages 源目录 | `docs/` |

## 依赖关系

| 依赖 | 用途 | 获取方式 |
|------|------|----------|
| Python 3.11+ | 脚本运行环境 | GitHub Actions Runner 预装 |
| `requests` | HTTP 调用 GitHub API | `pip install` |
| `pyyaml` | YAML 配置解析 | `pip install` |
| GitHub Actions | CI/CD 运行环境 | 仓库自带 |
| GitHub Pages | 静态站点托管 | 仓库 Settings 启用 |
| `GITHUB_TOKEN` | API 认证 | Actions 内置 Secret |
