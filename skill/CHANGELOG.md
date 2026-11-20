# 變更履歷（skill/）

這裡只記 `skill/`（AI agent 用的 BandScore 流程、工具、模板、文件）的變更。Audiveris 本體（Java）的改進見根目錄 README 第 2 節。日期是同步到本 repo 的日期，括號裡是 commit。

## 2026-11-20：半譜表調號正規化

- **`tools/unify_keys.py`**：雙譜表樂器若只有單手讀出調號（`<key number="1|2">`），`key_events()` 現在會收集同小節的編號調號（同小節兩譜表給出不同 `fifths` 時記錄衝突並以其他聲部時間線為準），且 `main()` 在比對聲部仍含 `<key number>` 時強制改寫為單一全聲部 `<key>`，移除編號屬性。維持 `<transpose>` 與打擊樂跳過規則。
- **`tools/tests/test_unify_keys.py`（新）**：覆蓋單譜表換調、重複編號調號正規化、孤立單譜表換調不誤擴散、同小節雙譜表調號衝突記錄與移調/打擊樂跳過規則。

## 2026-11-17：中文字型自動尋找

- **`tools/fonts.py`（新）**：`proof_pairs.py` 與 `omr_beat_grid.py` 共用的字型解析。依序找 macOS（Hiragino Sans GB、PingFang、STHeiti、Arial Unicode）、Linux（Droid Sans Fallback、Noto CJK、文泉驛、AR PL UMing）、Windows（微軟正黑、黑體、宋體），再問 fontconfig 與系統字型資料夾。載入後先確認畫得出「中」才採用：`fc-match ':lang=zh'` 常指到只有拉丁字的 DejaVu Sans，用下去標籤就變方框。中文與拉丁字在同一顆字型時整串用它；分開時逐段換字型，像 Linux 的 Droid Sans Fallback 沒有數字和拉丁字母，混排也不會出現方框。真的找不到中文字型時在 stderr 印一次警告，不再默默產出方框標籤。
- **`tools/proof_pairs.py`**：標籤改用共用的解析；macOS 行為不變，Linux 上「原譜／第 N 行／OMR／小節範圍」等中文標籤正常，圖寬、標籤條高度與小節對齊都不變。
- **`tools/omr_beat_grid.py`**：移除自己的 Arial 硬編碼路徑清單，改用共用的拉丁字型解析（以前在 Linux 掉回點陣字，小節號和拍點數字很小）。
- **`SKILL.md`**：對照圖一節註明字型是自動找的。

## 2026-11-16：吉他與貝斯八度移調

- **`tools/apply_tab_octave.py`（新）**：吉他與貝斯吉他的記譜比實音高一個八度，轉出的 MusicXML 少了 `<transpose>`，播放與音域檢查都高一個八度。對沒有八度移調的吉他、貝斯聲部補 `<octave-change>-1`；已有 capo／降半音的 `<chromatic>` 保留，只補八度。合成貝斯、低音管、長號、低音號、低音提琴不套用。
- **`bandscore_postprocess.py`**：在 `unify_keys.py` 之後自動執行這支工具（放在調號統一之後，吉他、貝斯仍參與調號比對；八度不改變調號）。

## 2026-11-16：反覆與房子稽核工具

- **`tools/audit_repeats.py`**：唯讀稽核 merged MusicXML 的反覆與房子。逐首列出 forward／backward 反覆、房子時間線與頁碼，重現 `score_quality.py` 的五項反覆標記，並印出被標記小節的右小節線樣式、印刷文字與附近的 segno／coda／D.S.／D.C. 供對照原譜。`--all` 掃 `songs/`（略過 `pages/`），`--table` 每首一行 TSV。
- **`SKILL.md`**：Step 7 補上使用時機與判讀原則（只有 `light-heavy` 帶 `<repeat>` 才是印譜的反覆線）。

## 2026-11-16：merged MusicXML 輸出位置與命名統一

- **`bandscore_postprocess.py`**：merged `.musicxml` 改寫入各曲資料夾 `<song_dir>/` 內，不再寫到上層 `songs/` 根目錄；檔名改優先依 `song_metadata.md` 的 `- Title:` 統一為 `<id>_<title>[_Keyboard].musicxml`（`songs/<series>/<song>/` 分層時各曲檔案皆自成目錄）。
- **`SKILL.md`**：更新 `songs/<系列>/<編號_羅馬字>/` 路徑範例與驗收指令。

## 2026-11-13：全音符模板門檻

- **`bandscore_postprocess.py`：補滿小節的休止符，在同一譜表另一個聲部有音的地方隱藏**。Audiveris 常把一行旋律拆成兩個聲部（前半在一個、後半在另一個），補拍數時印出來的二分、八分休止符原譜沒有，校對時被報成「多出休止符」。
- `templates/README.md`：一線譜（打擊樂）的全音符也用灰階模板找（只找線上和緊貼線的位置）；二值化會把小節反覆記號認成全音符。
- `templates/README.md`：全音符模板中段的門檻 `hollowMinGrade` 從 0.6 提高到 0.85，整個符頭的門檻 0.65（Audiveris 本體；和弦裡的全音符整個符頭只有 0.7–0.9，同一個 0.85 會擋掉和弦音）。以前和弦中間的音被上下鄰音拉低到 0.9 左右，門檻只能放低，低音譜號、轉調處的還原記號、文字（0.79–0.86）因此被當成全音符；現在比對的中段只量符頭（模板裡的譜線不算），真的全音符都在 0.9 以上。內建預設模板維持 Sunshine 那一份：μ's 的模板筆畫細、洞圓，會把附點黑符頭和弦、字母 o/c/e 認成全音符。

## 2026-11-12：找不同校對單位

- **`tools/proof_pairs.py`**：把校對拆成「原譜一行（約 4 小節）」的單位。每個單位一張圖，上半是原譜（取自 `raw/*.omr` 的 BINARY.png，小節框和譜線座標來自專案檔，裁得準），下半是同樣小節的 MusicXML 經 MuseScore 渲染（整份照原譜的換行一次渲染再逐行裁切，小節反覆記號 %、行首譜號調號、行尾提示調號都和原譜一樣）；下半每個小節依 `.mpos` 的位置拉伸到原譜的寬度，小節線上下對齊。不畫樂器名和拍號（原譜行首沒有）。另附同樣小節的音符文字清單（譜面書寫音高，8va 已扣回，隱藏的 coll'8va 重疊音有標記）。一個單位最多兩行譜表（`--max-staves`，大譜表自己一個，單行聲部兩兩一組，聲部不拆開），圖的大小不隨聲部數變；原譜那一行沒印的聲部不出圖，`index.txt` 列出來，MusicXML 在那裡有音符時特別標出。agent 校對時只要找上下的不同，不必自己裁圖、定位。

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
