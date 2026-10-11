# 已知缺口與待辦

這些問題還沒整合進流程。原則：不盲目堆成永久的 Python 後處理，先判斷能不能在 Audiveris Java 本體源頭解決，還是只能留在後處理。打擊樂、2X 小節的舊專用腳本不在這裡。

## 目前最明確的缺口
- **Audiveris 漏掉的音，流程沒有補音的層**：漏整小節或全音符／二分音符、只剩休止符（297：m45 鋼琴、合成器 7 處）。`<id>_quality.txt` 的 `length_mismatch_measures` 各曲 3～7 個小節，分不出「原譜如此」與「漏音」，要對照譜面。
- **216**：9 個非標準時值小節、4 個未配對的八度線。
- **068**：p06 偵測到 Coda 但未匯出。
- **調號時間線**：`unify_keys.py` 的結果要對照印刷譜面確認（068 m48、297 m78 與 m198 這幾處）。
- **`SentenceInter.java` 的 Direction 連結修正**（audiveris-bandscore repo）還沒編譯過。
- **速度／排練記號仍在專用腳本**：216 的 `TEMPO` 與排練記號在 `context/hook.py`，尚未搬進 `song_metadata.md`。

---

## 1. 2X 小節（Play-Twice / 2nd Time Only 括號記譜）

- **現象與痛點**：
  同一物理小節內塞入兩小節內容：第一遍演奏括號外音符，第二遍演奏括號 `(...)` 內音符，旁註 `2X` 或 `2nd time only`。Audiveris 無法理解括號語義，會將兩遍音符雜糅在同一個 `<measure>` 內部，造成約 100% OVER。嚴禁直接 clip 截斷，否則會抹殺第二遍演奏。
- **現狀可行解（舊 skill 後處理）**：
  舊專用腳本 `split_2x_measures.py`（不在本 repo）的做法是幾何反推定位與拆分：
  1. 幾何反推：以 OCR 抓取容錯正則 `(?i)\(?([12]\s*[xX]|2nd|tacet)\)?`，比對 `.omr` 的 `sheet#1/BINARY.png` 1:1 座標、`<system>` 的 staff y 範圍與 `<stack>` 橫向切片，鎖定小節號。
  2. 音符分割階梯：時間軸游標累加法（$\sum \text{dur} == \text{BAR}$） $\rightarrow$ 幾何 X 突變邊界法（Max Gap） $\rightarrow$ Backup 斷點 $\rightarrow$ 聲部短缺 Padding Guard。
  3. Ending 標記硬規則：Measure A 掛 Ending 1 + backward repeat；Measure B 掛 Ending 2，且右小節線**必須使用 `type="stop"` 閉合（嚴禁 `type="discontinue"`）**，避免無折角括號外溢；DTD 順序為 `bar-style` $\rightarrow$ `ending` $\rightarrow$ `repeat`。
- **Audiveris 本體改修可行性評估**：
  - **評估**：中～高難度。
  - **原因**：2X 記譜在紙面上完全沒有小節線，Audiveris 傳統架構在幾何切片階段（`BarlineBuilder` / `MeasureBuilder`）純粹依據實體小節線劃分 Measure。
  - **改修方向**：若在 Java 端實現，需要在 `PartwiseBuilder` 或 `MeasureBuilder` 整合 OCR 括號文字，動態將單一物理小節虛擬拆分為兩個 XML `<measure>` 並生成 Ending 標記。因邏輯複雜且涉及版面語義，**短期內建議維持 Python 後處理；長期可評估在 PartwiseBuilder 匯出層做虛擬拆分**。

---

## 2. 幽靈休止符聲部（Phantom Rest Voice Flattening）- **[已在 Audiveris 本體修復]**

- **現象與痛點**：
  換頁處、譜表起點或長髮夾線處，Audiveris 常誤判出整小節全休止符搶先寫入 Voice 1（佔滿時值）；隨後識別到真實音符時，因游標衝突被迫插入 `<backup>` 將真實音符丟進 Voice 2（或 Voice 6），導致 MuseScore 畫面中休止符與音符重疊繪製、單聲部旋律被顛倒符桿。
- **Audiveris 本體修復實作**：
  - **狀態**：**已整合至 `audiveris-bandscore` 分支（commit `c8a90a6d2`；`8d8bdf76c` 修正保留 voice 的重新編號，改依 Audiveris 的每譜表 id 家族 1–4 / 5–8 / 9–12，避免 3 譜表聲部撞號）**。可用 `-constant org.audiveris.omr.score.PartwiseBuilder.dropGhostRests=false` 關閉。
  - **審查實證（2026-09-29，297 全 21 頁以新 binary 對既有 `.omr` 重新匯出）**：所有發聲音符的（聲部、小節、譜表、起始時間、音高、時值）逐一相同，各小節長度不變；走完整條後處理後 DTD 0、`verify_musescore.py` 通過，preview 發聲音符 5197/5197 相同、休止符 1020 → 990。
  - **既有、與此改動無關的 WARN**：p05（有 `%` 一小節反覆）匯出時出現 `Error checking octave-shift ... no such vertex in graph`（關閉 dropGhostRests 時同樣出現）；只影響 8va 檢查，音符照常輸出，待查。
  - **修改位置**：`app/src/main/java/org/audiveris/omr/score/PartwiseBuilder.java`。
  - **核心邏輯**：
    - 新增參數 `Constants.dropGhostRests`（預設為 `true`）。
    - 在匯出小節各聲部時（`buildMeasure`），按 `Staff` 分組檢視各 Voice。
    - 透過 `voiceHasPitchedNotes` 區分「純休止符聲部」與「發聲音符聲部」。
    - 若同一 Staff 上同時存在發聲音符聲部與純休止符聲部（且非該譜表之合法全小節休止符），自動在匯出清單中捨棄純休止符聲部，阻斷無效 `<backup>` 產生。
    - 同時透過 `voiceIdMap` 自動將真實音符聲部重編提升（如單行譜 Voice 2 $\rightarrow$ 1，大譜表下行 Voice 6 $\rightarrow$ 5），維持合法 MusicXML 聲部順序。
