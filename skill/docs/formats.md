# 檔案格式（`songs/<編號_羅馬字>/context/` 下的檔案）

## `context/song_metadata.md`

曲目資訊，一首一個，多由 AI 讀譜後寫入（人工補充只是例外）。大部分是自由文字（曲名、藝人、聲部、調號、速度、版面、已核對的事實；外部資料只當 sanity check，譜面才是依據）。**程式只讀下面五行**（鍵名固定用英文小寫，半形冒號；沒寫的項目不會動）：

```
- pdf: 297_water_blue_new_world.pdf       拆分 PDF 的原檔名（prepare_pages.py 用；審查用的合併版 XML 也以此命名）
- time: 4/4                               每個聲部第 1 小節補拍號（已有就不動）
- tempo: 182 ca.                          第 1 小節：印出的速度記號 + 播放速度（ca. 可省）
- tempo_changes: 194=120 195=80           小節=BPM，只影響播放、不印出
- rehearsals: 2=A1 11=B1 19=C1            小節=標記，加方框，排在第一個聲部；先清掉 OCR 產生的排練記號
```
由 `tools/apply_score_hints.py` 套用（後處理自動執行）。

## `context/audiveris_hints.txt`

每行一個 **完整常數名**`=值`（`run_audiveris.py` 逐行原樣轉成 `-constant`；`#` 開頭為註解。**不能寫縮寫鍵名**）：
```ini
# 基本拍號
org.audiveris.omr.sheet.rhythm.PageRhythm.defaultTimeSignature=4/4
# 樂器拓撲提示（從上到下，全名[|縮寫]:譜表數，以分號分隔）
org.audiveris.omr.score.PartCollation.partsHint=A.Piano|A.pf:2; Strings I|Str. I:1; Strings II|Str. II:1; Synth. I|Syn. I:1; Synth. II|Syn. II:1
# 歌詞的字種（有 :lyrics 的譜才寫，見下）
org.audiveris.omr.text.TextBuilder.lyricsScripts=hiragana,latin,punct,hyphen
# 房子開關：僅限「完全沒有」1、2 房子的曲目才加
org.audiveris.omr.sheet.ProcessingSwitches.endings=false
# 歌詞：器樂譜（沒有人聲）加下面這行；有人聲的譜改在 partsHint 的人聲聲部後加 ":lyrics"（見下）
org.audiveris.omr.sheet.ProcessingSwitches.lyrics=false
# 僅在確定小節線因印刷斷口漏偵測時才加（預設 0.6）
org.audiveris.omr.sheet.grid.StaffProjector.gapThreshold=0.8

# 頁眉跑馬字塗白開關（預設 true，p02+ 自動動態偵測白縫塗白；不傳給 Audiveris -constant）
# header_mask=false
# header_mask_start_page=2
# header_mask_max_ratio=0.08
# header_mask_fixed_ratio=0.03

# 每頁從兩個系統之間切成上下半頁，各自放大 2x 再識別（預設關；不傳給 Audiveris -constant）
# split_pages=true
```
範例：`songs/054_natsuiro_egao_de_1_2_jump/context/audiveris_hints.txt`。OCR 引擎是 PaddleOCR（Audiveris 預設），服務要先自己啟動，`run_audiveris.py` 只檢查、沒開就報錯；不用寫進提示檔。

### `header_mask`（頁眉跑馬字塗白開關與參數）
`run_audiveris.py` 在複製暫存檔至 `WORK_DIR` 時，預設針對第 2 頁及之後（`p02+`）的上方天頭進行天頭字區（A 區）與音樂區之間的白縫動態偵測，並將天頭字（如曲名、跑馬頁號）塗白，避免送進 PaddleOCR 誤辨為 `<credit-words>` 雜訊或標題，同時 100% 保持頁面幾何座標並完整保留和弦與排練記號。
- `header_mask=true|false`：開關（預設 `true`；CLI 可用 `--no-mask-header`）。
- `header_mask_start_page=2`：起始遮蔽頁碼（預設 2，第 1 頁完整保留不塗白）。
- `header_mask_max_ratio=0.08`：天頭搜尋高度上限（預設佔頁高 8%）。
- `header_mask_fixed_ratio=0.03`：選填。指定固定高度比例直接塗白，略過自動白縫偵測。

