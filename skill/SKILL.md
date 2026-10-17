---
name: audiveris-omr-structure-repair
description: 基於改修版 Audiveris（audiveris-bandscore 分支）的樂譜 OMR 結構修復與後處理工作流：把樂團譜／鍵盤譜 PDF 轉成可在 MuseScore 正確播放的 MusicXML。涵蓋頁面準備、OMR 提示配置（partsHint / defaultTimeSignature / PaddleOCR / endings）、輕量確定性後處理、音色變換、八度線注入、品質報告與驗收。
---

# 跑一首曲子

開發規則（簡單原則、merged 播放規則、長批次）在 [DEVELOPMENT.md](DEVELOPMENT.md)，動手前先讀。
檔案格式 → [docs/formats.md](docs/formats.md)；出問題 → [docs/lessons.md](docs/lessons.md)；已知缺口 → [docs/known-gaps.md](docs/known-gaps.md)。

前置：以下命令都在 `skill/` 目錄下執行；`environment.txt` 存在（沒有就照 `requirements.txt` 末尾的模板建立並填寫）；Audiveris 用本 repo 最新版編譯。
曲子資料夾 `songs/<編號_羅馬字>/`，下文記作 `S`，編號記作 `<id>`。

```
S/input/score.pdf        ← 使用者給的樂譜 PDF（檔名寫在 song_metadata.md 的 "- pdf:"）
   │ python tools/prepare_pages.py S                          Step 0
   ▼
S/input/omr_in/<id>_pNN.png   (+ S/crop_meta/*.json)
   │ 寫 S/context/audiveris_hints.txt + song_metadata.md        Step 1
   │ python tools/run_audiveris.py S S/input/omr_in/*.png      Step 2
   ▼
S/raw/*.mxl + *.omr
   │ python tools/bandscore_postprocess.py S                   Step 3
   ▼
songs/<輸入 PDF 檔名>.musicxml（審查用，在 songs/ 根目錄）  +  S/<id>_quality.txt  (+ S/pages/)
   │ 需要時：page_ocr → locate_labels → 寫 instrument_changes / ottava → 重跑 Step 3   Step 4
   │ DTD + MuseScore + verify_musescore + 讀 quality.txt       Step 5
   │ 寫 S/omr_report.md（每次跑 OMR 都寫）
   ▼
回報 merged 的位置與 quality.txt 的 [issues]
```

## Step 0：取得頁面圖

1. 把使用者給的樂譜 PDF 存成 `S/input/score.pdf`；`song_metadata.md` 的 `- pdf:` 寫它的檔名。
   使用者給的是頁面圖（PNG）時不用 PDF：依頁序存成 `S/input/extracted/e-001.png`、`e-002.png`…，`- pdf:` 不寫（merged 以 `<編號>_<曲名>` 命名，曲名取 `- Title:` 括號前的部分）。
2. `python tools/prepare_pages.py S`：用 `pdfimages` 抽 PDF 內嵌原圖（不用 pdftoppm 重新點陣化），去標題、裁邊、約 2x 放大並壓到 < 20MP，存成 `input/omr_in/<id>_pNN.png`，裁切紀錄寫進 `crop_meta/`（進 git）。已經做過的頁會跳過。提示檔寫 `split_pages=true` 時每頁切成上下半頁（`<id>_pNNa` / `<id>_pNNb`，各 2x），見 `docs/formats.md`。
3. 約束（已由腳本處理，換腳本時要守住）：
   - Audiveris 單圖上限 20MP，超過會 `Too large image` 整頁被略過；放大約 1.8~2.0x，但總像素必須 < 20MP。
   - 裁掉標題時要保留第一個 system 的樂器名稱、Tempo 記號、和弦記號與排練標記。
   - 頁面檔名一律 `<id>_pNN`（半頁 `<id>_pNNa` / `<id>_pNNb`），後續工具靠這個格式找檔。
   - 輸入圖的路徑不能含使用者名稱：Audiveris 會把完整路徑寫進 `.mxl` 的 `<source>` 與 `.omr`（`run_audiveris.py` 會先複製到 `environment.txt` 的 `WORK_DIR`）。

