# 要收集的符號模板與處理方式

模板的做法與模板庫見 [templates/README.md](../templates/README.md)：每本書一個資料夾、檔名固定，人挑 3 個左右例子，剪下剛好包住符號的方塊，`learn_template.py` 對齊後平均。

## A：Audiveris 有這個類別，後面的步驟與匯出接得住，只是認不出來 → 補模板

| 符號 | Audiveris | 預定檔名 | 狀態 |
|---|---|---|---|
| 鼓叉頭 | `NOTEHEAD_CROSS` | `cross.png` | 已接入（單頁實測：132 p10 47 個，夏色 p04 28 個） |
| 壓線的叉頭（被譜線或加線穿過） | `NOTEHEAD_CROSS` | `cross_line.png` | 已接入；`lovelive_muse_4513870037718` 已學（夏色 Perc.），`lovelive_sunshine_best` 待學（132 m6 加線上的 crash） |
| 踩在粗短加線上的叉頭 | `NOTEHEAD_CROSS` | `cross_ledger.png` | 已接入；`lovelive_muse_4513870037718` 已學（夏色 p02 hi-hat） |
| 圓圈叉 ⊗ | `NOTEHEAD_CIRCLE_X` | `circle_x.png` | 待收集例子 |
| 小節反覆 𝄎（含 2、4 小節） | `REPEAT_ONE_BAR` / `REPEAT_TWO_BARS` / `REPEAT_FOUR_BARS`，匯出為 `measure-repeat` | `repeat1.png` `repeat2.png` | 待收集例子 |
| hi-hat 上的 o / + | `PLAYING_OPEN` / `PLAYING_CLOSED` | `open.png` `closed.png` | 待收集例子 |

## B：Audiveris 沒有這個類別 → 新增形狀，並讓符桿、節奏、匯出都認得

| 符號 | 備註 |
|---|---|
| 實心斜線 | 已接入：形狀 `NOTEHEAD_SLASH`，模板 `slash.png`，匯出 `<notehead>slash</notehead>`，音高由 `fill_slash_chords.py` 抄前一個和弦。`lovelive_sunshine_best` 已學（132 p10：E.G. I／II 各小節節奏與原譜相同，只差和弦或符槓本身沒認出來的小節） |
| 空心斜線（二分、全音符） | 待收集例子 |
| 整小節斜線（沒有符桿） | 待收集例子 |

## 2× 與 1× tacet：只在第二遍演奏

例：216 未来の僕らは知ってるよ p2（`raw/216_p02.omr`）第 1 段 m1 的鋼琴（上下兩行）：
小節左半是第一遍（4 拍），右半是「2×」加大括號 `( … )` 的第二遍（另 4 拍），同小節其他樂器是正常的 4 拍。
同頁第 3 段 Key.II 的「┌1× tacet →」是另一種寫法：範圍內第一遍不彈。

決定（使用者）：**不拆小節、不用 1 房／2 房；由改造過的 MuseScore（`hibikiwtnb/musescore` 的 `bandscore` 分支）顯示並播放「同一小節內的第二遍音符」，只有標 2× 的樂器顯示兩遍內容，其他樂器不變。**

MusicXML 寫法（Audiveris 輸出、MuseScore 匯入共同遵守）：
- 2× 小節裡，該譜表第一遍的音符加 `time-only="1"`，接著 `<backup>` 回小節開頭，第二遍的音符放在另一個 voice、加 `time-only="2"`；小節長度不變，其他樂器照常。
- 延音線照實際音樂寫：第一遍、第二遍的最後一個音都可以 tie 到下一小節。
- 括號與「2×」不輸出，由 MuseScore 依 `time-only` 自己畫（兩遍左右排開、第二遍放在高圓括號內、右括號在小節線前）。

Audiveris（fork `fddd57179` 起）：括號內的和弦標成第二遍（chord 屬性 `pass`），不算進小節節奏，恰好填滿小節時照上述寫法匯出。
- 「2×」、`(`、`)`、「1× tacet」用模板定位，得到受影響的譜表和括號的 x 範圍。
- Audiveris 的節奏是整個系統一起算的，改動前先讀 RHYTHMS 相關程式碼。

## C：不用模板

TAB 數字（由五線譜生成）、和弦名與 N.C. / H / P / S / simile 等文字（OCR）、推弦滑音顫音的曲線。
