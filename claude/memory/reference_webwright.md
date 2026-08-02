---
name: reference_webwright
description: "webwright (Microsoft Research browser-agent harness) install location, usage, and install gotchas"
metadata: 
  node_type: memory
  type: reference
  originSessionId: 3a410b23-358c-46fc-9ac6-d5d0088eaaf4
---

Microsoft Research **webwright** — a browser-agent harness ("a terminal is all you need for web agents"): the model writes/executes Playwright Python scripts instead of predicting single actions. Cloned at `~/project/webwright`, editable-installed (`pip install -e .`) into `~/.local` on 2026-06-03.

- **CLI:** `webwright` (on PATH at `~/.local/bin/webwright`) or `python3 -m webwright.run.cli -t "<task>" --start-url <url> -c base.yaml -c model_claude.yaml -o outputs/default`. Standalone CLI needs an API key env (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY`).
- **As a Claude Code plugin** (no extra API key — host drives it). Two steps, must run in the CC terminal, then restart session: `/plugin marketplace add /home/kun/project/webwright` then `/plugin install webwright@webwright`. The original `/plugin install` failed because step 1 (marketplace add) was skipped → "Marketplace webwright not found". Provides skill + `/webwright:run` (one-shot) and `/webwright:craft` (reusable parameterized CLI tool).
- **Gotchas:** all 9 Python deps were already present in `~/.local` (playwright 1.58, pydantic 2.13, typer, httpx, etc.) so no conflicts. System had `python3` but **no `python`**; the bundled skill's generated scripts call `python final_script.py`, so created symlink `~/.local/bin/python -> /usr/bin/python3`. Chromium binary installed via `playwright install chromium` (chromium-1208).

Relates to [[reference_chip_skill]] (browser/QA tooling lives elsewhere; webwright is general web automation).