---

## Step 1：寫 `context/`

啟動 OMR 前，目標是以**最低成本取得足夠的音樂結構脈絡**，讓後續處理有合理的基準：

### 1. 最小必要輸入（先讀文字，省 token）
1. `<OCR_PYTHON> tools/page_regions.py "S" 1 2` → `S/context/page_regions.txt`（幾秒鐘）。
   內容：A 區（曲名、作詞作曲）、B 區（樂器全名／縮寫）、C 區（頁碼）的 OCR，各區邊界、每行譜表（system、y 範圍、線數）、每個詞的外框座標，以及 `partsHint` 草稿和 doubts。
2. 以這份檔為依據寫 `context/audiveris_hints.txt`：草稿沒有疑點時直接採用，自己補 `:lyrics`（人聲）、`:drums`（鼓）和每個非鼓聲部的開頭音色 `:gmN`（看第一頁的音色標示，見 formats.md）；有 `:lyrics` 時看一段歌詞，寫 `lyricsScripts`（歌詞用到的字種，見 formats.md）。拍號等檔裡沒有的資訊，或有疑點時，用檔裡的座標自己決定要看圖的哪裡。
3. A 區的曲名、作詞作曲順手寫進 `song_metadata.md`。
4. 使用者說了這首屬於哪本樂譜集時，在 `audiveris_hints.txt` 加一行
   `org.audiveris.omr.sheet.note.NoteHeadsBuilder.templateDir=templates/<書名>`（相對於 repo 根目錄，`run_audiveris.py` 換成完整路徑）（鼓的叉頭改用該書模板找）。
   開頭是降號調、而且該書資料夾有和弦模板（`chord_<根音>b.png`）時，加 `org.audiveris.omr.text.ChordFlats.openingFifths=<負的降記號數>`（照 `song_metadata.md` 的開頭調號），OCR 漏掉的和弦 ♭ 由模板補上。
   書名與資料夾對照見 [templates/README.md](templates/README.md)；資料夾不存在時照 templates/README.md 挑例子學一次，把 `check_<名稱>.png` 給使用者確認。使用者沒說就不加。

`partsHint` 是全名 `|` 縮寫、由上到下（例：`A.Piano|A.pf:2; Strings I|Str. I:1;...`），語法見 [formats.md](docs/formats.md)。

### 2. 低成本加分項（推薦並行掌握，不卡主線）
對樂曲掌握越多，後續驗收與核對越不容易走偏。以下為低成本且高收益的輔助動作：
- **快速瞄一眼曲末與結構標記**：
  花幾秒看最後一頁或翻一下段落：確認曲末有無 Coda、D.S. / D.C. / Fine，以及是否有明顯的 1、2 番反覆房子（若完全沒有反覆房子，即可在提示檔放心設定 `endings=false`）。
- **並行查詢歌曲背景元數據（推薦）**：
  花 1 分鐘在網路檢索該曲的官方資訊或曲庫資料，記錄至 `S/context/song_metadata.md`：
  - 曲名、藝人/作曲、風格流派
  - 原曲基準 BPM / 速度標記（供後續驗證開頭 Tempo）
  - 原曲基準調號（Key）與是否有中途轉調
  - *注意地位*：外部資料作為 Sanity Check 輔助參考，樂譜影像印刷事實仍為第一權威。
  - 同一個檔也放後處理要套用的拍號、速度、速度變化、排練記號，格式見 [formats.md](formats.md)。

---

## Step 2：跑 Audiveris

