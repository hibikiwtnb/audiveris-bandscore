# 變更履歷（skill/）

這裡只記 `skill/`（AI agent 用的 BandScore 流程、工具、模板、文件）的變更。Audiveris 本體（Java）的改進見根目錄 README 第 2 節。日期是同步到本 repo 的日期，括號裡是 commit。

## 2026-11-12：找不同校對單位

- **`tools/proof_pairs.py`**：把校對拆成「原譜一行（約 4 小節）」的單位。每個單位一張圖，上半是原譜（取自 `raw/*.omr` 的 BINARY.png，小節框和譜線座標來自專案檔，裁得準），下半是同樣小節的 MusicXML 經 MuseScore 渲染；下半每個小節依 `.mpos` 的位置拉伸到原譜的寬度，小節線上下對齊。不畫樂器名和拍號（原譜行首沒有）。原譜的小節反覆記號 % 在下半也畫成 %：單位從反覆段中間開始時，補上反覆起點，讓 MuseScore-bandscore 匯入時換成 %（單位第 1 小節前面沒有小節，畫不出 %，仍寫出音符）。另附同樣小節的音符文字清單（譜面書寫音高，8va 已扣回，隱藏的 coll'8va 重疊音有標記）。鋼琴（第一個聲部）和其他聲部分成兩組。agent 校對時只要找上下的不同，不必自己裁圖、定位。

## 2026-11-12：第三次同步

### D.S.／Coda 能播放了
- **segno、coda 模板**（`templates/lovelive_sunshine_best/`、`templates/lovelive_muse_4513870037718/` 的 `segno.png`、`coda.png`，以及給人看的 `check_*.png`）：Audiveris 的分類器認不出這兩本書的 segno／coda 記號。fork 改成用書的模板在系統最上方比對（Audiveris `6d5f01b98`），這兩個模板就是它要讀的檔案。`templates/README.md` 補上說明和取樣來源。
- **`merge_pages.py` 合併後重新接好跳轉**：每頁各自匯出 `segno1`、`coda1` 這種名稱，合併後名稱會重複，D.S. 跳錯地方。現在合併時依文件順序重新編號：第 k 個 D.S. 指向第 k 個 segno，To Coda 指向它所在小節之後的第一個 coda。
- `docs/lessons.md`：MuseScore 3.6.2 會匯入 D.S. 的 Jump，但不會匯入 To Coda，D.S.／Coda 的播放要用 MuseScore-bandscore fork 驗收；書上的 segno／coda 要用模板，才不會把方框排練記號當成 coda。

### 後處理
- **`bandscore_postprocess.py`：套完 8va 後再清一次連結線**。八度線兩端的音高被移動，跨過兩端的連結線就不再是同音，成了不成對的連結線。

### 檢查工具不再誤報
- **`score_quality.py`**
  - `repeat_mismatch_between_parts` 只比反覆小節線。房子（1、2 番括號）本來就只寫在第一個聲部，以前 34 次誤報裡有 33 次是這個。
  - `transposing_key_mismatch` 把差 12 個五度的調號當成同一個調（例：期望 10 = -2、12 = 0），移調樂器不再被誤報；報告裡的期望調號也改用 -6…+5 的寫法。
- **`verify_musescore.py`**
  - 比對音高時套用聲部的 `<transpose>`（移調樂器、capo 吉他），不再整個聲部對不上。
  - MuseScore 把連續相同的小節畫成小節反覆記號時，那個小節的音照被反覆的小節計算，不再被當成空小節。

### songs/ 可以放在別處
- `songs/` 可以是指到另一個資料夾（例如自己的私人資料 repo）的連結：根目錄 `.gitignore` 改成連 `skill/songs` 這個連結本身也忽略。
- **`bandscore_postprocess.py` 執行 song hook 時把 `tools/` 放進 `PYTHONPATH`**：Python 會把 `songs` 連結解析成真實路徑，hook 裡用 `../../../tools` 找 `hook_lib` 的寫法就會找錯地方。現在 hook 直接 `from hook_lib import ...` 即可；手動跑 hook 時在 `skill/` 下用 `PYTHONPATH=tools python3 songs/<曲>/context/hook.py <merged>`（`hook_lib.py` 檔頭已改寫）。

### 準備頁面
- **`prepare_pages.py` 不把 PDF 的 soft mask 當成頁面**：有些 PDF 每頁帶一張透明度遮罩，`pdfimages` 會把它當成另一張圖抽出來，頁數變成兩倍、OMR 讀到空白頁。現在照 `pdfimages -list` 把 smask 刪掉。

### 文件
- `docs/formats.md`：`:gmN` 的編號是 1 起算（MusicXML 的 `midi-program`），很多 GM 表是 0 起算，照抄會全部少 1；補管弦樂常用編號。

## 2026-10-17：第二次同步（`4c7b52530`、`5991d264b`）
- 新工具：`clamp_offsets.py`（和弦代號、文字指示的位置拉回小節內）、`hook_lib.py`（逐曲 hook 用的整小節重寫、鼓、連結線、8va 函式）、`fix_lyrics.py`（歌詞校正）、`merge_full_score.py`（總譜合併）。
- 更新：`score_quality.py`、`page_ocr.py`、`bandscore_postprocess.py`、`apply_instrument_changes.py`（音色標示連動）。
- `SKILL.md`、`docs/lessons.md`：逐頁對圖精修的做法與常見錯誤清單。
- 拿掉 OCR 伺服器挑選工具 `ocr_pick.py`：使用者只要設 `PADDLE_OCR_URL`。

## 2026-10-13：說明書上線（`75ad4aed0`）
- 圖解說明書發佈到 GitHub Pages：https://hibikiwtnb.github.io/audiveris-bandscore/

## 2026-10-11：首次公開（`1fe2d7093`）
- `skill/`：SKILL.md、DEVELOPMENT.md、README、requirements.txt、tools/、templates/（兩本書的符號模板）、docs/（formats、known-gaps、lessons、symbol_templates、guide）。
- 根目錄 `CONTRIBUTING.md`、README 入口、`.gitignore`（`skill/songs`、`skill/environment.txt`）。
