#!/usr/bin/env python3
"""
GitHub 金融/银行业开源项目定时搜索脚本

功能：
  1. 读取 config/search.yml 配置
  2. 调用 GitHub Search API（多关键词 OR + 多语言遍历 + 分页）
  3. 去重 + 二次关键词筛选 + 排序
  4. 生成 results/ 和 docs/ Markdown 文件
  5. 全量重建 docs/index.md 索引页
"""

import os
import sys
import time
import json
import traceback
from datetime import datetime, timezone, timedelta

import requests
import yaml


# ============================================================
# 1. 配置加载与校验
# ============================================================

def load_config(config_path: str) -> dict:
    """读取并校验 YAML 配置文件。校验失败则打印错误并退出。"""
    if not os.path.exists(config_path):
        print(f"[ERROR] 配置文件不存在: {config_path}")
        sys.exit(1)

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        print(f"[ERROR] 配置文件解析失败: {e}")
        sys.exit(1)

    if config is None:
        print("[ERROR] 配置文件内容为空")
        sys.exit(1)

    # --- 必填项校验 ---
    errors = []

    if "keywords" not in config or not isinstance(config["keywords"], list) or len(config["keywords"]) == 0:
        errors.append("keywords 必须是非空列表")

    if "language" not in config or not isinstance(config["language"], list) or len(config["language"]) == 0:
        errors.append("language 必须是非空列表")

    if "min_stars" not in config or not isinstance(config["min_stars"], int) or config["min_stars"] < 0:
        errors.append("min_stars 必须为非负整数")

    if "pushed_after" not in config or not isinstance(config["pushed_after"], str):
        errors.append("pushed_after 必须为字符串（格式 YYYY-MM-DD）")

    if "sort_by" not in config or config["sort_by"] not in ("stars", "updated", "forks", "help-wanted-issues"):
        errors.append("sort_by 必须为 stars / updated / forks / help-wanted-issues")

    if "max_pages" not in config or not isinstance(config["max_pages"], int) or config["max_pages"] < 1:
        errors.append("max_pages 必须为正整数")

    if "min_keyword_matches" not in config or not isinstance(config["min_keyword_matches"], int) or config["min_keyword_matches"] < 0:
        errors.append("min_keyword_matches 必须为非负整数")

    if "output_dir" not in config or not isinstance(config["output_dir"], str):
        errors.append("output_dir 必须为字符串")

    if "docs_dir" not in config or not isinstance(config["docs_dir"], str):
        errors.append("docs_dir 必须为字符串")

    if errors:
        for e in errors:
            print(f"[ERROR] 配置校验失败: {e}")
        sys.exit(1)

    print(f"[INFO] 配置加载成功: keywords={config['keywords']}, language={config['language']}, min_stars={config['min_stars']}")
    return config


# ============================================================
# 2. GitHub API 搜索（含分页、重试、超时）
# ============================================================

def search_repositories(config: dict, token: str | None) -> tuple[list, bool]:
    """
    调用 GitHub Search API，返回 (项目列表, 是否部分失败)。

    关键词 OR 组合 + 每种语言分别搜索 + 分页获取。
    所有结果合并后（去重前）返回。
    """
    base_url = "https://api.github.com/search/repositories"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "findBankProject/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    # 构建基础查询参数（不含 language）
    keywords = config["keywords"]
    keyword_query = "+".join(keywords)  # OR 语义

    base_q = f"{keyword_query}+stars:>={config['min_stars']}+pushed:>={config['pushed_after']}+fork:false"

    # 可选 created_after
    if config.get("created_after"):
        base_q += f"+created:>={config['created_after']}"

    sort_by = config["sort_by"]
    max_pages = config["max_pages"]

    all_items = []
    partial = False
    languages = config["language"]

    for lang in languages:
        lang_q = f"{base_q}+language:{lang}"
        params = {
            "q": lang_q,
            "sort": sort_by,
            "order": "desc",
            "per_page": 100,
        }
        print(f"[INFO] 搜索语言: {lang}, q={lang_q}")

        for page in range(1, max_pages + 1):
            params["page"] = page
            try:
                data = _api_request_with_retry(base_url, headers, params, page, lang)
            except Exception as e:
                print(f"[WARN] 分页获取失败 (lang={lang}, page={page}): {e}")
                partial = True
                break  # 该语言后续页面跳过，继续下一种语言

            items = data.get("items", [])
            total_count = data.get("total_count", 0)
            print(f"[INFO] lang={lang}, page={page}: 获取 {len(items)} 条 (total={total_count})")

            all_items.extend(items)

            # 提前终止：结果不足一页
            if len(items) < 100:
                break

            # 遵守搜索接口限速（10 次/分钟 → 每请求间隔 7 秒）
            if page < max_pages:
                time.sleep(7)

        # 语言之间也间隔
        if languages.index(lang) < len(languages) - 1:
            time.sleep(7)

    print(f"[INFO] API 请求完成，共获取 {len(all_items)} 条 (去重前)")
    return all_items, partial