```bash
python tools/run_audiveris.py S S/input/omr_in/*.png
```
- 路徑與 binary 全部來自 `environment.txt`，缺什麼就報錯，不猜。
- 逐行把 `context/audiveris_hints.txt` 轉成 `-constant`。OCR 用 PaddleOCR，服務位址寫在 `environment.txt` 的 `PADDLE_OCR_URL`（本機或區網的機器，先自己啟動：`<OCR_PYTHON> <PADDLE_OCR_SERVER>`），腳本把位址傳給 Audiveris，只檢查 `/health`，沒開就報錯停止，不會啟動或關閉它。
- 用哪台 OCR：跑批次前 `python3 tools/ocr_pick.py`，從 `PADDLE_OCR_CANDIDATES`（逗號分隔，依序嘗試；預設只有本機）挑第一個有回應的寫進 `PADDLE_OCR_URL`。log 裡有 OCR 失敗的那次算失敗、重試（Audiveris 遇到 OCR 失敗會照樣輸出沒有文字的結果）。
- 每頁最多重試 3 次，成功後搬到 `raw/`（`.mxl` + `.omr`）；已完成的頁會跳過。
- **binary 要是最新版**：`git pull` 後在 repo 根目錄重新編譯（`./gradlew :app:installDist -x test`；原始檔為 CRLF，手改時保持）。
- 一次只跑一個進程（Audiveris 與 PaddleOCR 都吃記憶體）；長批次用 `setsid` 背景執行並寫進度到檔案（見 DEVELOPMENT.md）。
- 偶發 `FileSystemAlreadyExistsException`（存 `.omr` 時）重試即過；log 先出現 `UnmarshalException` 的是真崩潰，重試無效，要修原始碼。
- 已存好的 `.omr` 只改了匯出邏輯時，可 `Audiveris -batch -export -output <dir> -- <page>.omr` 重新匯出，不必重跑 OMR。

---

## Step 3：執行輕量後處理（`bandscore_postprocess.py`）

執行本倉庫核心處理引擎：
```bash
python tools/bandscore_postprocess.py S
```

### 後處理引擎核心保證（小節長度不超過拍號，弱起小節除外）
1. **排練記號回掛（`rehearsals_from_credits`）**：
   - Audiveris 若將外框中的排練字母（如 A、B、C）誤作為頁面 credit 匯出，工具自動讀取 `.omr` 幾何座標，將其轉回為小節首位置帶方框的 `<rehearsal>`。
2. **空小節補齊（`fill_empty_measures`）**：
   - 缺漏音符或休止符的完全空小節會導致 MuseScore 播放引擎死鎖凍結。自動為所有聲部補入帶有 `measure="yes"` 的全小節休止符。
3. **超長聲部修整（`trim_measure`）**：
   - 超長的聲部先處理附點（`drop_dots`）：先拿掉這個聲部所有的附點，再從左到右一個一個加回來，加下一個就會超長時停下。小節不足的部分由下面的補齊步驟補休止符。OMR 常把符頭旁的筆畫（例如書上叉頭的腳）當成附點。
   - 仍超出小節線的聲部在小節線處切掉：清除無印刷休止符的假 `<forward>`、或接延音線前的假休止符；否則縮短跨過小節線的音，刪掉小節線之後開始的所有東西（音符也刪）。一個聲部讀錯不能把所有聲部的小節撐長；刪掉的音列在輸出的 `overflow_cut`。
4. **聲部時值對齊與游標維護（`pad_measure` & `fix_backups`）**：
   - 時值不足的聲部自動以標準休止符補齊，最多補到拍號的長度（不看其他聲部多長）；
   - 補齊後自動重算小節內 `<backup>`，保持多聲部游標絕對精確。
   - Audiveris 常**沒寫 `<backup>` 就接另一個 voice 的音**：在前一 voice 後插休止時會補一個等長 backup（`keep_cursor`），否則後面的音會被推出小節線（297 p08 m5 實例）。
   - 過短的整小節休止符直接延長，不在後面另補休止。
