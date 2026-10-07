# Audiveris-Bandscore 用法

[README](README.md) 第 2 節列出本分支的改進；這份文件說明需要設定的項目怎麼設定、各項的規則細節。設定多為 Audiveris CLI 的 `-constant <完整常數名>=<值>`；完整的執行例子見 README 第 3 節。

---

## partsHint

聲部提示：由上到下給出完整系統的全部聲部。

```
-constant "org.audiveris.omr.score.PartCollation.partsHint=A.Piano|A.pf:2; Strings I|Str. I:1; ..."
```

格式：`名稱[|縮寫]:譜表數[:lyrics][:drums][:oneline][:tab|:tab4][:gmN][:capoN|:downN]`，聲部之間用 `;` 分隔。

- 寫完整系統（所有聲部都在的那一行），順序與譜表數必須與原譜完全一致。譜表數是這個聲部印了幾行譜表：五線譜、TAB、一線譜都是一行（大譜表寫 `:2`，五線譜加 TAB 寫 `:2:tab`，單行寫 `:1`）。
- 用 `|` 列出全名與縮寫，讓首頁與後續頁都能對上。
- 每行系統的譜表依數量與上下位置排出是完整系統的第幾行，再對到提示中涵蓋那幾行的聲部；排不出位置時改用譜表數加 OCR 名稱比對（容忍 `I/l/|/1` 等誤讀）。缺席聲部匯出為空聲部，對不上的不丟內容。
- 標記打錯會讓整個提示失效並寫 WARN，不會悄悄忽略。

### :lyrics

只有標記的（人聲）聲部下方的文字可判成歌詞；其他譜面文字（`pizz.`、`Woodwind`、`Bell (15ma)`）一律成為 words。例 `Vocal|Vo.:1:lyrics`。

每行譜表照 HEADS 步驟排出的提示行號判斷（漏掉的譜表放回空位）；排不出行號的系統不判歌詞。器樂譜（沒有人聲）可以直接關掉歌詞：`org.audiveris.omr.sheet.ProcessingSwitches.lyrics=false`。

### :drums

把聲部當成鼓組。例 `Drums|Dr.:1:drums`，需要寫聲部名稱。