- **A/B 測試實證結果（以 297 全曲 21 頁為基準）**：
  - **幽靈休止符小節數**：24 $\rightarrow$ 0（100% 徹底清除）。
  - **發聲音符總數（Pitched Notes）**：5140 $\rightarrow$ 5140（差異 0，達成嚴格 **Zero Note Loss**）。
  - **休止符元素總數**：843 $\rightarrow$ 817（精確扣除 26 個虛假休止符節點）。
- **流程結論**：
  新流程使用最新 `audiveris-bandscore` 匯出時已在源頭根除幽靈休止符，後處理無需再維護複雜的聲部提升腳本。

---

## 3. 延音線（Tie）同音約束與通用和弦漏 Tie

- **現象與痛點**：
  圓滑線（slur）被誤認成 tie；換行處產生單向懸空 tie；多音和弦（八度雙音、密集和弦）因符頭重疊只辨識出外側 1 個 tie，內聲部在播放時被重新敲擊發聲。
- **現狀可行解（舊 skill 後處理）**：
  `clean_score_noise.py`：
  1. 重複標記清理。
  2. 嚴格同音約束：Tie 只能連接相同音高（同 step, alter, octave）之相鄰音符；跨音高、懸空 start 或孤立 stop 一律清除。
  3. 通用和弦漏 Tie 補齊：多音和弦間只要至少已有 1 個同音建立合法延音錨點，自動為其餘完全同音高的成員補齊 `<tie>` 與 `<tied>`。
- **Audiveris 本體改修可行性評估（2026-09-29 查原始碼與 297 實測後更正）**：
  - **同音約束 Audiveris 早已內建**：`SlurInter.areTieCompatible` 要求兩端音名、八度、臨時記號一致才判為 tie（`checkStaffTie` / `checkCrossTie`），不需要再加。
  - **297 raw 實測**：619 條 tie start 都有正確的同音 stop，異常只有約 19 處（17 個 stop 前一個起音不同音、2 個 start 後面沒有音）。Audiveris 端的 tie 品質已經夠好。
  - `clean_score_noise.prune_invalid_ties` 在 297 刪掉的 32 個 tie start 中，16 個確實無效，**2 個其實有效**：舊版只以「同譜表的下一個起音」判斷、多聲部譜表會誤刪；**已修（`b3ccf77`）**：同 voice 與同譜表兩種看法都判無效才刪。
  - **跨頁 tie**：逐頁各開一個 book，頁尾的延音線不會匯出，只能在合併時補（後處理範疇）。
  - **仍值得進本體的是和弦漏 tie 補齊**（297 補了 188 個 tie/tied）：在匯出或 SIG 階段，若兩個相鄰和弦之間已有一條 tie，把其餘同音的成員也連上。

## 4. 打擊樂譜（Drums / Percussion）與叉頭

- **做得到**（partsHint 鼓聲部加 `:drums`，用法見 `formats.md`）：
  - 鼓譜表不管印什麼譜號都當鼓組匯出；kick、snare 的實心符頭與 hi-hat／crash 的叉頭照 `drum-set.xml` 的位置對上鼓音色。
  - 叉頭用書的模板找（`templateDir`，見 SKILL.md Step 1）。
  - 一線譜（Perc.）找得到；它的叉頭也照 `drum-set.xml` 找，線上和線上方一個行距兩個位置的音色是暫定的，要試聽後再選。
  - 單頁實測：132 p10 鼓 113 個音、其中叉頭 47 個；夏色 p04 鼓 73 個音、叉頭 28 個（p01、p02 叉頭 7、34 個），Perc. 一線譜的 8 個叉頭全部找到，符槓連上，每小節 4 拍。
- **還做不到**：
  1. 圓圈叉 ⊗、hi-hat 上的 o／+、小節反覆記號：沒有模板（清單見 `symbol_templates.md`）。
  2. 壓在加線上的叉頭（132 m6 的 crash、夏色 p04 加線上的 crash）：`lovelive_sunshine_best` 沒有 `cross_line`，兩本都還沒有加線上的例子。
  3. 偵測到但連不上符桿的符頭不會匯出：集中在密集小節（十六分音符 snare 連打）；夏色 p04 鼓譜表有 1 個單獨站在符桿上的 hi-hat 連符桿都沒建出來（x≈2412），原因未查。符桿穿過 X 被判成「符頭在符桿中段」而刪掉的問題已修（Audiveris `8265b32`），兩首還沒用它重跑。

---

## 5. 複合排版（D.S. / Coda 雙欄並排）分段守恆

- **現象與痛點**：
  同一行內左欄為 D.S. 前小節（2 節）、右欄為 Coda 小節（2 節），在紙面上屬於同一物理行（System）。Audiveris 在轉譯時容易在 Coda 起點誤插 `new-system="yes"`，導致一行被拆成兩個殘缺短行。
- **現狀可行解（舊 skill 後處理）**：
  在後處理中清除 Coda 起點的偽 `new-system`，保持包含 4 小節的完整行。
- **Audiveris 本體改修可行性評估**：
  - **評估**：低難度，適合在 Audiveris 本體修復。
  - **改修方向**：在 Audiveris 的 `SystemBuilder.java` 或 `PartwiseBuilder.java` 中，檢查水平連續 staff 的幾何重疊度；水平投影高度一致且相鄰的 stack 屬於同一 System，不應觸發斷行。

---