5. **合併與雜訊清理**：
   - 自動將頁面拼接為全曲總譜。
   - 調用 `tools/fill_measure_repeats.py`：每頁分開做 OMR，頁首的小節反覆（%）沒有前一小節可抄，只剩休止符；合併後改抄上一頁最後一小節的音符（不抄 tie 與歌詞）。
   - 調用 `tools/fill_slash_chords.py`：斜線（吉他「前一個和弦照這個節奏再彈」）匯出時只有暫定音高；改成前一個和弦（同譜表同聲部，跨頁也算）的所有音，符頭保持斜線，時值與連結線照斜線。前面沒有和弦的斜線不動，輸出會列出來。
   - 調用 `tools/clean_score_noise.py` 清除未經驗證之碎片化 `<slur>`、補齊和弦內聲部漏識的 Tie、清除異音或懸空的無效 Tie。
   - 有 `context/instrument_changes.txt` / `context/ottava.txt` 時接著自動套用（兩支都有防重複套用）。
   - 有 `context/song_metadata.md` 時接著由 `apply_score_hints.py` 套用拍號、速度與排練記號（格式見 Step 1）。
   - 有 `context/hook.py` 時接著執行 `python hook.py <preview>`（只放資料檔表達不了的逐曲修正，如 216 的 `<transpose>`）；沒有就跳過。
   - 最後由 `tools/unify_keys.py` 統一調號：樂隊轉調是全體一起，單一聲部調號不同視為 OMR 錯誤。某小節有聲部換到調號 v 時，至少一半聲部同時換、或其他聲部下次換的也是 v 就採用；孤立、沒人跟上的（如誤讀成 0 的還原記號）丟棄；採用的時間線寫進所有聲部。有 `<transpose>` 的聲部與打擊樂不動，所以要保留不同寫法的聲部（如 capo 吉他）必須在這一步之前已帶 `<transpose>`（216 由 `apply_216_global_fixes.py` 加）。輸出會列出被丟棄或延後採用的變化，以及只持續一小節的調號（`check:` 行，需對照原譜）。
6. **歌詞與路徑**：
   - 器樂聲部的 `<lyric>` 轉成譜下 `<words>`（碎片刪除）；**名稱或縮寫含 Vocal / Vo. / Voice / Chorus / Cho. 的聲部保留歌詞**（已實作）。
   - `<source>` 與 `source-file` 只留檔名（`scrub_paths`）。
7. **品質事實報告（`score_quality.py`，自動）**：
   - 真正的最後一步是 `tools/clamp_offsets.py`：和弦代號、文字指示的位置是「前面的音＋offset」，前面的音被後處理或 hook 改短、改寫後，offset 可能指到小節開頭之前（MuseScore 畫在譜號左邊，整行排版被撐壞）。這一步把它拉回小節內，並列出移動了哪些。`quality.txt` 的 `offset_outside_measure` 應該是 0。
   - 後處理最後對 preview 跑一次 `tools/score_quality.py`，印在輸出末尾並寫成 `S/<song>_quality.txt`（不含時間戳，重跑沒變化時檔案不變，和上一份比就看得出這次修改讓哪些項目變好或變差）。
   - 每次修改工具或提示檔後重跑，把新舊 `_quality.txt` 的 `[issues]` 比一下，再決定要不要交付。
   - **重跑後一定要跑對照**：重跑前先把 `<id>_quality.txt` 複製成 `<id>_quality.prev.txt`，重跑後 `python3 tools/compare_quality.py songs/<曲>/<id>_quality.prev.txt songs/<曲>/<id>_quality.txt`（在 git 裡管理曲子時，舊檔也可以寫 `HEAD:<路徑>`）。它列出樂譜結構的變化：頁數、小節數（每頁）、聲部、譜線數、各聲部的調號時間線與移調、排練記號、反覆與房子。有變化時 exit 1：逐項對照原譜，寫進 `omr_report.md`（變好／變壞／未確認）。DTD 和 `verify_musescore` 全過不代表沒有退步（曾發生：五線譜變一線譜、吉他調號被蓋掉、轉調位置延後，這些檢查全部通過）。
   - `[issues]` 最後四項是要對照原譜的清單，不是錯誤：`staff_lines_change`（譜表中途換線數）、`transposing_key_mismatch`（有 `<transpose>` 的聲部調號和其他聲部對不上）、`out_of_range`（音符超出開頭音色的常用音域，音域表是近似值）、`harmony_root_without_key_accidental`（和弦根音沒有升降記號，但調號裡這個音有：可能是 OCR 漏了 ♭／♯）。