### `split_pages`（切半頁）
- **識別研究的基準**（使用者 2026-10-06 決定）：比較與改進 Audiveris 識別時，以半頁的結果為準；開關保留，做不到切頁的譜（橫排）與回退時關掉。
- `split_pages=true`：`prepare_pages.py` 把每頁從中段（高度 30%～70%）最寬的空白帶切開，存成 `<id>_pNNa.png` / `<id>_pNNb.png`，各自放大 2x（約 13MP；054 p02～p06 節奏錯的小節 2.0x 為 76、約 2.5x 為 94，而且快約 40%），不銳化（unsharp mask 在 054 p02～p06 讓節奏錯的小節由 76 增到 98，見 docs/lessons.md）。整頁只能放大約 1.75x：054 p02 實測 Synth. I／II、Piano、Drums 多處整頁認錯的小節變成完全正確。
- 系統內每一列都有系統開頭的直線，所以切線只會落在系統之間。找不到空白帶的頁（只有一個系統、橫排的譜）維持整頁。
- 半頁在後續流程裡就是一頁：合併後總譜每半頁換一頁，全曲小節號不變；半頁開頭的 % 記號由 `fill_measure_repeats.py` 補。`run_audiveris.py` 只在上半頁遮頁眉，並對半頁加 `ScaleBuilder.minDerivativeRatio=0.008`（放大後預設值找不到 TAB 譜表的第二種線距，TAB 譜表會整行漏掉）。
- 開關切換後重跑 `prepare_pages.py`：另一種做法產生的頁圖、`crop_meta`、`raw/`、`pages/` 會被刪掉重做；切不開的整頁保留原圖與結果。
- 以頁碼寫死位置的 `context/hook.py`（例如 054 的 `pages/054_p02.musicxml`）切換後要改寫。

### `lyricsScripts`（歌詞的字種）
- 有 `:lyrics` 聲部的譜都要寫。值是歌詞用到的字種，逗號分隔、可組合：`hiragana`、`katakana`（兩者都含長音 `ー`）、`kanji`、`latin`（英文字母和 `'`）、`digits`、`punct`（`!?,.()~"`、`！？、。（）「」『』～・…‥`）、`hyphen`（英文歌詞的音節連字號 `-`）。
- 標記 `:lyrics` 的譜表下方改由日文模型讀，只輸出這些字（像白名單）：模型認為是其他字時，改成這些字中分數最高的。所以**只寫譜上真的出現的字種**，多寫會增加誤認（`か`／`カ`、`へ`／`ヘ`，長音被讀成漢字 `一`）。
- 看一兩段歌詞決定，例如全是平假名寫 `hiragana`；夾英文寫 `hiragana,latin,hyphen`。
- 沒寫時歌詞照整頁 OCR（英文模型），日文歌詞會變成雜訊。

### `partsHint` 撰寫心法
- **語法**：`名稱[|縮寫]:譜表數[:lyrics][:drums][:oneline][:tab|:tab4][:gmN][:capoN|:downN]`，以 `;` 分隔，由上到下，寫的是**完整系統**（所有樂器都在的那一行）。
- **譜表數**：這個樂器在完整系統裡印了幾行譜表（五線譜、TAB、一線譜都是一行）。例：五線譜加 TAB 的吉他寫 `:2:tab`，Grand staff 寫 `:2`，單行寫 `:1`。
- **樂器怎麼對上譜表**：每個系統裡找到的譜表，依數量與上下位置排出它是完整系統的第幾行；沒找到的行補在最大的空位（特別大的間距，或系統開頭的直線延伸到第一行之上、最後一行之下的地方）。每個聲部對到 partsHint 中涵蓋它那幾行的樂器。
  - 所以**順序與每個樂器的譜表數是硬條件**，必須和原譜完全一致；名稱不決定對應。
  - 找到的譜表比 partsHint 還多時排不出位置，會寫 WARN `staves not ranked`，該系統改用譜表數加名稱比對（容忍羅馬數字 `I/II` 被讀成 `1/2/l/|`），鼓譜表的叉頭也不會找。
  - 全名與縮寫都寫（`Strings I|Str. I`），聲部名稱用它們。
