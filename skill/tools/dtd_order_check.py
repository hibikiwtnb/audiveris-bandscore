import sys, xml.etree.ElementTree as ET
SEQ = {
 "attributes": ["footnote","level","divisions","key","time","staves","part-symbol",
                "instruments","clef","staff-details","transpose","directive","measure-style"],
 "note": ["grace","cue","chord","pitch","unpitched","rest","duration","tie","instrument",
          "footnote","level","voice","type","dot","accidental","time-modification","stem",
          "notehead","notehead-text","staff","beam","notations","lyric","play","listen"],
 "direction": ["direction-type","offset","footnote","level","voice","staff","sound","listening"],
 "clef": ["sign","line","clef-octave-change"],
 "key": ["cancel","fifths","mode"],
 "pitch": ["step","alter","octave"],
 "rest": ["display-step","display-octave"],
 "barline": ["bar-style","footnote","level","wavy-line","segno","coda","fermata","ending","repeat"],
 "time": ["beats","beat-type","senza-misura"],
}
bad = 0
r = ET.parse(sys.argv[1]).getroot()
for el in r.iter():
    s = SEQ.get(el.tag)
    if not s: continue
    idx = [s.index(c.tag) for c in el if c.tag in s]
    unknown = [c.tag for c in el if c.tag not in s]
    if idx != sorted(idx):
        bad += 1
        if bad <= 6: print('ORDER', el.tag, [c.tag for c in el])
print('violations:', bad)