---

## Step 4：音色變更與八度線（依曲目需求）

樂團譜與鍵盤譜常有音色標註（`Synth Pad`、`pizz.`、`Bell`）與八度線（`8va`、`15ma`、`coll'8va`）。Audiveris 只 OCR 它判為文字的區域，小的斜體標示大多漏掉，而且常把標示以 `<lyric>` 掛在錯的聲部。改用整頁 OCR＋幾何定位，少讀圖：

```bash
<OCR_PYTHON> tools/page_ocr.py S                  # → page_ocr/pNN.json
python3 tools/locate_labels.py S > /tmp/labels.tsv  # 頁 / 行 / 聲部 / 譜表 / 小節 / 拍 / 文字
python3 tools/omr_beat_grid.py S <頁>              # 需要精確位置時：在 .omr 圖上畫小節號與拍點
```

讀清單的做法：
- 聲部 = 文字下方最近的譜表；用 `.omr` 的 part id（partsHint 邏輯編號，**缺席聲部會跳號，不能用順序**），譜線高度按文字 x 內插（譜表會傾斜）；`special="CAUTIONARY"` stack 已排除。
- 讀清單的規律（297 出版社寫法）：「┌ X →」開始；「— X →┐」（鉤朝下）結束；行末「— X →」是接下一行的提醒。8va 標示之間**沒有虛線**，一段可跨好幾行；同一譜表上 8va / coll'8va 必定「開始、結束」交替，照順序配對；括號型「┌ 8va ──┐」一個標示就是整段。音色標示出現處即「從此是該音色」，只有回到原音色（pizz.→arco、(8va) 結束）要看結束位置。
- **只在清單判斷不了時看圖**（配不成對、分不出結束或提醒、不認得的音色名）。
- 試過並放棄：用像素形狀自動判斷「┌」／「→┐」——符槓、小節線、斜譜線一直干擾，不划算。

拿到清單後寫 `context/instrument_changes.txt`、`context/ottava.txt`（格式見 [formats.md](formats.md)），重跑 `bandscore_postprocess.py` 即可重建 preview。

做法（已定，不用再試）：每種音色一個 instrument，**每個音符（含休止符）**帶 `<instrument id>`；八度用 `<octave-shift>`，不用樂器移調（MuseScore 只在換樂器時才套 transpose）；標示區段內 Audiveris 自己產生的 octave-shift 是把標示括號誤判成 8va 線，先移除並還原音高。

---

## Step 5：驗收與交付

### 1. 程式化檢查（Agent 交付標準）
- **結構與 DTD 檢查（0 violations）**：
  ```bash
  python tools/dtd_order_check.py songs/<輸入 PDF 檔名>.musicxml
  java tools/DtdValidate.java songs/<輸入 PDF 檔名>.musicxml tools/dtd
  ```
  preview 沒有 DOCTYPE，`DtdValidate` 會自動補上 3.1 的再驗證（回報的行號會比檔案多 1）。
  確保所有 `<barline>`、`<ending>`、`<attributes>` 等元素符合 MusicXML 3.1 DTD 規範。
- **MuseScore 開啟／轉檔檢查（0 errors / warnings）**：
  以 MuseScore headless 執行無頭轉檔，檢查日誌：
  ```bash
  <MUSESCORE_BIN> -o /tmp/test.pdf songs/<輸入 PDF 檔名>.musicxml
  ```
  - **常見報錯排查**：不能出現 `要素 rest がこのスコープ内で定義されていません`（元素順序錯誤）、`不完全小節 / 長すぎます`（時值不對齊）、`spanner already started` 等。
  - **死鎖排查**：轉檔進度必須順利完成，不能因 0 duration 空小節卡住。
  - **修復要求**：若有轉檔錯誤，需定位至具體小節修復 XML，直到 MuseScore 載入無報錯。

