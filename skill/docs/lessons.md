# 教訓與邊界（出問題時查）

# 引擎已經做掉的事（audiveris-bandscore 分支）


| 核心改進項 | CLI 參數 / 機制 | 解決的根本問題 | 後處理不再需要做的事 |
|---|---|---|---|
| **預設拍號補齊** | `-constant org.audiveris.omr.sheet.rhythm.PageRhythm.defaultTimeSignature=4/4` | 逐頁各自開 book 跑 OMR 時，第 2 頁起找不到拍號，時值不檢查 | 不再需要全域 rebar 猜拍號 |
| **整小節休止符隔離** | 核心邏輯（永遠生效） | 拍號已知時，整小節休止符**一律等於應有時值**，不再抄該格實際長度：過長（某聲部多讀，初版修正）或過短（某聲部漏讀，`b11861f73`）都不會牽連其他聲部；弱起小節除外 | 消除 75%+ 的偽 OVER；297 過短的整小節休止符 8 → 0 |
| **樂器拓撲提示（partsHint）** | `-constant "org.audiveris.omr.score.PartCollation.partsHint=..."` | 依每行譜表的數量與位置對上提示中的樂器，缺失聲部自動補空 | **完全廢止** 每首曲子個別編寫 `normalize_*.py` |
| **PaddleOCR 支援** | 預設（`ocrEngine=tesseract` 改回 Tesseract） | 支援本地 PP-OCRv5，和弦識別率從 59% 提升至 90%+，杜絕排練記號變漢字 | 大幅減少 OCR 錯字後處理 |
| **和弦名語法擴充** | 核心邏輯（永遠生效） | 支援 `add2/4/9/11/13`、自動合併間隔後綴（如 `E sus4` $\to$ `Esus4`） | 不需要手寫和弦抽取重組腳本 |
| **Volta 開關（endings）** | `-constant org.audiveris.omr.sheet.ProcessingSwitches.endings=false` | 避免演奏法延續線（如 `— pizz. —↓`）被誤判為 1、2 房子括號 | 無房子的樂譜不再產生假 Ending |
| **小節反覆號（%）修正** | 核心邏輯（永遠生效） | 遇到 `%` 時只複製該譜表聲部並倒回小節起始，不再拼接出 8 拍小節 | 不再需要事後拆分小節 |
| **引擎穩定性防護** | 核心邏輯（永遠生效） | 修正退化線段、空 RunTable 重載、side stems null、word bounds 越界等崩潰 | 不再需要針對崩潰頁面切換 binary |

---

# 避坑指南與關鍵邊界約束


## 1. 歌詞處理的聲部特化規則（重要邊界）
- **器樂譜（Instrumental Score）**：
  樂譜中殘留的 `<lyric>` 通常是誤識的樂器文字（如 `pizz.`、`8va` 殘片）。若未閉合，MuseScore 會跨行繪製長破折號（短橫線）。`bandscore_postprocess.py` 預設將這些轉為譜表下方文字。
- **人聲 / 樂團總譜（Vocal / Band Score）**：
  若樂譜包含 **Vocal** 或 **Chorus** 聲部（如 132），**絕不可對人聲 Part 無差別執行 `lyrics_to_words`**！
  已實作：聲部名稱或縮寫符合 Vocal / Vo. / Voice / Chorus / Cho. / 歌 的聲部保留 `<lyric>`；新曲若人聲聲部名稱不同，要擴充 `bandscore_postprocess.py` 的 `VOCAL_RE`。
- **源頭控制**（歌詞判定在 TEXTS 步驟，遠早於聲部對應，所以哪些聲部有歌詞要由人提供）：
  - 器樂譜：提示檔加 `org.audiveris.omr.sheet.ProcessingSwitches.lyrics=false`（Audiveris 內建全曲開關；297 已加）。
  - 有人聲的譜：在 partsHint 的人聲聲部後加 `:lyrics`（見 Step 1），只有人聲下方判歌詞。
  - 兩者都用了之後，後處理的 `lyrics_to_words` 只剩保險作用。
- 注意：關掉後文字掛在哪個聲部仍由 Audiveris 決定，音色標示的正確聲部還是以 `instrument_changes.txt` 為準。

## 2. 樂譜反覆房子（Endings / Volta）
- **`endings=false` 僅限於「全譜完全沒有 1、2 房子」的曲目**：
  關閉此開關能防止譜表上長段延音線被誤判為房子括號。但若樂譜本身帶有真正的 1、2 番反覆，此開關**必須設為 true**，否則會破壞宏觀反覆結構。

## 3. Tie（延音線）嚴格同音原則
- 規則與處理見上方「延音線（Tie）同音約束與通用和弦漏 Tie」：`<tie>` / `<tied>` 只能連相同音高，跨音高的一律是 slur 被誤認，需清除；和弦缺漏的同音內聲部要補 tie。

