# Audiveris-Bandscore

[中文](README.md) | English

> [!IMPORTANT]
> **AI agents, read this first:** when asked to convert a score, do **not** run Audiveris directly. Read [`skill/SKILL.md`](skill/SKILL.md) in full and follow its steps in order from Step 0, inside `skill/`. The preparation steps give the parts, lyrics, drums and instruments; skipping them makes all of these come out wrong.

A fork of [Audiveris](https://github.com/Audiveris/audiveris) for **band scores and keyboard scores** (Japanese-style "bandscore" books).
The goal is OMR that outputs **MusicXML that plays correctly in MuseScore**, fixing inside the Audiveris core the problems that used to need hand repair after recognition.

- Base: upstream Audiveris **5.12.0** (`598d16410`); the changes are listed in section 2
- Branch: `bandscore` (default branch)
- License: same as upstream, [AGPL-3.0](LICENSE)
- **Download**: prebuilt zips for macOS (Apple Silicon, Intel) and Windows on the [Releases](https://github.com/hibikiwtnb/audiveris-bandscore/releases) page (needs Java 25). For playback and checking, use [MuseScore-Bandscore](https://github.com/hibikiwtnb/MuseScore/releases).
- **AI conversion workflow**: [`skill/`](skill/README.md) is a manual and toolset for AI agents that takes a band score PDF all the way to playable MusicXML. Illustrated guide (Chinese): [read online](https://hibikiwtnb.github.io/audiveris-bandscore/)
- Reporting problems and proposing changes: [CONTRIBUTING.md](CONTRIBUTING.md)

The detailed setting reference [USAGE.md](USAGE.md) and the skill documents are in Chinese for now.

---

## 1. Background

Audiveris is the most widely used open-source OMR engine, but on Japanese band and keyboard scores it keeps hitting the same problems, and the MusicXML it writes is close to unusable as is:

- **Parts out of place**: band scores print only the instruments that play on each system, and OCR often misreads instrument names (`Str. I` → `Str. l`). Audiveris cannot map the staves of every system and page to the same part, so the part count is wrong, music lands in other parts, and the merged song falls apart.
- **Lost time signatures**: when a page does not print a time signature at the top (true of every page after the first when pages are read one by one), the whole page has none and measure lengths cannot be checked.
- **One error spoils the whole measure**: one extra or missing note in a part makes the whole-measure rests of every other part longer or shorter, the measure's timing is wrong everywhere, and the parts drift apart on playback.
- **Ghost rest voices**: staves with real notes get extra voices holding only rests; the MuseScore playback cursor jumps around and voices swap places.
- **Poor text recognition**: Tesseract reads chord names (`Bbadd9`, `E sus4`) and rehearsal marks badly, sometimes reading rehearsal marks as kanji; text such as `pizz.` and `Woodwind` is taken as lyrics; some expressions and tempo marks vanish.
- **Wrong structure**: technique extension lines (`— pizz. —↓`) are taken as 1st/2nd endings and add repeats on playback; a `%` measure repeat printed in only some staves is expanded into an 8-beat measure in 4/4.
- **Crashes**: some pages throw NPEs or index errors during recognition or export, and the page or measure is lost.

This fork's approach: **fix at the source what can be fixed at the source** — change Audiveris's recognition and export logic instead of patching the XML afterwards.

Input-hint features are **opt-in** `-constant` switches; without them the behavior is the same as upstream. Text and symbol recognition, export fixes, stability and speed fixes are on by default (see the "Setting" column of each table in section 2; how to set them is in [USAGE.md](USAGE.md)).

---

## 2. Changes

On top of upstream 5.12.0 this branch has 87 commits that change code. Leaving out a pair that was added and reverted, one that only changed line endings and one that removed cache files, that is 83 patches, grouped from 2.2 on into 11 categories and 41 improvements:

| Category | Improvements | Commits |
|---|---|---|
| Parts and lyrics (2.2–2.3) | 5 | 8 |
| Text and chord names (2.4–2.5) | 8 | 21 |
| Drums and guitar (2.6–2.7) | 10 | 27 |
| Key signatures, rhythm and symbols (2.8–2.10) | 15 | 23 |
| Stability and speed (2.11–2.12) | 3 | 10 |
| **Total** | **41** | **83** |

Six commits touch two categories, so the per-category commit counts add up to more than the total.

### 2.1 Overall effect

All numbers below compare upstream Audiveris 5.11.0 with this branch on the same input images, with no post-processing on either side (measured before this branch merged upstream 5.12.0).

**Score structure**: a 21-page keyboard band score with 5 parts (piano grand staff, plus two string and two synthesizer parts), each page recognized on its own.

| Measure | Upstream | This branch |
|---|---|---|
| Total parts (21 pages × 5 parts, correct: 105) | 139 | **105** |
| Pages with the wrong number of parts | 10 / 21 | **0** |
| Measures with wrong length | 23% (391 / 1633) | **6%** (109 / 1755) |
| Whole-measure rests spoiled by other parts | 261 | **16** |
| Ghost rest measures | 24 | **0** (all 5140 notes kept) |
| Chord names | 96 | **227** |
| Noise text taken as text | 48 | **10** |
| Rehearsal marks | about 3 correct, the rest misread (`Al`, `El`, duplicate `D1`) | **all 7 correct** |
| Crashed pages | 2 | **0** |

**Text recognition**: 6 pages of band and keyboard scores annotated by hand, comparing two OCR engines on the same images Audiveris actually sends to OCR.

| Kind | Tesseract (upstream) | PaddleOCR (this branch) |
|---|---|---|
| Chord names | 54 / 91 (59%) | **82 / 91 (90%)** |
| Instrument names | 31 / 84 (37%) | **64 / 84 (76%)** |
| Rehearsal marks | 1 / 7 | **7 / 7** |
| Performance directions | 20 / 37 | **29 / 37** |
| Noise tokens | 305 | **172** |
| Time per page | about 1 s | about 12 s |

Almost all remaining instrument-name errors are `II` read as `11` or `ll`, which `partsHint` already tolerates. PaddleOCR is slower, but most of its text can be used as is.

The tables below list the improvements over upstream, by what they deal with. **Setting**: "Default" means nothing to do; the others link to how to set them in [USAGE.md](USAGE.md).

### 2.2 Parts

| Improvement | Effect | Setting |
|---|---|---|
| Part mapping | • In band scores that print only some instruments on each system, each staff now maps to the right part, and the part count matches<br>• Parts stay matched when OCR misreads instrument names | [`partsHint`](USAGE.md#partshint) |
| TAB kept in its part | • Fixed guitar parts getting the wrong staff count when the TAB is not recognized or is split off as its own part | [`:tab`](USAGE.md#tab) |
| Instrument sounds | • Each part's exported General MIDI sound can now be set<br>• Without a setting, one-line-staff parts get a voice sound and the others piano | [`:gm`](USAGE.md#gm) |

### 2.3 Lyrics

| Improvement | Effect | Setting |
|---|---|---|
| Where lyrics are read | • Lyrics are read only under the staves marked as having lyrics (any number of them); text such as `pizz.` and `Woodwind` is no longer attached to notes | [`:lyrics`](USAGE.md#lyrics) |
| Misread symbols | • Kana and punctuation in lyrics are no longer read as accents or staccatos | Default |

### 2.4 Text

| Improvement | Effect | Setting |
|---|---|---|
| Recognition accuracy | • Text recognition uses PP-OCR; chord names, instrument names and rehearsal marks are read much better<br>• Japanese lyrics are read syllable by syllable with a lyrics model, and can be limited to chosen scripts<br>• Extender lines under lyrics are no longer read as characters<br>• The OCR service can run on another computer | Default; lyrics need [`lyricsScripts`](USAGE.md#lyricsscripts) |
| Where text belongs | • Short text between staves (D.S., 2x, sound names) is attached to its measure instead of being taken as the page title<br>• Fixed text being dropped when no chord is nearby<br>• TAB fret numbers and lines made only of rules and brackets are no longer exported as text | Default |
| Text size | • Fixed huge text in the middle of a staff when an OCR box is wrong<br>• Fixed titles and chord names sometimes getting a huge font size | Default |
| Rehearsal marks | • Boxed rehearsal marks are read correctly, not as `Al`, `El` or chord names<br>• Chord names next to them no longer pick up the box lines<br>• Fixed boxed marks being assigned to the previous measure | Default |
| Glissando export | • `gliss.` and the guitar `S` are exported as a slide line between two notes, which MuseScore plays | Default |

### 2.5 Chord names

| Improvement | Effect | Setting |
|---|---|---|
| Recognition | • Added chords such as `add2`, `add9`, `add11` are supported<br>• Fixed chord names with a gap (`E sus4`) being split into two texts<br>• Better OCR of ♭ in chord names, which used to be very poor<br>• Small ♭ can be found with the book's template, and ♭ lost by OCR is put back<br>• The usual OCR misreadings of chord names are repaired before parsing: `$`, `^` or a `-` after the root is a # (`F$m`, `C-m7`), and `(>5)`, `(65)`, `(5)` after m7 is (b5); such chord names, and their whole line, used to be exported as plain text | Default; the template needs [`openingFifths`](USAGE.md#openingfifths) |
| Position | • Several chord names over one long note now each sit on their own beat instead of all stacking at the note's start | Default |
| Export | • Fixed 6(9) chords showing as `69()` in MuseScore | Default |

### 2.6 Drums and percussion

| Improvement | Effect | Setting |
|---|---|---|
| Drum staff export | • Drum parts are exported with a percussion clef and drum sounds whatever clef is printed (band scores often use a bass clef for drums)<br>• With several drum parts on a page, each part uses its own drum sound definitions | [`:drums`](USAGE.md#drums) |
| X noteheads | • Noteheads on drum staves are looked for at the drum kit's positions, including hi-hat and crash x-heads<br>• X-heads can be found with templates made from the book, whatever the print density<br>• X-heads crossed by staff lines or sitting on ledger lines are found too<br>• Fixed x-head stems and dots being attached wrongly, and x-head legs being taken as dots<br>• Fixed single hi-hats losing their stems<br>• A wrong template folder path now stops with an error | [`templateDir`](USAGE.md#templatedir) |
| The book's drum map | • When a book writes drums differently from the usual (e.g. hi-hat on the top line), your own mapping can override it | [`templateDir`](USAGE.md#templatedir) |
| One-line staves | • Percussion staves with a single line, and x-heads on them, are recognized<br>• Fixed five-line staff lines being taken as one-line staves<br>• Fixed one-line staves being dropped on slightly warped pages, and runs of ties being taken as one-line staves<br>• A one-line staff whose barlines do not reach the drums staff above is no longer made a system of its own (the page had its measure count doubled, the percussion played after the other parts) | [`:oneline`](USAGE.md#oneline) |
| Open/closed marks | • Hi-hat open/closed marks (`+`, `o`) above drum staves are no longer exported as text | [`:drums`](USAGE.md#drums) |
| Sound numbers | • Fixed every drum sound being off by one, which turned bass drum and hi-hat into other drums on playback | Default |

### 2.7 Guitar

| Improvement | Effect | Setting |
|---|---|---|
| Slash noteheads | • Guitar slashes (play the previous chord in this rhythm) are recognized and exported as slash noteheads, counted as normal notes in the rhythm | [`templateDir`](USAGE.md#templatedir) |
| Capo transposition | • A guitar with a capo keeps its own written key signature instead of being overwritten by the other parts' key | [`:capo`](USAGE.md#capo) |
| Staff line spacing | • When the TAB lines are wider apart than the five-line staff, the five-line staff is no longer treated as a cue/ossia staff, and notes on ledger lines are no longer lost<br>• Every staff (five-line or TAB) now uses the line spacing measured from its own lines; fixed five-line staves being searched with the TAB's size for heads, ledgers and key signatures | Default |
| Down-tuning | • Guitars and basses tuned down a half step (or more) keep their own written key, e.g. vocal in A♭ and guitar in A, instead of being unified to one key | [`:down`](USAGE.md#down) |

### 2.8 Key signatures

| Improvement | Effect | Setting |
|---|---|---|
| Recognition | • Fixed faintly printed flats whose stems break at the staff lines being read as only one or two flats | Default |
| Key templates | • With the book's ♯/♭ templates, the key at the start of each system is read by matching templates at fixed positions: flats cut by staff lines are no longer undercounted, and accidentals right after the key are no longer counted in<br>• All 7 positions are checked before deciding (instead of stopping at the first miss), so one weak match in the middle still counts; positions come from the book's measured `key_layout.txt` | [`templateDir`](USAGE.md#templatedir) |
| One key for all staves | • All staves of a measure now use the same key, and staves whose key was missed are no longer output in C major<br>• Transposing instruments (trumpet, saxophone, horn…) get their own key from the part name<br>• Fixed key changes in the middle of a system taking effect only from the next system | Default |

### 2.9 Measures and rhythm

| Improvement | Effect | Setting |
|---|---|---|
| Default time signature | • When a page does not print a time signature at the top, a given one can be used, so page-by-page recognition keeps its length checks | [`defaultTimeSignature`](USAGE.md#defaulttimesignature) |
| Tuplets | • Fixed noteheads read as triplet marks, which broke measure lengths | Default |
| Whole-measure rests | • When a part has an extra or missing note, the other parts' whole-measure rests no longer get longer or shorter | Default |
| Rests for empty staves | • A staff with nothing in a measure gets a whole-measure rest, so all staves have the same length | Default |
| Extra rest voices | • Extra voices with only rests on staves that have notes are dropped; the MuseScore playback cursor and voice order are no longer confused | Default |
| `%` measure repeats | • Fixed a `%` printed in only some staves being expanded into an 8-beat measure in 4/4<br>• `%` now records how many measures repeat, so software that supports it can show it as a `%` sign<br>• Fixed a `%` at the start of a part copying nothing when the previous part ended with a `%`<br>• Fixed added whole-measure rests overlapping the copied notes | Default |
| Second-time notes (2x) | • Notes in brackets marked "2x" are exported as MusicXML `time-only`: the first and second time each have the right length, MuseScore can play them per pass, and the measure is no longer too long<br>• For `D.S.x` or when a measure cannot be filled, the second-time notes can be skipped, keeping only the first time | Default; skipping needs [`dropParenthesized`](USAGE.md#dropparenthesized) |

### 2.10 Other symbols

| Improvement | Effect | Setting |
|---|---|---|
| Misread rests | • Quarter rests are no longer read as hollow noteheads<br>• Text is no longer read as a very wide half rest | Default |
| Articulation attachment | • Accents and staccatos are no longer attached to far-away notes of other parts | Default |
| Misread endings | • Ending detection can be turned off, so extension lines such as `— pizz. —↓` are not taken as 1st/2nd endings<br>• Fixed unrecognized TAB or one-line staff lines being taken as endings and stealing each part's barlines | Turning detection off needs [`endings`](USAGE.md#endings) |
| Octave shift export | • 8va/8vb now follows the printed dashed line and exports a `stop` after the last note it covers, so the whole passage stays shifted and the postprocess no longer drops it as an unterminated fragment<br>• An "8va →" label with no dashed line is no longer taken as an octave shift | Default |
| D.S./Coda playback | • With the book's `segno.png` and `coda.png`, the segno and coda marks above the first staff are confirmed by template, so `<segno>`/`<coda>` and named `<sound segno=...>`/`<sound coda=...>` are exported even when the classifier misses them<br>• A mark above the staff that is not exactly on a barline is attached to the nearest staff barline<br>• `D.S.`, `D.C.`, `To Coda`/`to ⊕` and `Fine` are exported as `dalsegno`, `dacapo`, `tocoda` and `fine` at the end of their measure<br>• Later-pass texts such as `D.S.①x` and `2x` are not taken as jumps | [`templateDir`](USAGE.md#templatedir) (mark templates) |

### 2.11 Stability

| Improvement | Effect | Setting |
|---|---|---|
| Crash fixes | • Fixed a crash on degenerate ending segments<br>• Fixed some `.omr` files failing to load<br>• Fixed the end of a crescendo/diminuendo making a whole measure fail to export<br>• Fixed a crash when an OCR box runs off the image<br>• Fixed page recognition stopping after a barline is removed<br>• Fixed crashes caused by some tempo marks, unclassifiable text lines and slurs with no staff<br>• Fixed pages whose shortest note is a half or whole note exporting a divisions value of 0 | Default |

### 2.12 Speed

| Improvement | Effect | Setting |
|---|---|---|
| OCR speed | • PP-OCR can use oneDNN on CPU (except on Windows)<br>• PP-OCR can run on a GPU, from about 50 s to about 3 s of OCR per page, with results identical to CPU | GPU needs [`--device`](USAGE.md#paddleocr-服務) |
| BEAMS step speed | • The image closing before beam detection is computed row by row; the BEAMS step goes from about 5.4 s to about 2.3 s per page, with identical output | Default |

---

## 3. Build and use

Prebuilt zips are on the [Releases](https://github.com/hibikiwtnb/audiveris-bandscore/releases) page. To build it yourself:

### Build

Needs **JDK 25** (upstream's requirement).

```bash
./gradlew :app:installDist -x test
# output: app/build/install/app/bin/Audiveris
```

> Source files use CRLF line endings; keep them when editing by hand.

### Start the PaddleOCR service (the default OCR engine)

```bash
pip install paddleocr pillow numpy     # a separate venv is recommended
python dev/paddleocr/paddle_ocr_server.py --port 8868   # add --host 0.0.0.0 to serve other machines
curl http://127.0.0.1:8868/health      # answers "ok <det> <rec> lyrics=<lyrics-rec>"
```

### Batch example

```bash
Audiveris -batch -export -output out/ \
  -constant org.audiveris.omr.sheet.rhythm.PageRhythm.defaultTimeSignature=4/4 \
  -constant "org.audiveris.omr.score.PartCollation.partsHint=Vocal|Vo.:1:lyrics; A.Piano|A.pf:2; Strings I|Str. I:1" \
  -constant org.audiveris.omr.text.TextBuilder.lyricsScripts=hiragana,katakana,punct \
  -constant org.audiveris.omr.sheet.ProcessingSwitches.endings=false \
  -- page01.png
```

How each constant is written and used: [USAGE.md](USAGE.md) (Chinese).

A saved `.omr` only needs re-exporting to pick up new export logic; OMR does not have to run again (it does if `partsHint` or `templateDir` changed):

```bash
Audiveris -batch -export -output out/ -- page01.omr
```

---

## 4. Relation to upstream

- This branch changes only the recognition and export related to band scores; the interface, editor and other steps are upstream's.
- For upstream installation, use and the editor, see the [Audiveris Handbook](https://audiveris.github.io/audiveris/).
- Upstream project: [Audiveris/audiveris](https://github.com/Audiveris/audiveris). Note: `audiveris.com` and `audiveris.net` have nothing to do with Audiveris and appear to be scam sites.
