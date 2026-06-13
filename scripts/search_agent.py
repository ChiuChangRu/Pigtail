"""
Daily Literature Search Agent
搜尋 PubMed、Google Scholar、USPTO 的 hydrophilic coating 相關文獻
使用 Claude API 進行中文摘要與相關性評分
"""

import os
import json
import time
import datetime
import requests
import xml.etree.ElementTree as ET
from pathlib import Path
import anthropic

# ── 路徑設定 ──────────────────────────────────────────
ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "config" / "keywords.json"
PAPERS_PATH = ROOT / "data" / "papers.json"
REPORTS_DIR = ROOT / "reports"
REPORTS_DIR.mkdir(exist_ok=True)
(ROOT / "data").mkdir(exist_ok=True)

TODAY = datetime.date.today().isoformat()
client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


# ── 載入設定 ──────────────────────────────────────────
def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ── 載入既有論文資料庫（去重用）─────────────────────────
def load_existing_papers():
    if PAPERS_PATH.exists():
        with open(PAPERS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def get_existing_ids(papers):
    return {p.get("id", "") for p in papers if p.get("id")}


# ══════════════════════════════════════════════════════
# 1. PubMed 搜尋
# ══════════════════════════════════════════════════════
def search_pubmed(query: str, max_results: int = 10) -> list[dict]:
    """使用 PubMed E-utilities API 搜尋，完全免費"""
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

    # Step 1: esearch 取得 PMID 列表
    search_url = f"{base}/esearch.fcgi"
    params = {
        "db": "pubmed",
        "term": query,
        "retmax": max_results,
        "sort": "date",
        "datetype": "pdat",
        "reldate": 90,   # 近 90 天
        "retmode": "json"
    }
    try:
        r = requests.get(search_url, params=params, timeout=15)
        r.raise_for_status()
        pmids = r.json().get("esearchresult", {}).get("idlist", [])
    except Exception as e:
        print(f"  PubMed esearch 失敗: {e}")
        return []

    if not pmids:
        return []

    # Step 2: efetch 取得詳細資訊
    fetch_url = f"{base}/efetch.fcgi"
    fetch_params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "rettype": "abstract",
        "retmode": "xml"
    }
    try:
        r = requests.get(fetch_url, params=fetch_params, timeout=20)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception as e:
        print(f"  PubMed efetch 失敗: {e}")
        return []

    papers = []
    for article in root.findall(".//PubmedArticle"):
        try:
            pmid = article.findtext(".//PMID", "")
            title = article.findtext(".//ArticleTitle", "No title")
            abstract = article.findtext(".//AbstractText", "")
            journal = article.findtext(".//Journal/Title", "")
            year = article.findtext(".//PubDate/Year", "")
            month = article.findtext(".//PubDate/Month", "")

            # 作者
            authors = []
            for author in article.findall(".//Author")[:3]:
                last = author.findtext("LastName", "")
                fore = author.findtext("ForeName", "")
                if last:
                    authors.append(f"{last} {fore}".strip())
            author_str = "; ".join(authors) + (" et al." if len(authors) >= 3 else "")

            papers.append({
                "id": f"pubmed_{pmid}",
                "source": "PubMed",
                "pmid": pmid,
                "title": title,
                "abstract": abstract[:1500],
                "journal": journal,
                "year": year,
                "month": month,
                "authors": author_str,
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                "query": query,
                "fetched_date": TODAY
            })
        except Exception:
            continue

    print(f"  PubMed [{query[:40]}]: {len(papers)} 篇")
    return papers


