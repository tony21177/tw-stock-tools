---
name: Update README with every significant change
description: Whenever making meaningful behavior, default, or feature changes to tw_stock_tools or any project, also update the README/docs in the same commit
type: feedback
originSessionId: e67fcb4a-ba3e-4b10-8dd9-8d8a51bbed3d
---
For tw_stock_tools (and any project with a README), **every significant change must include a README update in the same commit/push**. The user explicitly stated this on 2026-04-29 after multiple commits where I shipped code changes without syncing docs.

**Why:** The user uses the README as the canonical reference and shares the public GitHub repo. Code that drifts ahead of docs makes the repo confusing for users (themselves or others reading it later).

**How to apply:**
- "Significant" includes: new tools/files, new flags or CLI options, default value changes, new concept categories, removed features, behavior changes that affect output. Bug fixes with no user-visible behavior change can skip README.
- The README update must accurately reflect the new behavior — not just mention it in passing. If a default changed, update the section that documents the default.
- Bundle code + README in one commit when possible. If splitting, do README in immediate follow-up commit.
- For tw_stock_tools specifically: top-level README.md covers overall workflow + per-tool sections; concept_momentum/ has its own README.md for the sub-module.
- When in doubt, update README rather than skip it.
- **In Telegram completion reports, always explicitly list README among updated artifacts** (e.g., "✅ README 已同步" or "README 第 N 節更新"). Doing it silently makes the user worry it was skipped — they specifically called this out on 2026-05-06 after I committed README in 969e82f but only mentioned the code files in my report. Treat README mention as a required line in any "done" report, not optional.

**2026-08-02 文件結構改版**:README 已精簡為 73 行索引(策略表+排程+回測一句+連結),完整內容拆至 `docs/strategies/`(18 份策略頁文件)、`docs/tools/`(9 份深潛文件)、`docs/infra.md`(基礎設施)。**之後改動:更新對應的 docs/ 檔案 + README 索引表該列(排程/回測結論變動時)**,不要再把長內容塞回 README。新策略上線=新增 docs/strategies/<slug>.md + README 表格加一列。
