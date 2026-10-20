# BandScore skill

> [!IMPORTANT]
> **AI agent**：轉譜時不要直接執行 Audiveris。先完整讀 [SKILL.md](SKILL.md)，從 Step 0 起依序執行（準備頁面圖、整理歌曲資料、讀譜、後處理、驗收），不要跳過前置步驟。
> **AI agents:** do not run Audiveris directly. Read [SKILL.md](SKILL.md) in full and follow it from Step 0; do not skip the preparation steps.

把樂團譜／鍵盤譜 PDF 轉成可在 MuseScore 正確播放的 MusicXML。這是一份給 AI agent 的作業手冊（[SKILL.md](SKILL.md)）加一組 Python 工具：前處理頁面、呼叫本 repo 的 Audiveris-Bandscore 讀譜、後處理與驗收。

- 圖解說明書：[線上閱讀](https://hibikiwtnb.github.io/audiveris-bandscore/)（← → 翻頁，F 全螢幕，點圖放大）；原始檔在 [docs/guide/](docs/guide/index.html)
- 跑一首曲子：[SKILL.md](SKILL.md)
- 開發規則：[DEVELOPMENT.md](DEVELOPMENT.md)
- 檔案格式、教訓、已知缺口：[docs/](docs/)
- 回報問題、提議改進：[../CONTRIBUTING.md](../CONTRIBUTING.md)

## 快速開始

在能執行命令的 AI 工具（Claude Code、Codex、OpenCode、Cursor 等，模型不限）裡說：

```
讀 https://github.com/hibikiwtnb/audiveris-bandscore 的 skill/README.md 和 skill/SKILL.md，
幫我把這份樂隊總譜轉成 MuseScore 能播放的 MusicXML：<PDF 路徑>。從頭做到驗收，最後告訴我結果檔的位置。
```

agent 會照 [requirements.txt](requirements.txt) 準備環境、建立 `environment.txt`，在 `songs/` 下替這首建資料夾，自己讀譜寫 `context/`，跑完流程並驗收。你只需要用 [MuseScore-Bandscore](https://github.com/hibikiwtnb/MuseScore) 聽一遍 `songs/` 下與輸入 PDF 同名的 `.musicxml`。

## 輸入要求

- **格式**：PDF（直接取出內嵌的原圖，不重新點陣化），或依頁序排好的頁面圖（PNG）。
- **解析度**：掃描建議 300 dpi 以上；手機拍照、歪斜嚴重的頁面效果差。
- **樂譜種類**：五線譜的樂隊總譜、鍵盤譜（人聲、吉他與貝斯的五線譜、鍵盤、鼓組、打擊樂一線譜）。
- **TAB**：有 TAB 的譜可以轉，音高從上方的五線譜讀；TAB 的品格數字目前不讀。
- **版權**：請用你合法取得的樂譜，在自己的電腦上轉。轉出的檔案不要公開散佈市售樂譜的內容。

## 結構

```
README.md        本檔
SKILL.md         跑一首曲子的流程與指令（給 agent）
DEVELOPMENT.md   開發規則
requirements.txt 依賴；末尾有 environment.txt 的模板
environment.txt  本機路徑（不進 git，第一次執行時依模板建立）
docs/            formats.md（檔案格式）、lessons.md（教訓）、known-gaps.md（已知缺口）、symbol_templates.md、guide/（圖解說明書）
tools/           流程用的腳本；tools/dtd 是 MusicXML 3.1 DTD
templates/       符號模板，每本樂譜集一個資料夾（見 templates/README.md）
songs/           你的工作區（不進 git）
  <輸入 PDF 檔名>.musicxml   各曲最終輸出（合併版，與輸入 PDF 同名）
  <編號_羅馬字>/             處理過程的產物（一般不必看）
    context/       曲目專屬資料（多由 AI 產生）：song_metadata.md、audiveris_hints.txt、instrument_changes.txt、ottava.txt、hook.py（可選）
    crop_meta/ raw/ pages/   頁面裁切紀錄、Audiveris 輸出、各頁中間 musicxml
    input/         score.pdf、extracted/、omr_in/
    <id>_quality.txt   品質報告
```

曲子資料夾名稱自己取；建議 `編號_羅馬字`，小寫，只用 `a-z 0-9 _`。

## 頁面分區

`tools/page_regions.py` 把每一頁分成以下幾區（輸出 `context/page_regions.txt`），整份文件都用這套名稱：

| 區 | 位置 | 內容 |
|---|---|---|
| 譜表區 | 頁面中間 | 譜表、音符，以及速度、排練記號、和弦名、歌詞、奏法標記等（都屬於譜表區，不屬於 A/B/C） |
| A | 第一行譜表上方 | 只有標題類文字。第 1 頁有曲名、作詞作曲；之後的頁面可能沒有，也可能每頁印同一個曲名 |
| B | 每行譜表左邊 | 樂器全名（第 1 個 system）、縮寫（之後的 system） |
| C | 譜表區下方 | 頁尾、頁碼 |
| D | 右邊 | 通常是空的，不讀 |

A、B、C 只用來取得曲名、作者、聲部名稱、頁碼；加上每行譜表的線數（5 線、TAB 的 6／4 線、打擊樂 1 線），沒有看圖能力的模型也能寫出聲部提示 `partsHint`。

## 環境與依賴

見 [requirements.txt](requirements.txt)：Python 套件（`pip install -r requirements.txt`）與系統工具（poppler、JDK 25、本 repo 編譯出的 Audiveris、MuseScore-Bandscore、PaddleOCR venv）。

- Audiveris：在 repo 根目錄 `./gradlew :app:installDist -x test`，產物在 `app/build/install/app/bin/`。
- PaddleOCR 服務：見 repo 根目錄 [README](../README.md) 第 3 節。沒有 GPU 時每頁 OCR 約 50 秒，有 GPU 約 3 秒。
- MuseScore：用改版的 3.x 分支 [MuseScore-Bandscore](https://github.com/hibikiwtnb/MuseScore)（2x 兩遍小節、% 小節反覆、Hi-Hat 開合記號、移調與樂器映射），不用 MuseScore 4。SKILL 與 docs 記載的 MuseScore 行為是這個分支的實測結果。

## 授權

與本 repo 相同：[AGPL-3.0](../LICENSE)。