# ══════════════════════════════════════════════════════
# 2. USPTO 專利搜尋
# ══════════════════════════════════════════════════════
def search_uspto(query: str, max_results: int = 5) -> list[dict]:
    """USPTO PatentsView API，免費"""
    url = "https://search.patentsview.org/api/v1/patent/"
    payload = {
        "q": {"_text_any": {"patent_title": query}},
        "f": ["patent_id", "patent_title", "patent_abstract", "patent_date",
              "assignee_organization", "inventor_last_name"],
        "o": {"per_page": max_results, "sort": [{"patent_date": "desc"}]}
    }
    try:
        r = requests.post(url, json=payload, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  USPTO 搜尋失敗: {e}")
        return []

    papers = []
    for p in data.get("patents", []):
        pid = p.get("patent_id", "")
        papers.append({
            "id": f"uspto_{pid}",
            "source": "USPTO",
            "patent_id": pid,
            "title": p.get("patent_title", ""),
            "abstract": (p.get("patent_abstract") or "")[:1500],
            "year": (p.get("patent_date") or "")[:4],
            "month": (p.get("patent_date") or "")[5:7],
            "authors": p.get("inventor_last_name", ""),
            "assignee": p.get("assignee_organization", ""),
            "url": f"https://patents.google.com/patent/US{pid}",
            "query": query,
            "fetched_date": TODAY
        })

    print(f"  USPTO [{query[:40]}]: {len(papers)} 篇")
    return papers


# ══════════════════════════════════════════════════════
# 3. Claude AI 分析（批次處理）
# ══════════════════════════════════════════════════════
SYSTEM_PROMPT = """你是 Bioteque（邦特生物科技）的 R&D 文獻分析助理，專精於醫療器材表面改質技術。

Bioteque 產品線：ureteral stent、hemodialysis catheter、TPU catheter、biopsy needle。
現有能力：air plasma 前處理、LED UV 固化、Harland FTS 摩擦測試儀。
關注塗層系統：PVP、PEG、MPC、SBMA、UV-cure、thermal-cure。

你的任務：
1. 產出繁體中文摘要（150字以內）
2. 評分（JSON格式）：
   - product_score (0-5)：與 Bioteque 產品線的直接相關性
   - research_score (0-5)：研究深度（有定量數據得高分）
   - total_score (0-10)：兩者之和
   - highlight：1句話說明最有價值的發現（繁體中文）
   - tags：最多3個標籤，從 [PVP, PEG, MPC, SBMA, UV-cure, thermal-cure, friction, adhesion, durability, biocompatibility, TPU, ureteral-stent, catheter, patent] 選取

回應格式必須是純 JSON，不含任何 markdown：
{
  "summary_zh": "...",
  "product_score": 0,
  "research_score": 0,
  "total_score": 0,
  "highlight": "...",
  "tags": []
}"""


def analyze_papers_with_claude(papers: list[dict]) -> list[dict]:
    """批次送給 Claude 分析，使用 claude-haiku-4-5 節省成本"""
    analyzed = []

    for i, paper in enumerate(papers):
        print(f"  分析 {i+1}/{len(papers)}: {paper['title'][:50]}...")

        prompt = f"""標題：{paper.get('title', '')}
摘要：{paper.get('abstract', '（無摘要）')}
來源：{paper.get('source', '')} | 年份：{paper.get('year', '')}
查詢關鍵字：{paper.get('query', '')}"""

        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=500,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}]
            )
            raw = response.content[0].text.strip()
            # 清除可能的 markdown fence
            raw = raw.replace("```json", "").replace("```", "").strip()
            analysis = json.loads(raw)

            paper.update({
                "summary_zh": analysis.get("summary_zh", ""),
                "product_score": analysis.get("product_score", 0),
                "research_score": analysis.get("research_score", 0),
                "total_score": analysis.get("total_score", 0),
                "highlight": analysis.get("highlight", ""),
                "tags": analysis.get("tags", []),
                "analyzed_date": TODAY
            })
        except Exception as e:
            print(f"    分析失敗: {e}")
            paper.update({
                "summary_zh": "",
                "total_score": 0,
                "tags": [],
                "analyzed_date": TODAY
            })

        analyzed.append(paper)
        time.sleep(0.3)  # 避免 rate limit

    return analyzed


# ══════════════════════════════════════════════════════
# 4. 生成 Markdown 報告
# ══════════════════════════════════════════════════════
def generate_markdown_report(new_papers: list[dict], all_papers: list[dict]) -> str:
    """生成每日 Markdown 報告"""
    high_relevance = [p for p in new_papers if p.get("total_score", 0) >= 6]
    medium_relevance = [p for p in new_papers if 3 <= p.get("total_score", 0) < 6]

    high_relevance.sort(key=lambda x: x.get("total_score", 0), reverse=True)

    lines = [
        f"# 文獻日報 {TODAY}",
        "",
        f"> 本日搜尋新增 **{len(new_papers)}** 篇 ｜ 高相關（≥6分）**{len(high_relevance)}** 篇 ｜ 資料庫總計 **{len(all_papers)}** 篇",
        "",
    ]

    # 高相關文獻
    if high_relevance:
        lines += ["## ⭐ 高相關文獻（評分 ≥ 6）", ""]
        for p in high_relevance:
            source_badge = {"PubMed": "🔬", "USPTO": "📋", "Scholar": "📖"}.get(p.get("source", ""), "📄")
            lines += [
                f"### {source_badge} {p.get('title', 'No title')}",
                "",
                f"**來源** {p.get('source', '')} ｜ **年份** {p.get('year', '')} ｜ **評分** {p.get('total_score', 0)}/10（產品相關 {p.get('product_score', 0)} + 研究深度 {p.get('research_score', 0)}）",
                "",
            ]
            if p.get("authors"):
                lines.append(f"**作者** {p['authors']}")
                lines.append("")
            lines += [
                f"**中文摘要** {p.get('summary_zh', '—')}",
                "",
                f"**重點發現** {p.get('highlight', '—')}",
                "",
            ]
            if p.get("tags"):
                tag_str = " ".join(f"`{t}`" for t in p["tags"])
                lines.append(f"**標籤** {tag_str}")
                lines.append("")
            lines.append(f"🔗 [{p.get('url', '')}]({p.get('url', '')})")
            lines.append("")
            lines.append("---")
            lines.append("")

    # 中等相關
    if medium_relevance:
        lines += ["## 📋 中等相關文獻（3–5 分）", ""]
        lines.append("| 標題 | 來源 | 年份 | 評分 | 標籤 | 連結 |")
        lines.append("|------|------|------|------|------|------|")
        for p in sorted(medium_relevance, key=lambda x: x.get("total_score", 0), reverse=True):
            title_short = p.get("title", "")[:60] + ("…" if len(p.get("title", "")) > 60 else "")
            tags = ", ".join(p.get("tags", []))
            lines.append(
                f"| {title_short} | {p.get('source', '')} | {p.get('year', '')} | "
                f"{p.get('total_score', 0)}/10 | {tags} | [link]({p.get('url', '')}) |"
            )
        lines.append("")

    # 統計
    lines += [
        "## 📊 本日統計",
        "",
        f"- 搜尋來源：PubMed + USPTO",
        f"- 新增文獻：{len(new_papers)} 篇",
        f"- 高相關（≥6）：{len(high_relevance)} 篇",
        f"- 中等相關（3-5）：{len(medium_relevance)} 篇",
        f"- 資料庫累計：{len(all_papers)} 篇",
        "",
        f"*自動生成時間：{TODAY} | 由 GitHub Actions + Claude API 驅動*",
    ]

    return "\n".join(lines)


