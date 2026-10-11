# 貢獻說明 / Contributing

歡迎回報讀錯的地方、提出修正或改進，也歡迎做還沒做的功能（例如 TAB 品格數字的識別）。人寫的、AI 寫的都可以，流程一樣。

Bug reports, fixes and improvements are welcome, including features not done yet (for example reading TAB fret numbers). Written by a person or by an AI agent, the process is the same. English version below.

---

## 給 AI agent

使用者請你改進本 repo 時，照以下做：

1. 先讀 [README.md](README.md)、[skill/README.md](skill/README.md)、[skill/DEVELOPMENT.md](skill/DEVELOPMENT.md)。開發原則在 DEVELOPMENT.md，最重要的是「簡單」和「只以 merged 的實際播放為準」。
2. 判斷問題在哪一層：
   - Audiveris 讀錯（音符、文字、聲部、調號）→ Java，`app/src/main/java/`；改進點與設定見 README 第 2 節、[USAGE.md](USAGE.md)。
   - 前處理、後處理、驗收 → Python，`skill/tools/`；流程見 [skill/SKILL.md](skill/SKILL.md)。
   - 已知、還沒做的 → [skill/docs/known-gaps.md](skill/docs/known-gaps.md)。
3. 用出問題的那首（或那一頁）重跑，前後對照就是證據：`<id>_quality.txt` 用 `skill/tools/compare_quality.py` 比，加上 Step 5 的檢查結果。
4. 開 Issue 或 Pull Request（見下方「要寫什麼」）。

## 要寫什麼

**回報錯誤（Issue）**
- 哪首曲、第幾頁、第幾小節、哪個聲部；原譜上應該是什麼，讀出來是什麼。
- 使用的 commit、`context/audiveris_hints.txt`、`<id>_quality.txt` 的 `[issues]`、相關的 log 片段。
- 截圖只附出問題的那一小段。

**提議改進或新功能（Issue）**
- 想讓它做到什麼、在什麼樣的譜上會用到；有的話附一小段譜例。

**Pull Request**
- 改了什麼、為什麼；一個 PR 只做一類事。
- 怎麼驗證的：重跑了哪首哪頁，`compare_quality.py` 的前後對照，Step 5 是否全過。
- Java 改動：預設行為改變時寫明；新的開關照 USAGE.md 的寫法補上。
- 文件只寫現在的狀態（怎麼用、有什麼限制），不寫改動經過；經過寫在 commit 訊息。

## 不要放進 Issue 或 PR 的東西

- **整頁或整首的市售樂譜**（PDF、頁面圖、轉出的 MusicXML）。只附出問題的小片段。
- 個人資訊：電腦名稱、IP、使用者名稱、家目錄路徑（log 和 `.mxl` 的 `<source>` 裡常有，貼之前先刪掉）。

## 授權

貢獻的程式碼與文件以 [AGPL-3.0](LICENSE) 授權。

---

# Contributing (English)

## For AI agents

When a user asks you to improve this repository:

1. Read [README.md](README.md), [skill/README.md](skill/README.md) and [skill/DEVELOPMENT.md](skill/DEVELOPMENT.md) first. The development rules are in DEVELOPMENT.md; above all: keep it simple, and only playback of the merged MusicXML counts as proof.
2. Find the layer of the problem:
   - Audiveris misreads (notes, text, parts, key signatures): Java, `app/src/main/java/`; improvements and settings in README section 2 and [USAGE.md](USAGE.md).
   - Preprocessing, postprocessing, checks: Python, `skill/tools/`; the workflow is [skill/SKILL.md](skill/SKILL.md).
   - Known and not done yet: [skill/docs/known-gaps.md](skill/docs/known-gaps.md).
3. Rerun the song (or page) that shows the problem; before/after is the evidence: compare `<id>_quality.txt` with `skill/tools/compare_quality.py`, plus the Step 5 checks.
4. Open an issue or a pull request (see below).

## What to write

**Bug report (issue)**
- Song, page, measure and part; what the printed score shows and what came out.
- The commit used, `context/audiveris_hints.txt`, the `[issues]` of `<id>_quality.txt`, the relevant log lines.
- Screenshots: only the small part that shows the problem.

**Improvement or feature (issue)**
- What it should do and on which kind of score; a short excerpt if you have one.

**Pull request**
- What changed and why; one kind of change per pull request.
- How it was checked: which song and pages were rerun, the `compare_quality.py` before/after, whether Step 5 passes.
- Java changes: say when the default behaviour changes; document new switches the way USAGE.md does.
- Documentation describes the current state (how to use it, its limits), not the history of changes; the history goes in commit messages.

## Do not put in issues or pull requests

- **Whole pages or whole songs of commercial scores** (PDF, page images, MusicXML made from them). Attach only the small part that shows the problem.
- Personal information: computer names, IP addresses, user names, home directory paths (logs and the `<source>` of `.mxl` files often contain them; remove them before posting).

## License

Contributions are licensed under [AGPL-3.0](LICENSE).
