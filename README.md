# Audiveris-Bandscore

針對**樂團譜／鍵盤譜（bandscore）**改修的 [Audiveris](https://github.com/Audiveris/audiveris) 分支。
目標是讓 OMR 直接輸出**可以在 MuseScore 正確播放的 MusicXML**，把原本要靠大量逐曲後處理腳本修補的問題，移到 Audiveris 核心裡一次解決。

- 基底：上游 Audiveris **5.11.0**（`7a36078`），之上共 22 個 commit
- 分支：`bandscore`（預設分支）
- 授權：與上游相同，[AGPL-3.0](LICENSE)

---

## 1. 背景

Audiveris 是成熟的開源 OMR 引擎，對古典譜（IMSLP 類）效果很好，但拿來處理日式樂團譜、鍵盤譜時，會反覆遇到同一批問題：

- **聲部拓撲不穩**：多聲部總譜每行出現的樂器不同（休止的聲部被省略）、樂器名被 OCR 讀錯（`Str. I` → `Str. l`），導致各頁的 part 對不上，合併後聲部錯位。
- **逐頁 OMR 沒有拍號**：每頁各自開 book 跑時，第 2 頁起找不到拍號，時值不檢查。
- **一個聲部讀錯，整格污染**：某聲部多讀或漏讀一個音，整小節休止符跟著變長／變短，所有聲部一起 OVER／UNDER。
- **文字辨識弱**：Tesseract 對和弦名（`Bbadd9`、`E sus4`）、排練記號、器樂譜面文字的辨識率低；`pizz.`、`Woodwind` 等譜面文字被當成歌詞。
- **誤判結構**：演奏法延續線（`— pizz. —↓`）被當成 1、2 房子；`%` 小節反覆展開成 8 拍小節；鬼休止符 voice 讓播放游標錯亂。
- **偶發崩潰**：特定頁面在 OMR 或匯出時拋出 NPE／陣列越界，整頁失敗。

過去這些都在 OMR 之後用 Python 腳本逐曲修補（每首曲子一支 `normalize_*.py`、`fix_*.py`），維護成本高、容易互相打架。
本分支的做法是：**能在源頭修的就在源頭修**，後處理只留輕量、確定性的步驟。

輸入提示類的功能都是 **opt-in** 的 `-constant` 開關，不設定就與上游行為相同；文字辨識、匯出修正與穩定性修補則預設生效（見下表「啟用方式」欄）。

---

## 2. 改進點總覽

**啟用方式**欄：`預設生效` 表示不需設定；其餘為 Audiveris CLI 的 `-constant <完整常數名>=<值>`。

### 2.1 輸入提示（使用者告訴 Audiveris 已知的事）

| Patch | 啟用方式 | 能力／效果 |
|---|---|---|
| **partsHint：聲部拓撲提示**<br>`6a28ce4` | `org.audiveris.omr.score.PartCollation.partsHint=`<br>`A.Piano\|A.pf:2; Strings I\|Str. I:1; ...` | 由上到下給出全曲聲部（`名稱[\|縮寫]:譜表數`）。每行系統以動態規劃對齊到這組邏輯聲部：譜表數與上下順序為硬條件，OCR 名稱只作軟性成本（容忍 `I/l/\|/1` 等誤讀）。缺席聲部匯出為空聲部，對不上的不丟內容。**取代每首曲子手寫的 normalize 腳本。** |
| **partsHint `:lyrics` 標記**<br>`8192fd8` | 在人聲聲部後加 `:lyrics`，<br>例 `Vocal\|Vo.:1:lyrics` | 只有被標記聲部下方的文字可判成歌詞；其他譜面文字（`pizz.`、`Woodwind`、`Bell (15ma)`）一律成為 words。譜表數對不上提示的系統不判歌詞（保守）；標記打錯會讓提示失效並寫 WARN，不會悄悄忽略。 |
| **預設拍號**<br>`06a58f6` | `org.audiveris.omr.sheet.rhythm.PageRhythm.defaultTimeSignature=4/4` | 頁面開頭沒有拍號、前面頁面也找不到時，退回使用者給的拍號。逐頁 OMR 不再整頁失去時值檢查。 |
| **endings 開關（房子偵測）**<br>`eda9db9` | `org.audiveris.omr.sheet.ProcessingSwitches.endings=false` | 已知全曲沒有 1、2 房子時關閉偵測，避免 `— pizz. —↓` 之類的延續線被誤判成 Volta。預設 `true`（行為不變）。 |

### 2.2 OCR 與文字

| Patch | 啟用方式 | 能力／效果 |
|---|---|---|
| **PaddleOCR 引擎**<br>`89895eb` `83cab4a` `0bb1f3a` | `org.audiveris.omr.text.OcrUtil.ocrEngine=paddle`<br>＋ 啟動 [`dev/paddleocr/paddle_ocr_server.py`](dev/paddleocr/paddle_ocr_server.py) | 改用本機 PP-OCRv5 服務（HTTP，預設 `127.0.0.1:8868`），回傳行／字／字元框，字元框貼齊實際墨跡。實測和弦名辨識率約 **59% → 90%+**，排練記號不再被讀成漢字。CPU 上關閉 mkldnn，避開 PaddlePaddle 3.x 的 oneDNN 崩潰。 |
| **禁止靜默退回 Tesseract**<br>`247887e` | 隨 `ocrEngine=paddle` 生效 | 指定 paddle 但服務連不上時**直接報錯**，不再默默改用 Tesseract 產出低品質結果；未知的 `ocrEngine` 值同樣報錯。 |
| **和弦名 add 音**<br>`5720d71` | 預設生效 | 支援 `add2 / add4 / add9 / add11 / add13`（如 `Bbadd9`、`F#madd11`、`Cadd9/E`），以 `degree-type add` 匯出。 |
| **和弦根音與後綴合併**<br>`af3e7d9` | 預設生效 | 印刷時中間有空隙的和弦（`E sus4`）在判定文字角色前合併為 `Esus4`；只在根音合法、合併後也合法且間距小於字高時才合併。 |
| **排練記號框內文字清除**<br>`4194106` | 預設生效 | 能穿透方框讀字的 OCR（PaddleOCR）會在排練記號上生出一般文字，進而殺掉排練記號；現在先移除這些重疊文字。 |
| **Direction 文字不再遺失**<br>`57de5c2` | 預設生效 | 附近沒有和弦時放寬水平範圍、再找整格最近的和弦，不再丟掉 direction 文字；上方只有休止符時，優先掛到下方的實音和弦。 |

### 2.3 MusicXML 匯出（PartwiseBuilder）

| Patch | 啟用方式 | 能力／效果 |
|---|---|---|
| **整小節休止符時值隔離**<br>`485dba4` `b11861f` | 預設生效 | 拍號已知時，整小節休止符一律等於應有時值，不再沿用該格實際長度：某聲部多讀（過長）或漏讀（過短）都不會牽連其他聲部；弱起等隱含小節除外。實測 297 號曲過短休止符 8 → 0，偽 OVER 消除約 75%。 |
| **鬼休止符 voice 消除**<br>`c8a90a6` `8d8bdf7` | 預設生效；<br>`org.audiveris.omr.score.PartwiseBuilder.dropGhostRests=false` 可關閉 | 有實音的譜表上，丟掉只有休止符的多餘 voice，並把剩下的 voice 依 Audiveris 的譜表 id 家族（1–4／5–8／9–12）重新編號。避免播放游標膨脹與聲部倒置。21 頁 A/B 測試：鬼休止小節 24 → 0，音符 5140/5140 全數保留。 |
| **`%` 小節反覆展開修正**<br>`0c63a21` | 預設生效 | 只出現在部分譜表（如鋼琴左手）的 `%`：只複製這些譜表的 voice，並先倒回小節起點；不再拼出 4/4 裡 8 拍的小節。 |
| **6(9) 和弦匯出**<br>`0c63a21` | 預設生效 | 六和弦只加 9 音時不輸出括號度數，避免 MuseScore 合併成 `69` 後留下空括號。 |

### 2.4 穩定性

| Patch | 情境 | 效果 |
|---|---|---|
| `b30a567` | 房子線段退化（次像素或反向） | 避免 `NegativeArraySizeException` |
| `a5e7e2e` | 重新載入空的 RunTable；beam 缺 side stem | 避免 `.omr` 載入失敗與 NPE |
| `a7e2bce` | 漸強／漸弱結尾和弦沒有時間位置 | 跳過該結尾，不再讓整小節匯出失敗 |
| `b4e21b6` | OCR 字框略超出影像 | 先裁到 OCR 緩衝區內，避免陣列越界 |

---

## 3. 建置與使用

### 建置

需要 **JDK 25**（上游 5.11 的要求）。

```bash
./gradlew :app:installDist -x test
# 產物：app/build/install/app/bin/Audiveris
```

> 原始碼檔為 CRLF 換行，手動修改時請保持。

### 啟動 PaddleOCR 服務（使用 `ocrEngine=paddle` 時）

```bash
pip install paddleocr pillow numpy     # 建議放在獨立 venv
python dev/paddleocr/paddle_ocr_server.py --port 8868
curl http://127.0.0.1:8868/health      # 回應 "ok <det> <rec>"
```

### 批次執行範例

```bash
Audiveris -batch -export -output out/ \
  -constant org.audiveris.omr.sheet.rhythm.PageRhythm.defaultTimeSignature=4/4 \
  -constant "org.audiveris.omr.score.PartCollation.partsHint=Vocal|Vo.:1:lyrics; A.Piano|A.pf:2; Strings I|Str. I:1" \
  -constant org.audiveris.omr.text.OcrUtil.ocrEngine=paddle \
  -constant org.audiveris.omr.sheet.ProcessingSwitches.endings=false \
  -- page01.png
```

`partsHint` 撰寫要點：

- 順序與譜表數必須與原譜完全一致（大譜表寫 `:2`，單行寫 `:1`）。
- 用 `|` 列出全名與縮寫，讓首頁與後續頁都能對上。
- 器樂譜（沒有人聲）可以直接關掉歌詞：`org.audiveris.omr.sheet.ProcessingSwitches.lyrics=false`。

已存好的 `.omr` 若只需要套用新的匯出邏輯，不必重跑 OMR：

```bash
Audiveris -batch -export -output out/ -- page01.omr
```

---

## 4. 與上游的關係

- 本分支只修改與樂團譜相關的辨識與匯出；介面、編輯器、其他步驟沿用上游。
- 上游的安裝、使用與編輯器操作請看 [Audiveris Handbook](https://audiveris.github.io/audiveris/)。
- 上游專案：[Audiveris/audiveris](https://github.com/Audiveris/audiveris)。注意：`audiveris.com`、`audiveris.net` 與 Audiveris 無關，疑似詐騙網站。