# ══════════════════════════════════════════════════════
# 主程式
# ══════════════════════════════════════════════════════
def main():
    print(f"=== 文獻搜尋代理人啟動 {TODAY} ===")

    config = load_config()
    existing_papers = load_existing_papers()
    existing_ids = get_existing_ids(existing_papers)

    all_new_papers = []

    # 每個類別各取代表性查詢（控制 API 用量）
    queries_to_run = []
    for category, queries in config["search_queries"].items():
        queries_to_run.extend(queries[:2])  # 每類別取前 2 個查詢

    print(f"\n將執行 {len(queries_to_run)} 個查詢...")

    for query in queries_to_run:
        print(f"\n🔍 查詢：{query}")

        # PubMed
        pubmed_papers = search_pubmed(query, max_results=8)
        new_pubmed = [p for p in pubmed_papers if p["id"] not in existing_ids]
        all_new_papers.extend(new_pubmed)
        existing_ids.update(p["id"] for p in new_pubmed)
        time.sleep(0.4)  # PubMed API 速率限制

        # USPTO（僅 coating 相關查詢）
        if "coating" in query.lower() or "hydrophilic" in query.lower():
            uspto_papers = search_uspto(query, max_results=4)
            new_uspto = [p for p in uspto_papers if p["id"] not in existing_ids]
            all_new_papers.extend(new_uspto)
            existing_ids.update(p["id"] for p in new_uspto)
        time.sleep(0.3)

    print(f"\n共找到 {len(all_new_papers)} 篇新文獻，開始 AI 分析...")

    # Claude 分析
    if all_new_papers:
        analyzed_papers = analyze_papers_with_claude(all_new_papers)
    else:
        analyzed_papers = []
        print("今日無新文獻。")

    # 合併資料庫
    all_papers = existing_papers + analyzed_papers

    # 儲存 papers.json
    with open(PAPERS_PATH, "w", encoding="utf-8") as f:
        json.dump(all_papers, f, ensure_ascii=False, indent=2)
    print(f"\n✅ papers.json 已更新（共 {len(all_papers)} 篇）")

    # 生成 Markdown 報告
    report_md = generate_markdown_report(analyzed_papers, all_papers)
    report_path = REPORTS_DIR / f"{TODAY}.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_md)
    print(f"✅ 報告已生成：{report_path}")

    # 更新 README
    high_count = sum(1 for p in analyzed_papers if p.get("total_score", 0) >= 6)
    readme_path = ROOT / "README.md"
    readme_content = f"""# Hydrophilic Coating Literature Database

邦特生物科技 R&D 文獻自動追蹤系統

## 最新報告
- 📅 最後更新：{TODAY}
- 📚 資料庫總計：{len(all_papers)} 篇
- ⭐ 本日高相關：{high_count} 篇

## 查看報告
瀏覽 [reports/](./reports/) 資料夾，或直接看 [今日報告](./reports/{TODAY}.md)。

## 系統說明
- 搜尋來源：PubMed、USPTO
- 關鍵字：hydrophilic coating、PVP/PEG/MPC、ureteral stent、catheter
- 更新頻率：每日 08:00（台灣時間）
- AI 分析：Claude API（相關性評分 + 中文摘要）
"""
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(readme_content)

    print(f"\n🎉 完成！本日新增 {len(analyzed_papers)} 篇，高相關 {high_count} 篇。")


if __name__ == "__main__":
    main()
