# papers.json 使用說明

## 這是什麼
親水塗層文獻資料庫的核心檔案，結構化儲存所有文獻。免安裝、免權限，放在 GitHub repo 即可持續累積。

## 檔案結構

```
{
  "meta": { ... },        ← 專案資訊 + 標籤字典（tag_dictionary）
  "papers": [ ... ]       ← 文獻陣列，每篇一個物件
}
```

## 每篇文獻的欄位

| 欄位 | 說明 | 範例 |
|------|------|------|
| id | 編號（自訂） | "A1"、"67" |
| title | 標題 | "..." |
| authors | 作者 | "Ding et al." |
| year | 年份（數字） | 2021 |
| venue | 期刊/來源 | "Polymers" |
| doi | DOI（無則 null） | "10.3390/..." |
| pmid | PubMed ID（無則 null） | "26202385" |
| doc_type | 類型 | 期刊論文/專利/學位論文/綜述review/會議論文 |
| access | 取得方式 | 開放全文/開放摘要/付費/專利全文 |
| tags | 標籤陣列 | ["TPU", "UV光固化"] |
| purpose | 為什麼要讀 | "..." |
| abstract_note | 摘要重點（無則 null） | "..." |
| value_to_project | 對本案價值 | "..." |
| links | 連結物件 | {"doi": "...", "fulltext": "..."} |

## 如何新增一篇文獻
複製任一篇物件，貼到 papers 陣列最後，改內容即可。記得：
- 物件之間用逗號分隔
- 最後一篇後面「不要」加逗號
- 無資料的欄位填 null（不是空字串）

## 標籤分類（tag_dictionary）
為保持一致，新增文獻時 tags 盡量從字典挑選：
- **基材**：TPU, Pellethane, PVC, Pebax, nitinol, stainless-steel, PEEK, PDMS
- **親水高分子**：PVP, PEG, PEGDA, PVA, MPC, PEO, hyaluronic-acid
- **固化方式**：UV光固化, 熱固化, plasma, self-polymerization
- **錨定/底塗**：benzophenone, C-H-insertion, PDA-polydopamine, PUA, isocyanate, photografting
- **應用**：穿刺針, 活檢針, 導尿管, 導管, 導線guidewire, stent, 通用biomaterial

## 如何用 AI 自動產樹枝圖
把整份 papers.json 貼給 AI，或在對話中說「讀取 papers.json 第 B1 篇，產出樹枝圖」，AI 即可依結構化資料生成。

## 維護建議
- 每次新增文獻同步更新 meta.last_updated
- 重大改版時 schema_version 進位（如 1.0 → 1.1）
- 放在 GitHub repo 的 data/ 資料夾，用 commit 紀錄變更歷史