- **`:lyrics`**：人聲聲部加上它，例如 `Vocal|Vo.:1:lyrics; Chorus|Cho.:1:lyrics; ...`。只要有任一聲部加了標記，**只有這些聲部下方的文字能判成歌詞**，其他位置的譜面文字（pizz.、音色標示…）一律判成 `<words>`。
  - 沒有任何標記時，哪裡都可以判成歌詞。
  - 某一行的譜表數對不上 partsHint 時，該行不判歌詞（人聲歌詞頂多漏一行）。
- **`:drums`**：鼓聲部加上它，例如 `...; E.Bass|E.B.:2:tab4; Drums|Dr.:1:drums`。
  - 識別：這行譜表的符頭照鼓組（`app/res/drum-set.xml`）找，包括 hi-hat／crash 的叉頭。有設 `templateDir` 時，叉頭用該書的模板找（見 SKILL.md Step 1）。
  - 匯出：**不管譜面印的是什麼譜號**（樂團譜的鼓常印低音譜號）都當鼓組，打擊樂譜號、`<unpitched>` 音符、GM 鼓音色。`<midi-unpitched>` 已是正確編號，後處理不要再加 1。
  - 一定要寫名稱，沒寫名稱整個 partsHint 失效。
  - 現況與限制見 `known-gaps.md` 第 4 節。
- **`:oneline`（一線譜，打擊樂）**：印在一線譜上的聲部要加，例如 `Percussion|Perc.:1:drums:oneline`。partsHint 裡有聲部標 `:oneline` 時才找一線譜（系統裡一條單獨的長橫線，附近沒有其他譜線、離譜表不遠）；沒有標記就完全不找。原本只要有 partsHint 就找，五線譜的譜線沒聚成譜表時會被當成一線譜（297 p10、216 p09）。線上的叉頭要用 `:drums` 才會找。
- **`:capoN`（夾 capo 的吉他）**：譜上寫的音比實際音高低 N 個半音（1–11），例如 216 的 `A.Guitar|A.G.:1:capo1`（寫 G 調，實際 A♭）。Audiveris 保留這個聲部自己寫的調號（不會被其他聲部的調號蓋掉），後處理的 `tools/apply_capo.py` 依同一個標記寫 `<transpose>`。一定要寫名稱。
- **`:downN`（降音調弦的吉他、貝斯）**：譜上寫的音比實際音高高 N 個半音（1–11），例如 140 的 `E.Bass|E.B.:2:tab4:gm34:down1`（歌寫 A♭ 的 4 降，吉他、貝斯寫 A 的 3 升；歌轉到 A 時吉他寫 B♭）。判斷方法：p01 歌和吉他、貝斯的調號不同，和弦名也差半音（歌 D♭、吉他 D）。處理和 `:capo` 相同、方向相反。一定要寫名稱。
- **`:tab`／`:tab4`**：這個樂器的最後一行是 6 線（4 線）TAB，譜表數至少 2。TAB 沒被認出來時，匯出仍有這一行。
- **`:gmN`**：這個樂器開頭的音色，N 是 General MIDI 音色編號（1–128），寫進匯出的 `midi-program`。例如 `E.Guitar I|E.G. I:2:tab:gm30`。
  - 每個非鼓聲部都要寫。照譜上第一個音色標示（例如 `(Strings)`、`(Distortion)`、`5st. Bass`）選；沒有標示時照樂器名稱選。曲中的音色變更另外用 `instrument_changes.txt`。
  - 沒寫時照譜表數用預設音色（1 行 54 Voice Oohs，其他 1 Acoustic Grand Piano），電吉他會變成鋼琴。
  - `:drums` 的聲部一律用 GM 鼓組，不用寫。
  - 常用編號：1 Acoustic Grand Piano、5 Electric Piano 1、10 Glockenspiel、17 Drawbar Organ、26 Acoustic Guitar (steel)、28 Electric Guitar (clean)、30 Overdriven Guitar、31 Distortion Guitar、34 Electric Bass (finger)、35 Electric Bass (pick)、39 Synth Bass 1、49 String Ensemble 1、53 Choir Aahs、54 Voice Oohs、62 Brass Section、63 Synth Brass 1、81 Lead 1 (square)、82 Lead 2 (sawtooth)、89 Pad 1 (new age)、90 Pad 2 (warm)。