def _api_request_with_retry(url: str, headers: dict, params: dict, page: int, lang: str) -> dict:
    """单次 API 请求，超时 10 秒，失败重试最多 2 次（指数退避）。"""
    last_exception = None
    for attempt in range(3):  # 首次 + 2 次重试
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=10)
            if resp.status_code == 403:
                print(f"[WARN] API 限速 (403)，lang={lang}, page={page}")
                # 等待重试
                wait = 10 * (2 ** attempt)
                print(f"[INFO] 等待 {wait} 秒后重试...")
                time.sleep(wait)
                continue
            if resp.status_code == 422:
                # 422 通常是查询语法问题或搜索结果超 1000 条限制
                print(f"[WARN] API 返回 422 (可能结果超 1000 上限)，lang={lang}, page={page}")
                return {"items": [], "total_count": 0}
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.Timeout:
            last_exception = f"请求超时 (attempt={attempt + 1})"
            if attempt < 2:
                wait = 5 * (2 ** attempt)
                print(f"[WARN] {last_exception}, {wait}s 后重试...")
                time.sleep(wait)
        except requests.exceptions.RequestException as e:
            last_exception = str(e)
            if attempt < 2:
                wait = 5 * (2 ** attempt)
                print(f"[WARN] 请求失败: {e}, {wait}s 后重试...")
                time.sleep(wait)
    raise RuntimeError(last_exception or "未知错误")


# ============================================================
# 3. 结果去重
# ============================================================

def deduplicate_results(items: list) -> list:
    """以 full_name 为唯一标识去重，保留首条。"""
    seen = set()
    unique = []
    for item in items:
        full_name = item.get("full_name", "")
        if full_name and full_name not in seen:
            seen.add(full_name)
            unique.append(item)
    print(f"[INFO] 去重: {len(items)} → {len(unique)} 条")
    return unique


# ============================================================
# 4. 二次关键词筛选
# ============================================================

def filter_by_keywords(items: list, keywords: list, min_matches: int) -> list:
    """
    按描述中匹配关键词数量进行二次筛选。
    对 description 字段（小写）检查包含几个关键词。
    """
    if min_matches <= 1:
        return items

    keywords_lower = [kw.lower() for kw in keywords]
    filtered = []
    for item in items:
        desc = (item.get("description") or "").lower()
        match_count = sum(1 for kw in keywords_lower if kw in desc)
        if match_count >= min_matches:
            filtered.append(item)
    print(f"[INFO] 关键词二次筛选 (min_matches={min_matches}): {len(items)} → {len(filtered)} 条")
    return filtered


# ============================================================
# 5. 排序
# ============================================================

def sort_results(items: list, sort_by: str) -> list:
    """按指定字段降序排序（API 已按 sort_by 排序，这里做兜底）。"""
    key_map = {
        "stars": "stargazers_count",
        "updated": "pushed_at",
        "forks": "forks_count",
    }
    field = key_map.get(sort_by, "stargazers_count")

    def sort_key(item):
        val = item.get(field, 0)
        if field == "pushed_at":
            return val or "1970-01-01"
        return val or 0

    return sorted(items, key=sort_key, reverse=True)


# ============================================================
# 6. 项目用途摘要
# ============================================================

def summarize_with_ai(description: str, repo_url: str | None = None) -> str:
    """
    获取项目用途摘要（预留 AI 扩展入口）。
    本期直接返回 description 字段，为空返回"无描述"。
    """
    if description:
        return description
    return "无描述"


# ============================================================
# 7. Markdown 文件生成
# ============================================================