## 4. 八度線（Ottava）與聲部長度等長法則
- MuseScore 計算八度線（`<octave-shift>`）的有效終點時，是以**該 Part 內部的累計時間**為準。
- 若同小節中 Part A 長度為 4 拍，Part B 因漏音只有 3.5 拍，則 Part B 後續所有的八度線起訖點將全部產生 0.5 拍的累積位移！
- 因此，`pad_measure` 必須將同小節內所有較短的聲部強制對齊補滿至小節或 Stack 的最大長度。

## 5. 機密資訊脫敏
- Audiveris 預設會將本機絕對路徑（包含本機帳號名稱）寫入 MusicXML 的 `<source>` 與 `source-file` 欄位，以及 `.omr` 的 book.xml。
- 後處理已把 preview／pages 的路徑過濾為純檔名；**raw 的 `.mxl` / `.omr` 則要靠輸入路徑本身不含帳號名稱**（`run_audiveris.py` 已先複製到 `WORK_DIR`）。297 現有 raw 檔仍含舊暫存路徑（私人 repo 可接受，公開前要重跑）。

## 6. MuseScore 3.6 的樂器與八度行為（實證）
- `<instrument id>` 一變才建 InstrumentChange；**休止符沒帶 id 會在同一音色間反覆切換**（297：Str. I 切了 88 次）。
- 八度必須用 `<octave-shift>`。`<transpose>` 寫在聲部開頭時 MuseScore 會套用（2026-10-08 用 3.6.2 實測：216 A.Guitar capo 1，記譜 G 播成 A♭；140、226 降半音的吉他、貝斯也對），舊的「沒有換樂器就不生效、播放低半音」不成立。`<pitch>` 是**記譜音高**，實音 = 記譜 + `<chromatic>`。`score_quality.py` 與 `unify_keys.py` 不檢查／不動有 `<transpose>` 的聲部。
- 降半音的 `<transpose>` 要寫 `<diatonic>0</diatonic><chromatic>-1</chromatic>`（記譜 A、實音 A♭）。3.7 Evolution 曾把明寫的 diatonic 0 改算成 -1，實音拼成 G♯；我們的 MuseScore fork 已修（e15c0f445）。
- 做不到：換樂器後譜表名稱變成樂器庫縮寫（Cel.、Glock.、Hch.、St.），`<instrument-abbreviation>` 無效；`pizz.`/`arco` 文字與 `<sound>` 內的 `midi-program` 都被忽略，要切只能換樂器。
- 器樂 `<lyric>` 的 begin/middle 沒收尾 → 一路畫連字號（「選不中、刪不掉的短橫線」）。
- `6(9)` 若寫 `parentheses-degrees` 會被讀成 `69()`（fork 已修匯出）。

## 7. Audiveris 仍會出現、後處理補不了的
- 漏掉整小節或全音符／二分音符，只剩休止符（297：m45 鋼琴、合成器 7 處）。**目前沒有手動補音的層**，是現行流程的缺口。
- 把音符放到小節線後（時間定位錯誤）：後處理保留，其他聲部補到同長度。
- 偶爾多切／少切一個小節、漏掉整條譜表。
- 修在哪裡的取捨（ROUND1 實例）：判斷邏輯錯且每首都會遇到 → 原始碼；只對某些曲子成立 → 參數；需要跨頁或全曲資訊 → 後處理；人一眼看出、程式難讀 → 提示檔。修原始碼先用一頁重現、只驗那頁，再批次；崩潰按「root exception＋最底層 Audiveris frame」分類。

## 8. 排練標記（Rehearsal Marks）的商業樂譜邏輯與跳字母異常檢驗
- **商業總譜出版慣例（常識基線）**：
  - 商業出版樂譜（Band Score）開頭通常為無字母標記的 Intro（或明記 Intro 字樣）；一旦進入字母排練記號，**必定按照字母順序嚴格連續遞增**（如 `A -> B -> C -> D...`，或多段式 `A1 -> B1 -> C1... A2 -> B2 -> C2...`）。
  - 商業總譜極其罕見無故跳過字母（例如 `A` 直接跳 `C`，或 `A1` 直接跳 `D1`）。
- **異常判定（Red Flag）**：
  - 運行 `tools/score_quality.py` 檢查時，若輸出中的 `rehearsal_marks` 序列出現跳字母現象，**應直接視為 Audiveris OCR 方框文字時漏識或認偏的異常**，不可盲目默認其合理性。
- **低成本修復指南（建議採用，不強制）**：
  - **切勿重跑全頁 OMR**：重跑 Audiveris 批次耗時極大且無必要，排練記號修復純屬語義與文字層校準，應於後處理階段解決。
  - **段落特徵快速定位**：排練記號在 99% 的情況下緊隨段落邊界出現，即緊跟在雙小節線（`bar-style="light-light"`）、反覆記號（`repeat`）或換行（`new-system="yes"`）之後的小節首。
  - **輕量切片核對**：僅針對疑似漏掉字母的小節頂部做快速局部切片（如局部 OCR、ASCII 陣列預覽），確認原譜真實字母。
  - **自動鉤子注入**：在 `context/song_metadata.md` 的 `- rehearsals:` 行補上小節=標記，重新執行 `python tools/bandscore_postprocess.py S`，數秒即可自動合流並完成全局修復。
  - **靈活度約束（不強制）**：本項修復為推薦的最佳實踐，但**不強制每首曲目都必須完全補齊**。對某些視覺分析或工具鏈調用成本較高的模型/環境而言，逐小節查圖可能較耗時，可依據任務優先級與時間成本靈活取捨。