- 被標記的譜表照鼓組（`app/res/drum-set.xml`）找符頭，hi-hat／crash 的叉頭也找。
- 匯出時一律當鼓組，不管譜面印的是什麼譜號：輸出打擊樂譜號、`<unpitched>` 音符與 GM 鼓音色，每個鼓聲部的音符用自己聲部的音色定義（一頁可以有多個鼓聲部）。
- 鼓譜表上方（到上一行譜表為止）只由 `+ o O 0 i ( ) ○ ◦ °` 組成的 OCR 文字是 hi-hat 開合記號，直接丟掉（記號本身還沒有辨識）。
- 叉頭用本書的模板找時，見 [templateDir](#templatedir)。

### :oneline

找一線譜（打擊樂）。例 `Percussion|Perc.:1:drums:oneline`（`oneLineStaves` 開關關閉時）。

- `partsHint` 裡有聲部標 `:oneline` 時才找：系統裡一條單獨的長橫線（附近沒有其他譜線、離譜表不遠）認成一線譜表，在 `partsHint` 裡算一行。沒有標記時完全不找。
- 找到的長線要夠直才算：離兩端連線超過 0.4 個行距就丟掉（被當成長線的整串連結線彎 1 個行距左右）。不看斜率，頁面輕微翹曲時一線譜會跟著斜。
- 加 `:drums` 時，線上的叉頭照 `drum-set.xml` 一線譜的兩個位置（線上、線上方一個行距）找，音色是暫定的。

### :tab

`:tab`（6 線）或 `:tab4`（4 線）：這個聲部的最後一行是 TAB。例 `E.Guitar|E.G.:2:tab`。TAB 沒被認出來、或被拆成獨立聲部時，仍匯出成同一個聲部，譜表數照提示（含 TAB 這一行）。

### :gm

`:gm` 加 General MIDI 音色編號（1–128），例 `E.Guitar|E.G.:2:tab:gm30`。匯出時這個聲部的 `midi-program` 和 `instrument-name` 用這個音色（開頭的音色）。

- 沒寫時照譜表數用預設音色：1 行譜表 54 Voice Oohs，其他 1 Acoustic Grand Piano。
- `:drums` 的聲部一律用 GM 鼓組，不看這個標記。
- 編號超出 1–128 時整個提示失效並寫 WARN。

### :capo

`:capo` 加夾的格數（1–11），例 `A.Guitar|A.G.:1:capo1`，需要寫聲部名稱。

夾 capo 的吉他寫的音比實際音高低 N 個半音（capo 1：寫 G 調、實際是 A♭）。這個聲部在[每小節統一調號](#每小節統一調號)裡當移調樂器：投票時換回實際音高，匯出時用自己寫的調號。`<transpose>` 不由 Audiveris 寫，由後處理依同一個標記補上。

### :down

`:down` 加調低的半音數（1–11），例 `E.Bass|E.B.:2:tab4:down1`，需要寫聲部名稱。

降 N 個半音調弦的吉他、貝斯寫的音比實際音高 N 個半音（down 1：寫 A 調、實際是 A♭；同一個字母，所以是增一度）。調號的處理和 [`:capo`](#capo) 一樣，只是方向相反。

---

## templateDir

本書的模板資料夾。同一本樂譜集字型相同，模板做一次整本共用。

```
-constant org.audiveris.omr.sheet.note.NoteHeadsBuilder.templateDir=<資料夾>
```

資料夾裡可以放：

| 檔案 | 用途 |
|---|---|
| `cross.png` | `:drums` 譜表上的叉頭 |
| `cross_line.png` | 被譜線或加線從中間穿過的叉頭 |
| `cross_ledger.png` | 踩在粗短加線上的叉頭 |
| `slash.png` | 吉他譜的斜線（所有非鼓的五線譜上都找） |
| `drum-set.xml` | 本書的鼓譜對應 |
| `chord_<根音>b.png` | 和弦名的 ♭，見 [openingFifths](#openingfifths) |
| `key_sharp.png`、`key_flat.png` | 調號的 ♯、♭（單一個，長方形），兩個都有時用來重讀每行開頭的調號 |

**模板的做法**：剛好包住一個符號的正方形（墨色深，行距 20 像素的比例），由人在譜面上挑幾個例子平均而成，方塊裡每個像素都參與比對。同一個符號在譜線上、加線上樣子不同，所以分開做；每個位置取吻合度最高的。

**比對**：模板和比對都用灰度（3×3 中值後的深淺，不二值化），比對用正規化相關係數，所以印刷深淺不影響；比對前把長橫線（譜線、加線）上下都白的部分擦掉，規則和學模板時相同。log 會印出每行譜表最好的相關係數與位置。

**找到的符頭**：外框是符頭中心部分（符桿接點照舊），glyph 是整個符號的墨跡；找其他符號前照這個 glyph 擦掉。附點只連到在符頭整個墨跡右邊的那一個符頭。判斷符頭連在符桿哪一端時，符桿末端落在整個符號的範圍內就算（書上的符桿常穿過 X 到它底部）。

**斜線**：當成符頭 `NOTEHEAD_SLASH`，符桿、符槓、附點、連結線照一般音符算節奏，匯出為 `<notehead>slash</notehead>`，音高先放第三線。符桿朝上的斜線在第 4 線附近、朝下的在第 2 線附近，兩種都找。

**drum-set.xml**：格式同 `app/res/drum-set.xml`。載入共用表之後再載入它，同一個（位置、符頭、記號）以它為準。用在本書寫法和一般鼓譜不同的地方，例如 hi-hat 寫在最上線（一般是 Ride）。

**調號**：有 `key_sharp.png` 和 `key_flat.png` 時，每行有音高的五線譜（鼓、TAB、一線譜除外）在譜號選定後重讀一次調號。調號的每個記號位置是固定的：第一個緊接譜號，高度照譜號（高音譜號 ♯ 依 F C G D A E B、♭ 依 B E A D G C F），之後每個往右約一個行距。從第一個位置開始一個一個比對模板（只在預期位置上下左右小範圍找），數到第一個比對不過的位置為止；♯ 和 ♭ 都數，取數到比較多的那種。和原本讀到的不同就換掉，log 寫 `key N read with the templates, not M`，附每個位置的相關係數。原本是把記號一塊塊切出來再數，被譜線切斷的 ♭ 會少算、緊貼在後面的臨時記號或音符會多算；在固定位置比對模板就沒有這兩個問題。門檻 `org.audiveris.omr.sheet.key.KeyTemplates.minGrade`（0.5）；第一個記號要 `minFirstGrade`（0.75），因為低音譜號的兩個點剛好在第一個 ♯ 的位置，比對約 0.6，真的記號在 0.8 以上。

**錯誤時**：資料夾不存在時直接報錯停止（路徑錯會整本沒用模板，不可默默跑下去）。輸入圖檔要還在；讀不到時寫 WARN、不用模板。

---

## lyricsScripts

歌詞用歌詞模型重讀，值是歌詞用到的字種。

```
-constant org.audiveris.omr.text.TextBuilder.lyricsScripts=hiragana,katakana,punct
```

需要 `:lyrics` 標記與 PaddleOCR 引擎，沒有時報錯停止。空白（預設）時歌詞照整頁 OCR。

字種逗號分隔、可組合：`hiragana`、`katakana`（兩者都含長音 `ー`）、`kanji`、`latin`（含 `'`）、`digits`、`punct`（`!?,.()~"`、`！？、。（）「」『』～・…‥`）、`hyphen`（`-`）。只輸出這些字：模型認為是其他字時，改成這些字中分數最高的。

讀法：標記 `:lyrics` 的譜表下方（到下一行譜表）不做文字偵測（會漏掉單獨的短音節和橫線）；先擦掉連結線和延長線（扁平、貼在行底部的線段），依空白切成行、依字間空隙切成音節；音節並排成一行一起辨識，每個字依解碼位置分回音節。扁平的音節是橫線：前一個音節是英文時為 `-`，否則為 `ー`。有大小寫的假名照字高判斷（比整行中位數低 0.76 以下為小寫，高 0.9 以上為大寫，中間照模型）。

---

## openingFifths

開頭是降號調的歌，用書的模板補回 OCR 讀丟的和弦 ♭。

```
-constant org.audiveris.omr.text.ChordFlats.openingFifths=-4
```

模板資料夾（[templateDir](#templatedir)）要有 `chord_<根音>b.png`（例 `chord_Eb.png`）。OCR 讀到的根音字母（字首或 `/` 後）有對應模板時，在灰階圖上用整個「根音＋♭」模板對齊字母位置，只用 ♭ 那一塊算相關係數；達 `minFlatGrade`（0.55）就把 ♭ 位置上 OCR 讀到的字換成 ♭，沒達到照 OCR 原樣。在判斷文字角色之前做，`E$` 補成 `E♭` 後才會被當成和弦名。

---

## defaultTimeSignature

頁面開頭沒有拍號、前面頁面也找不到時使用的拍號。

```
-constant org.audiveris.omr.sheet.rhythm.PageRhythm.defaultTimeSignature=4/4
```

---

## dropParenthesized

樂團譜常把只在第二遍（`2x`）或 D.S. 之後（`D.S.x`）才演奏的音符，用和譜表一樣高的括號寫在同一小節原本的音符後面，一起讀進來小節就會超長。打開後，節奏算完、某個聲部長度不對的小節，依序檢查：

1. 該聲部的譜表上（TAB 除外）有沒有一對高括號（文字自己的括號，如 `(Synth.)`，不算）；
2. 括號上方附近有沒有 OCR 讀到的 `2x`～`9x`、`D.S.x`、`D.C.x`（`1x` 是第一遍，不算）；
3. 刪掉括號裡的和弦（連同符桿、符槓、符尾、附點、臨時記號、演奏記號；跨過括號的連音視為誤認一併移除）後，所在的每個聲部是否剛好等於拍號長度，或整個變空。

三項都成立才刪，否則照原樣保留（log 會寫明）。預設 `false`。

```
-constant org.audiveris.omr.sheet.rhythm.ParenthesizedChords.dropParenthesized=true
```

只做第一遍的音符；第二遍的內容目前不匯出。圖例（`( ) = D.S.x`）沒有被 OCR 讀到的譜表不會處理。

---

## endings

已知全曲沒有 1、2 房子時關閉房子偵測。預設 `true`（照常偵測）。

```
-constant org.audiveris.omr.sheet.ProcessingSwitches.endings=false
```

---

## 其他開關

| 常數 | 預設 | 說明 |
|---|---|---|
| `org.audiveris.omr.score.PartwiseBuilder.maxFontSize` | 24 | 標題、和弦名等文字的字級上限（pt），超過的不寫字級 |
| `org.audiveris.omr.score.PartwiseBuilder.dropGhostRests` | true | 丟掉有實音的譜表上只有休止符的多餘 voice |
| `org.audiveris.omr.text.OcrUtil.ocrEngine` | paddle | 改成 `tesseract` 時用上游的 Tesseract |
| `org.audiveris.omr.text.paddle.PaddleOCR.serverUrl` | `http://127.0.0.1:8868` | PaddleOCR 服務的位址 |

---

## PaddleOCR 服務

預設的 OCR 引擎，服務程式在 [`dev/paddleocr/paddle_ocr_server.py`](dev/paddleocr/paddle_ocr_server.py)，啟動方式見 README 第 3 節。

- 使用 PP-OCRv5，回傳行／字／字元框，字元框貼齊實際墨跡。
- 服務連不上時直接報錯，不會退回 Tesseract。
- 啟動時加 `--device gpu:N` 用 GPU（需要 paddlepaddle-gpu）：以完整 fp32 執行（關閉 TF32、cuDNN 固定演算法），文字、字框、分數都和 CPU 相同。
- CPU 上的文字辨識模型保留 oneDNN 加速；文字偵測模型關閉 mkldnn，避開 PaddlePaddle 3.x 的 oneDNN 崩潰。

---

## 預設生效的規則

以下不需要設定，列出判斷規則供查錯。

### 每小節統一調號

同一小節所有有音高的譜表（鼓、TAB、一線譜除外）只有一個實際音高的調號：

- 每行譜表投它認出的調號，移調樂器先換回實際音高；系統開頭沒認出調號的譜表不投票，系統中間沒認出的投「沿用」。
- 多數決；平手時取目前的調號，否則取最上面的譜表；沒有任何票時沿用（還沒有調號時為 C）。被否決的譜表寫 WARN。
- 行中「沿用」勝出、但有譜表讀到的調號正好是下一行開頭多數譜表讀到的調號時，從這個小節起就用新調號；一行最後一個小節右半邊的調號是預告下一行的，不算。每頁的最後一行照舊多數決。
- 匯出時每個聲部用這個調號寫 `<key>` 並換算音高。
- 移調樂器照聲部名稱判斷：名稱裡有 `in X` 時照它；否則 B♭（Trumpet、Cornet、Flugelhorn、Clarinet、Soprano／Tenor Sax，及 Tp.、Cl.、T.Sax 等縮寫）、E♭（Alto／Baritone Sax，A.Sax、B.Sax）、F（Horn、English Horn，Hr.、E.H.）；只差八度的（吉他、貝斯）調號相同。

### 調號的降記號

判斷 ♭ 有沒有直桿時，譜線所在的列也算直桿的一部分（看二值圖上那一列在 ♭ 範圍內有沒有墨跡）。印得很淡很細的直桿二值化後斷成虛線，斷的地方常在譜線上。

### 不合小節長度的連音

拍號已知、不是弱起小節時：某個聲部長度不對、裡面又有連音記號時，先全部拿掉，再從左到右一個個加回，加到聲部會比小節短之前就停；沒加回的連音記號刪掉、小節節奏重算。

### 整小節休止符

拍號已知時，整小節休止符一律等於應有時值（弱起等隱含小節除外）。某行譜表在這個小節一個聲部都沒有時，匯出一個整小節休止符；有 `%` 的譜表不補。

### 多餘的休止符聲部

有實音的譜表上，丟掉只有休止符的多餘 voice，並把剩下的 voice 依 Audiveris 的譜表 id 家族（1–4／5–8／9–12）重新編號。

### % 小節反覆

只出現在部分譜表的 `%` 只複製這些譜表的 voice，並先倒回小節起點。`<measure-repeat type="start">` 寫入重複的小節數（等於 % 的斜線數）；MuseScore 3.6 讀入時不處理 `measure-repeat`，照抄過來的音符顯示、播放。「% 序列進行中」的狀態每個聲部各自保存。

### 文字的歸屬

- 譜表區裡的文字一律當 direction 掛到小節；只有第一個 system 上方離譜表遠的文字、最後一個 system 下方離譜表遠的文字才是 credit。
- direction 掛到上下最靠近的譜表，在那行譜表裡找水平範圍內最近的和弦；沒有時放寬水平範圍、再找整格最近的和弦。
- 和弦名正下方沒有音符時，掛到下方譜表最近的和弦，匯出時用 `<offset>` 移到和弦名水平位置上、任一聲部的音符的拍點。
- TAB 譜線範圍內讀到的字（品格數字）、沒有任何字母或數字的行丟掉。
- 譜表上的指示文字不寫 `font-size`；其他文字照 OCR 文字框寫字級，超過 [maxFontSize](#其他開關) 的不寫。

### 方框排練記號

TEXTS 步驟在整頁 OCR 之前先找方框：system 第一行譜表上方、四邊幾乎全是墨跡、內部幾乎空白的空心矩形。方框連同框內文字從 OCR 圖上擦掉，框內文字單獨 OCR 成排練記號；OCR 信心低也不刪。用方框右緣決定小節。

### 和弦名

- OCR 把 ♭ 讀成 `'`（`D'M7`）時當成 ♭。
- 中間有空隙的和弦（`E sus4`）在判定文字角色前合併，只在根音合法、合併後也合法且間距小於字高時才合併。
- `add2 / add4 / add9 / add11 / add13` 以 `degree-type add` 匯出；六和弦只加 9 音時不輸出括號度數。

### 滑音

`gliss.` 匯出成 `<glissando>`、吉他譜的 `S` 匯出成 `<slide>`。連的是同一聲部裡、左緣夾住記號中心的兩個相鄰音（grace 音排在它的主音前面）；其中一個是休止符、或記號在聲部最後一個音上方時，留成文字。推弦（`cho`）、悶音（`M`）留成文字：MuseScore 3.6 不讀 `<bend>`、`<other-technical>`。

### 符號

- 休止符候選和一個只由空心符頭組成的和弦黏在一起、而且每個符頭的可信度都比休止符低時，刪掉這個和弦、保留休止符。
- 寬度超過 2.5 個行距的全休止符、二分休止符不建立（實際約 1.4 個行距）。
- SYMBOLS 步驟前把歌詞行的範圍（上下各多 4 像素）塗白，演奏記號的候選點落在歌詞行內時放棄。
- 演奏記號找所屬和弦時，上下距離不超過 1.8 個行距（第二種輪廓 2.2），也不超出譜表範圍。
- 房子只在系統第一行譜表上方找。