- **MuseScore 實際結果檢查**（顯示音高、換樂器、8va；exit 0 才算過）：
  ```bash
  python3 tools/verify_musescore.py songs/<輸入 PDF 檔名>.musicxml
  ```
  逐譜表、逐小節比對 MuseScore `.mscx` 的顯示音高與「XML 音高 − 該譜表 8va 線」，並列出每譜表 InstrumentChange / Ottava / 隱形音數；同一聲部兩譜表間移動的音標為 cross-staff，不算錯。8va 之後才開始的差異，通常是各聲部小節長度不一致（見避坑 4）。
- 事實報告（後處理已自動產生 `<id>_quality.txt`；`tools/score_quality.py` 只印事實、不下判斷、永遠 exit 0，輸出給 agent 讀；手動重跑：`python3 tools/score_quality.py songs/<輸入 PDF 檔名>.musicxml`）：
  前段是基本資訊（頁數、小節數、音符數、速度、排練記號、反覆記號、房子、Segno/Coda/D.S./D.C.、各聲部音符數與調號）；`[issues]` 段列出樂理上的不一致（小節長度不符拍號、非標準時值、tie／八度線不成對、各聲部調號不一致、反覆記號與房子不完整或各聲部不一致），每項給次數與小節位置。`[issues]` 只是「檢查到什麼」，是否真的錯要對照譜面判斷。交付時在回報裡附上 `[issues]` 各項次數，說明哪些已對照譜面確認是原譜本來如此、哪些是未處理的已知缺口。移調樂器（有 `<transpose>`）不參與調號比對。
  - **排練標記常識檢查**：審視報告中的 `rehearsal_marks` 序列是否連續（如 A->B->C... 或 A1->B1->C1...）；若出現跳字母（如 A->C、A1->D1），視為 OMR 漏識或認偏異常，建議優先以低成本手段修復（見避坑指南 8）。
- 小節時值統計（需要時）：`python3 tools/measure_duration_audit.py --files S/raw/*.mxl`

### 逐頁對圖精修（使用者要求時）
程式化檢查全過，不代表聽起來對。精修時逐頁把輸出（`mscore -r 100 -o p.png`）和原譜頁面圖對照，修正寫在 song hook，整小節重寫、鼓、反覆、8va 用 `tools/hook_lib.py`。常見錯誤清單和寫法見 [lessons.md](docs/lessons.md) 12。

### 結果報告 `S/omr_report.md`（每次跑 OMR 都寫）
跑完 Step 5 後寫（重跑時整份改成這次的結果）。內容：
- 輸入：頁面來源、送進 OMR 的頁（沒送的頁與原因）、`audiveris_hints.txt` 的重點（partsHint、templateDir、開關）。
- 使用的版本：audiveris-bandscore 的 commit。
- 轉換過程的改動：為這首修了哪些工具或 Audiveris 原始碼（原因、commit）、重跑了哪些頁、手動處理了什麼。
- 結果：merged 路徑、Step 5 各項檢查結果、`[issues]` 各項次數與判斷（原譜如此／OMR 錯／未確認）。
- 已知問題：還沒解決、要使用者試聽時注意的地方。

### 2. 人工播放檢查（由使用者在 GUI 試聽）
由使用者在 MuseScore GUI 實際試聽：
- 開頭速度（Tempo）是否正確；
- 音色變換（如 Pluck、Lead、Strings）是否平滑，無多餘斷音或雜音；
- 八度線（8va/15ma）區間音高是否符合原曲聽感；
- 長音和弦內聲部延音是否連貫。
- 若試聽發現聽感異常，反饋具體小節與現象進行調整。

---