## 9. OCR 伺服器與 GPU
- **性能實測**：以 `--device gpu:0`（全 fp32 模式）在 GPU 上運行 PaddleOCR 伺服器，單頁 OCR 約 2.6 秒，較 CPU 快約 10 倍。
- **使用**：
  - GPU 版顯存約 2.1GB。
  - 跑批次前 `python3 tools/ocr_pick.py`：從 `PADDLE_OCR_CANDIDATES`（逗號分隔，依序嘗試；預設只有本機）挑第一個有回應的寫進 `PADDLE_OCR_URL`。`run_audiveris.py` 本身只用 `PADDLE_OCR_URL`，不挑伺服器。

## 10. 細筆畫與去譜線（2026-10-06，054 調號）
- **Audiveris 去譜線本來就保留穿過譜線的筆畫**：譜線 glyph 不含交叉處的像素。實測在 `Picture.buildNoStaffBuffer` 加「上下都黑就保留」的處理，054 p02／p03 一個像素都沒有恢復、結果完全不變，已撤回。zemsky 的 `staffRemoveWithScan` 不是我們的差異點。
- **054 的問題在二值化**：降記號的直桿印得很淡很細，二值化後斷成虛線，調號讀到一兩個降記號就停。補救：`KeyExtractor.hasStem` 把譜線所在列算進直桿（fork `e9eaeef06`），切半頁 2.0x 不銳化時 p02～p06 的調號全對。
- **銳化（unsharp mask）沒有收益，已撤掉**：054 p02～p06 半頁（2.0x），節奏錯的小節（聲部時值和拍號對不上）不銳化 76／440、銳化 98／441；E.G.、Piano、E.Bass 都變差，只有 Drums 變好（30→21）。各頁方向不一（p05b 銳化好、p06a 不銳化 0 對 8），只看一頁會被誤導：之前 p02 一頁判斷「修好 9 個、變差 3 個」就是這樣。
- **半頁放大倍數用 2.0x**：同樣 5 頁不銳化，2.0x 節奏錯 76／440、約 2.5x 94／438，10 個半頁有 8 個 2.0x 較好或持平，每個半頁約 25 秒對 41 秒。放大多不一定好。
- **小節線被旁邊墨跡扣分（054 p10b，已不再發生）**：鋼琴和弦的連結線橫穿小節線，`StaffProjector` 量小節線旁的墨跡（chunk）扣分，那一行沒認出小節線，`purgePartialColumns` 把整欄刪掉，少一個小節。對照灰階：Audiveris 的自適應二值化（0.7·平均＋0.9·標準差）把灰度 160～190 的像素 91% 變黑，弧線和譜線變粗，小節線旁每欄黑像素二值圖約 37、灰階 < 128 只有 15～22。改成 2.0x 不銳化後這頁 4 個小節全對。再出現時，修法是只在這個判斷改用灰階量墨跡（不改全域二值化）。
- **評估方法**：Audiveris 是確定性的（同一張圖跑兩次結果完全相同），兩組差異都是設定造成的；但一個設定會讓很多小節往兩個方向變，所以要多頁比，用「節奏錯的小節數」這種不靠人判斷的指標。
- 看到「某符號斷掉」時，先打開 `.omr` 裡的 `BINARY.png` 確認是二值化就斷，還是後面的步驟弄斷的。

## 11. 單線打擊樂譜表的漏認（2026-10-06，054 半頁）
三個原因各不相同，都改在 fork `f5372092e`：
- **頁面翹曲時單線譜表被當成斜線刪掉**：`LinesRetriever` 在頁面平均斜率算成 0 時，用外框高度估斜率，超過 0.001 就刪。054 頁面上方譜表斜 −0.0008、下方 +0.0012，平均是 0，最下面的 Perc 跟著翹到 0.0023 被刪（p10b、p16b、整頁 p16）。改成看「直不直」：離兩端連線超過 0.4 線距才刪。真的單線譜表偏 0.6～2.8px，被誤當單線的長連結線串偏 16～23px。
- **反覆記號（%）的狀態跨聲部洩漏**：匯出時「反覆進行中」的旗標不分聲部，Drums 最後一小節是 % 時，下一個聲部 Perc 第一小節的 % 就沒寫 start，後面整串空掉（p14a）。改成每個聲部各自保存。
- **文字被當成二分休止符**：「(Handclap)」被認成 87px 寬的二分休止符，小節超長，音符被丟掉（p05a）。全／二分休止符寬超過 2.5 線距就不建立。
- 查法：`.omr` 裡的 `sheet#1.xml`，單線譜表的標籤是 `one-line-staff`（不是 `staff`），數譜表時別漏算。