def generate_markdown(items: list, config: dict, trigger: str, partial: bool) -> None:
    """
    生成两个 Markdown 文件：
    - results/{date}_{trigger}.md   （提交回仓库）
    - docs/{date}.md                （GitHub Pages）

    内容含搜索时间、条件摘要、项目表格、统计信息。
    """
    now_utc = datetime.now(timezone.utc)
    date_str = now_utc.strftime("%Y-%m-%d")
    time_str = now_utc.strftime("%Y-%m-%d %H:%M UTC")
    beijing_time = now_utc + timedelta(hours=8)
    beijing_str = beijing_time.strftime("%Y-%m-%d %H:%M 北京时间")

    # 确保输出目录存在
    output_dir = config["output_dir"]
    docs_dir = config["docs_dir"]
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(docs_dir, exist_ok=True)

    # 构建内容
    keywords_str = "+".join(config["keywords"])
    languages_str = ",".join(config["language"])
    sort_by = config["sort_by"]
    min_stars = config["min_stars"]
    min_matches = config.get("min_keyword_matches", 1)
    total_count = len(items)

    partial_note = "\n> ⚠️ **注意**：数据获取不完整，部分页面请求失败。\n" if partial else ""
    empty_note = "本次搜索无符合条件的结果。" if total_count == 0 else ""

    lines = [
        "# GitHub 金融开源项目搜索报告",
        "",
        f"- **搜索时间**：{time_str}",
        f"- **触发方式**：{trigger}",
        f"- **搜索条件**：关键词={keywords_str} | 语言={languages_str} | 最低Star={min_stars} | 排序={sort_by} | 关键词匹配数≥{min_matches}",
        f"- **数据统计**：去重后 {total_count} 条",
        partial_note,
        "",
    ]

    if total_count == 0:
        lines.append(empty_note)
    else:
        lines.append("| # | 项目名 | ⭐ Stars | 语言 | 最近更新 | 用途描述 |")
        lines.append("|---|--------|---------|------|----------|----------|")
        for i, item in enumerate(items, 1):
            full_name = item.get("full_name", "")
            html_url = item.get("html_url", "")
            stars = item.get("stargazers_count", 0)
            lang = item.get("language") or "-"
            pushed = (item.get("pushed_at") or "")[:10]
            desc = summarize_with_ai(item.get("description") or "")
            # 截断过长描述
            if len(desc) > 80:
                desc = desc[:77] + "..."
            lines.append(f"| {i} | [{full_name}]({html_url}) | {stars} | {lang} | {pushed} | {desc} |")

    lines.append("")
    lines.append(f"> 生成时间：{beijing_str} | 搜索工具：[findBankProject](https://github.com/{os.environ.get('GITHUB_REPOSITORY', 'unknown/repo')})")

    content = "\n".join(lines) + "\n"

    # 写入 results/
    result_filename = f"{date_str}_{trigger}.md"
    result_path = os.path.join(output_dir, result_filename)
    with open(result_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[INFO] 结果文件已生成: {result_path}")

    # 写入 docs/
    docs_filename = f"{date_str}.md"
    docs_path = os.path.join(docs_dir, docs_filename)
    with open(docs_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[INFO] Pages 文件已生成: {docs_path}")


# ============================================================
# 8. docs/index.md 索引页重建
# ============================================================

def regenerate_index(docs_dir: str) -> None:
    """
    扫描 docs/ 目录下所有 {YYYY-MM-DD}.md 文件，
    全量重新生成 docs/index.md（日期倒序链接列表）。
    """
    os.makedirs(docs_dir, exist_ok=True)

    date_files = []
    for filename in os.listdir(docs_dir):
        if filename == "index.md":
            continue
        if filename.endswith(".md") and len(filename) >= 11:
            prefix = filename[:10]
            try:
                datetime.strptime(prefix, "%Y-%m-%d")
                date_files.append(prefix)
            except ValueError:
                pass

    date_files.sort(reverse=True)

    lines = [
        "# GitHub 金融开源项目搜索记录",
        "",
        "本站自动同步仓库搜索结果，所有项目按 Star 数降序排列。",
        "",
        "## 📅 历史搜索记录",
        "",
    ]

    if date_files:
        for d in date_files:
            lines.append(f"- [{d}]({d}.md)")
    else:
        lines.append("暂无搜索记录，等待首次运行。")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"> 最后更新：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")

    index_path = os.path.join(docs_dir, "index.md")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"[INFO] 索引页已重建: {index_path}")


# ============================================================
# 9. 主流程
# ============================================================

def main() -> None:
    """主流程编排。"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    config_path = os.path.join(project_root, "config", "search.yml")

    # --- 1. 加载配置 ---
    print("=" * 60)
    print("[INFO] GitHub 金融开源项目定时搜索 启动")
    print("=" * 60)
    config = load_config(config_path)

    # --- 2. 检测 GITHUB_TOKEN ---
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("[WARN] GITHUB_TOKEN 未设置，将以匿名模式运行（限速较低）")

    # --- 3. 确定触发方式 ---
    # 通过 GITHUB_EVENT_NAME 区分 schedule / workflow_dispatch / 本地运行
    event_name = os.environ.get("GITHUB_EVENT_NAME", "LOCAL").upper()
    if event_name == "SCHEDULE":
        trigger = "SCHEDULED"
    elif event_name == "WORKFLOW_DISPATCH":
        trigger = "MANUAL"
    else:
        trigger = "LOCAL"

    print(f"[INFO] 触发方式: {trigger}")

    # --- 4. 搜索 ---
    all_items, partial = search_repositories(config, token)

    # --- 5. 去重 ---
    all_items = deduplicate_results(all_items)

    # --- 6. 二次关键词筛选 ---
    min_matches = config.get("min_keyword_matches", 1)
    all_items = filter_by_keywords(all_items, config["keywords"], min_matches)

    # --- 7. 排序 ---
    all_items = sort_results(all_items, config["sort_by"])

    print(f"[INFO] 最终结果: {len(all_items)} 条")

    # --- 8. 生成 Markdown ---
    generate_markdown(all_items, config, trigger, partial)

    # --- 9. 重建索引页 ---
    docs_dir = os.path.join(project_root, config["docs_dir"])
    regenerate_index(docs_dir)

    print("=" * 60)
    print("[INFO] 搜索完成")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[ERROR] 脚本执行异常: {e}")
        traceback.print_exc()
        sys.exit(1)