- 打錯的標記會讓整個 partsHint 失效並寫 WARN，不會悄悄忽略。
- 改了 partsHint 要重跑 OMR，不能只重新匯出舊的 `.omr`。

---

## `context/instrument_changes.txt`
由 `tools/apply_instrument_changes.py` 讀取並套用：
```bash
python tools/apply_instrument_changes.py <score.musicxml> <context/instrument_changes.txt>
```
- **內建泛用 GM 1–128 音色庫**：常見樂器（Piano, Strings, Brass, Flute, Oboe, Horn, Synth Lead/Pad, Orchestra Hit, Bell, Harpsichord, Pizz 等）已內建標準 Program 對照，提示檔中 `[timbres]` 區塊可省略不寫，亦可自訂覆蓋。
- **提示檔語法（tab 分隔）**：支援傳統「頁/行/小節」三段式（完整範例見 297），亦支援直接小節號 `小節 聲部 標示文字 音色 八度`。
```
[timbres]
Pluck	7	Harpsichord（若需覆蓋內建 GM 程式號時自訂）
Bell	9	Celesta
Pizz	46	Pizzicato Strings
Arco	49	String Ensemble 1

[defaults]
Str. I	Arco

[changes]
1	1	2	Syn. II	Pluck I	Pluck	0
2	3	1	Syn. II	Add Sequenced Arpeggio	-	0
2	3	3	Syn. I	Bell I (8va)	Bell	1
5	2	1	Str. I	pizz.	Pizz	0
5	3	4	Str. I	-	Arco	0
```
- `[timbres]`：音色名、GM program（1–128）、說明（可省略，直接套用內建庫）。`[defaults]`：聲部縮寫或名稱、曲首音色。
- `[changes]`：頁、行、該行第幾個**印出的**小節（或直接小節號）、聲部縮寫/名稱、標示文字、音色、八度。標示文字 `-` = 原譜沒印字；音色 `-` = 只放文字、不換音色；八度 1 = (8va)、2 = (15ma)（該段音高升八度並加 8va/15ma 線）。
- **資料行不能加行內註解**（解析器按 tab 切欄）；註解只能整行以 `#` 開頭。

做法（已定，不用再試）：每種音色一個 instrument，**每個音符（含休止符）**帶 `<instrument id>`；八度用 `<octave-shift>`，不用樂器移調（MuseScore 只在換樂器時才套 transpose）；標示區段內 Audiveris 自己產生的 octave-shift 是把標示括號誤判成 8va 線，先移除並還原音高。

## `context/ottava.txt`
由 `tools/apply_ottava.py` 讀取。**tab 分隔**：`聲部縮寫 譜表 種類 起始小節 起始位置 結束小節 結束位置`
```
A.pf	1	8va	27	2	29	end
A.pf	1	8va	37	#2	38	1
A.pf	2	8va	84	#2	84	end
A.pf	1	coll8va	91	1	93	3.5
A.pf	1	15ma	247	1	247	end
```
- 譜表 1 = 高音譜、2 = 低音譜。Audiveris 時間錯位的小節（如上例 m37、m84）用 `#k`（該譜表第 k 個起音），不要用拍數。資料行同樣不能加行內註解。
- 小節 = 全曲小節號；位置 = 拍（1 起算，含該拍起音的音）、`#k` 或 `end`。
- 8va/15ma：該譜表範圍內音高升 1/2 八度＋`<octave-shift type="down">`（direction 帶 `<staff>`；高低音譜同時有線時用不同 `number`）。coll8va：每個音加一個高八度**隱形音**（`print-object="no"`）＋文字，譜面不變、播放有重疊。
- 目標小節沒音會印 `no notes`：多半是 Audiveris 漏音（297：m45 鋼琴整小節、m247 全音符），提示保留，補音後重跑即生效。



---
