#!/usr/bin/env python3
"""Deterministic OMR-noise cleanup for normalized / merged MusicXML.

Idempotent, in-place.  Each fix is either a skill retrospective rule or a
MusicXML DTD requirement, and removes only what Audiveris invented wrongly:

  1. rest display positions -- <rest> may carry <display-step>/<display-octave>;
     they push rests off the staff and inflate system height
     (skill Retrospective #7).  Pitched rests default to the middle line.
  2. dangling wedges & octave-shifts -- a <wedge type="crescendo|diminuendo"> or
     <octave-shift type="up|down"> with no matching type="stop" is an OMR fragment
     (skill Retrospective #8). Remove the element; if that empties its <direction-type>,
     drop that, and if the <direction> then has no direction-type at all, drop the
     whole direction (DTD: direction requires direction-type+).
  3. duplicate ties & invalid ties -- a note may carry the same <tie> (or notations <tied>)
     several times; DTD allows at most one per type. Also prunes spurious ties that
     cross pitches or dangle without matches (Lesson 42).
  4. <staves> inside <score-part> -- not allowed by the MusicXML 3.1 DTD (the
     staff count belongs in <attributes>); remove it from part-list.
  5. empty lyrics -- <lyric> with no text and no children is pure noise.
  6. slurs -- OMR misrecognized slurs as ties or noisy curves (Lesson 42);
     cleanly drop them to avoid obstruction during proofreading.
  7. measure repeat overlays -- Audiveris exports measure repeats with a dummy <rest measure="yes"/>,
     <backup>, and notes in the same voice; MuseScore stacks them causing duration mismatch
     (e.g. 6/4 in 4/4). Redundant rest and backup are removed when notes follow.
  8. spurious articulations -- drops staccatissimo (martellato is not used in band scores),
     vocal/chorus articulations caused by lyric characters/dakuten/i-dots/chords, and deep
     off-staff articulations (placement="below", default-y <= -50) colliding with TAB/lyrics.

Usage:
    clean_score_noise.py FILE [FILE ...]
"""
import re
import sys
import xml.etree.ElementTree as ET

WEDGE_START = ("crescendo", "diminuendo")


def strip_rest_positions(root):
    n = 0
    for rest in root.iter("rest"):
        for tag in ("display-step", "display-octave"):
            e = rest.find(tag)
            if e is not None:
                rest.remove(e)
                n += 1
    return n


def strip_dangling_wedges(root):
    n = 0
    for part in root.findall("part"):
        unbalanced = []
        for m in part.findall("measure"):
            for w in m.iter("wedge"):
                t = w.get("type")
                if t in WEDGE_START:
                    unbalanced.append(w)
                elif t == "stop" and unbalanced:
                    unbalanced.pop()
        for w in unbalanced:
            parent = None
            for p in root.iter():
                if w in list(p):
                    parent = p
                    break
            if parent is None:
                continue
            parent.remove(w)
            if parent.tag == "direction-type" and len(parent) == 0:
                direction = None
                for p in root.iter():
                    if parent in list(p):
                        direction = p
                        break
                if direction is not None:
                    direction.remove(parent)
                    if not any(c.tag == "direction-type" for c in direction):
                        up = None
                        for p in root.iter():
                            if direction in list(p):
                                up = p
                                break
                        if up is not None:
                            up.remove(direction)
            n += 1
    return n


def strip_dangling_octave_shifts(root):
    n = 0
    for part in root.findall("part"):
        unbalanced = []
        for m in part.findall("measure"):
            for d in m.findall("direction"):
                st = d.findtext("staff", "1")
                for o in d.iter("octave-shift"):
                    t = o.get("type")
                    if t in ("up", "down"):
                        unbalanced.append((o, st))
                    elif t == "stop":
                        match_idx = next((i for i in reversed(range(len(unbalanced))) if unbalanced[i][1] == st), None)
                        if match_idx is not None:
                            unbalanced.pop(match_idx)
                        else:
                            unbalanced.append((o, st))
        for o, _ in unbalanced:
            parent = None
            for p in root.iter():
                if o in list(p):
                    parent = p
                    break
            if parent is None:
                continue
            parent.remove(o)
            if parent.tag == "direction-type" and len(parent) == 0:
                direction = None
                for p in root.iter():
                    if parent in list(p):
                        direction = p
                        break
                if direction is not None:
                    direction.remove(parent)
                    if not any(c.tag == "direction-type" for c in direction):
                        up = None
                        for p in root.iter():
                            if direction in list(p):
                                up = p
                                break
                        if up is not None:
                            up.remove(direction)
            n += 1
    return n


def strip_duplicate_ties(root):
    n = 0
    for note in root.iter("note"):
        for tag in ("tie", "tied"):
            seen = set()
            holders = [note] if tag == "tie" else list(note.findall("notations"))
            for holder in holders:
                for t in list(holder.findall(tag)):
                    typ = t.get("type")
                    if typ in seen:
                        holder.remove(t)
                        n += 1
                    else:
                        seen.add(typ)

    return n


def strip_all_slurs(root):
    """Drop all <slur> notations from notes (Lesson 42)."""
    n = 0
    for note in root.iter("note"):
        for notat in list(note.findall("notations")):
            for s in list(notat.findall("slur")):
                notat.remove(s)
                n += 1
            if len(notat) == 0:
                note.remove(notat)
    return n


def _get_pitch(n):
    if n.find("rest") is not None:
        return None
    s = n.findtext("pitch/step", "")
    a = n.findtext("pitch/alter", "0")
    o = n.findtext("pitch/octave", "")
    return (s, a, o)


def _has_tie(note, typ):
    for tag in ("tie", "tied"):
        for holder in ([note] if tag == "tie" else list(note.findall("notations"))):
            if any(t.get("type") == typ for t in holder.findall(tag)):
                return True
    return False


def _add_tie(note, typ):
    """Add a <tie>/<tied> of the given type, keeping MusicXML child order."""
    if not any(t.get("type") == typ for t in note.findall("tie")):
        idx = len(note)
        dur = note.find("duration")
        if dur is not None:
            idx = list(note).index(dur) + 1
        note.insert(idx, ET.Element("tie", {"type": typ}))
    notat = note.find("notations")
    if notat is None:
        notat = ET.Element("notations")
        pos = len(note)
        for i, ch in enumerate(note):
            if ch.tag in ("lyric", "play"):
                pos = i
                break
        note.insert(pos, notat)
    if not any(t.get("type") == typ for t in notat.findall("tied")):
        notat.insert(0, ET.Element("tied", {"type": typ}))


def complete_chord_ties(root):
    """Fill missing ties in chords where other tones are tied (general chord tie completion).

    Applies when >= 1 chord tone is tied to the immediately following chord
    in the same voice and another tone continues there with the same pitch.
    Legitimate partial ties (tone changes pitch or does not continue) are
    left untouched.  Returns ties added (2 per filled note: start and stop).
    """
    added = 0
    for part in root.findall("part"):
        seq = {}
        for m in part.findall("measure"):
            notes = [el for el in m if el.tag == "note"]
            i = 0
            while i < len(notes):
                grp = [notes[i]]
                j = i + 1
                while j < len(notes) and notes[j].find("chord") is not None:
                    grp.append(notes[j])
                    j += 1
                st = notes[i].findtext("staff", "1")
                v = notes[i].findtext("voice", "1")
                slot = {}
                for nt in grp:
                    p = _get_pitch(nt)
                    if p is not None:
                        slot[p] = nt
                if slot:
                    seq.setdefault((st, v), []).append(slot)
                i = j

        for slots in seq.values():
            for k in range(len(slots) - 1):
                cur, nxt = slots[k], slots[k + 1]
                if len(cur) < 2 and len(nxt) < 2:
                    continue
                tied = [p for p in cur
                        if _has_tie(cur[p], "start")
                        and p in nxt and _has_tie(nxt[p], "stop")]
                if not tied:
                    continue
                for p in cur:
                    if p in nxt and not _has_tie(cur[p], "start") and not _has_tie(nxt[p], "stop"):
                        _add_tie(cur[p], "start")
                        _add_tie(nxt[p], "stop")
                        added += 2
    return added


def _drop_tie(note, typ):
    """Remove <tie> and <tied> of the given type from a note; return how many were removed."""
    n = 0
    for t in list(note.findall("tie")):
        if t.get("type") == typ:
            note.remove(t)
            n += 1
    for notat in list(note.findall("notations")):
        for t in list(notat.findall("tied")):
            if t.get("type") == typ:
                notat.remove(t)
                n += 1
        if len(notat) == 0:
            note.remove(notat)
    return n


def _voice_chords(part):
    """voice -> chords in document (= time) order; chord = {pitch: note}, {} for a rest.
    A voice id is unique within a part."""
    voices = {}
    chord = None
    for m in part.findall("measure"):
        for el in m:
            if el.tag != "note" or el.find("grace") is not None:
                continue
            pitch = _get_pitch(el)
            if el.find("chord") is not None and chord is not None:
                if pitch is not None:
                    chord[pitch] = el
                continue
            chord = {} if pitch is None else {pitch: el}
            voices.setdefault(el.findtext("voice", "1"), []).append(chord)
    return list(voices.values())


def _staff_chords(part):
    """staff -> chords of all voices ordered by onset within each measure, same format.
    Finds ties that pass from one voice to another on the same staff."""
    staves = {}
    for m in part.findall("measure"):
        offset = last = 0
        slots = {}
        for el in m:
            if el.tag == "note":
                if el.find("grace") is not None:
                    continue
                if el.find("chord") is not None:
                    at = last
                else:
                    at = last = offset
                    offset += int(el.findtext("duration", "0"))
                slot = slots.setdefault((el.findtext("staff", "1"), at), {})
                pitch = _get_pitch(el)
                if pitch is not None:
                    slot[pitch] = el
            elif el.tag == "backup":
                offset -= int(el.findtext("duration", "0"))
            elif el.tag == "forward":
                offset += int(el.findtext("duration", "0"))
        for (st, at), slot in sorted(slots.items(), key=lambda kv: kv[0][1]):
            staves.setdefault(st, []).append(slot)
    return list(staves.values())


def _dangling_ties(sequences, keep_ends):
    """(note, type) of every tie start / stop with no matching partner in the neighbouring
    chord of its sequence (same pitch, opposite tie type). With keep_ends, a stop on the first
    chord / a start on the last chord of a sequence has no neighbour to check and is kept."""
    bad = []
    for chords in sequences:
        for i, cur in enumerate(chords):
            prev = chords[i - 1] if i > 0 else {}
            nxt = chords[i + 1] if i + 1 < len(chords) else {}
            for pitch, n in cur.items():
                if ((i + 1 < len(chords) or not keep_ends) and _has_tie(n, "start")
                        and not (pitch in nxt and _has_tie(nxt[pitch], "stop"))):
                    bad.append((n, "start"))
                if ((i > 0 or not keep_ends) and _has_tie(n, "stop")
                        and not (pitch in prev and _has_tie(prev[pitch], "start"))):
                    bad.append((n, "stop"))
    return bad


def prune_invalid_ties(root):
    """Enforce strict same-pitch and contiguous ties (Lesson 42).

    Removes:
      1. Duplicate ties (multiple start or stop on same note)
      2. Cross-pitch ties (start pitch != stop pitch)
      3. Dangling ties (unmatched start/stop within document)
    Preserves boundary ties at document start/end for single-page files.

    A tie is judged in two views: the next chord of the same voice, and the next chord on the
    same staff (any voice). It is removed only when both views reject it: other voices sounding
    in between must not kill a valid tie, and Audiveris does tie across voices of one staff.
    Repeated until stable, since removing one end of a tie orphans the other end.
    """
    total_removed = strip_duplicate_ties(root)

    for part in root.findall("part"):
        while True:  # removing a tie can orphan its partner: repeat until stable
            # a voice starts / ends anywhere in the part: only the staff view knows part ends
            by_voice = {(id(n), t) for n, t in _dangling_ties(_voice_chords(part), False)}
            both = [(n, t) for n, t in _dangling_ties(_staff_chords(part), True)
                    if (id(n), t) in by_voice]
            removed = sum(_drop_tie(n, t) for n, t in both)
            total_removed += removed
            if not removed:
                break

    return total_removed


def strip_score_part_staves(root):
    n = 0
    pl = root.find("part-list")
    if pl is None:
        return 0
    for sp in pl.findall("score-part"):
        for st in list(sp.findall("staves")):
            sp.remove(st)
            n += 1
    return n


def strip_empty_lyrics(root):
    n = 0
    for parent in root.iter():
        for l in list(parent.findall("lyric")):
            if len(l) == 0 and not (l.text or "").strip():
                parent.remove(l)
                n += 1
    return n


def strip_measure_repeat_overlays(root):
    """Strip redundant measure rest notes and backups in measures with measure-repeat notes.

    Audiveris exports a measure repeat by writing a <rest measure="yes"/>, <backup>, and then
    the copied notes in the same voice. MuseScore stacks these durations instead of replacing,
    producing over-full measures (e.g. 6/4 in a 4/4 score). Dropping the dummy initial rest
    and backup leaves the playback notes aligned at offset 0 while preserving <measure-repeat>.
    """
    n = 0
    for part in root.findall("part"):
        for m in part.findall("measure"):
            notes = m.findall("note")
            if not notes:
                continue
            first_note = notes[0]
            rest = first_note.find("rest")
            if rest is not None and rest.get("measure") == "yes":
                backups = m.findall("backup")
                if backups and len(notes) > 1:
                    bk = backups[0]
                    rest_dur = first_note.findtext("duration", "")
                    bk_dur = bk.findtext("duration", "")
                    if rest_dur == bk_dur:
                        m.remove(first_note)
                        m.remove(bk)
                        n += 1
    return n


def strip_spurious_articulations(root):
    """Strip OCR junk articulations from lyrics, text serifs, rehearsal marks, and TAB stems.

    Audiveris misinterprets:
      1. All staccatissimo: band scores do not use martellato; all instances are OCR false
         positives on text serifs, commas, exclamation marks, or TAB stems.
      2. Vocal / chorus articulations (staccato, tenuto, accent, strong-accent): vocal pop
         lines do not have staccatos or tenutos; Audiveris picks up lyric dots (i, dakuten,
         punctuation) and above-staff chord/rehearsal symbols.
      3. Deep off-staff articulations (placement="below" and default-y <= -50): collisions
         with lyrics line or TAB staff lines.
    """
    vocal_part_ids = set()
    for sp in root.iter("score-part"):
        name = (sp.findtext("part-name") or "").lower()
        pid = sp.get("id")
        if any(k in name for k in ("vocal", "voice", "vo.", "chorus", "cho.")):
            vocal_part_ids.add(pid)
    for p in root.findall("part"):
        if any(p.iter("lyric")):
            vocal_part_ids.add(p.get("id"))

    n = 0
    for p in root.findall("part"):
        is_vocal = p.get("id") in vocal_part_ids
        for m in p.findall("measure"):
            for note in m.findall("note"):
                notations = note.find("notations")
                if notations is None:
                    continue
                art = notations.find("articulations")
                if art is None:
                    continue
                for a in list(art):
                    tag = a.tag
                    y = float(a.get("default-y", "0"))
                    placement = a.get("placement", "")
                    drop = False
                    if tag == "staccatissimo":
                        drop = True
                    elif is_vocal and tag in ("staccato", "tenuto", "accent", "strong-accent"):
                        drop = True
                    elif placement == "below" and y <= -50:
                        drop = True

                    if drop:
                        art.remove(a)
                        n += 1
                if len(art) == 0:
                    notations.remove(art)
                if len(notations) == 0:
                    note.remove(notations)
    return n


def process(path):
    text = open(path, encoding="utf-8").read()
    mt = re.search(r"<!DOCTYPE[^>]*>", text)
    doctype = mt.group(0) if mt else ""
    root = ET.fromstring(text)
    a = strip_rest_positions(root)
    b = strip_dangling_wedges(root)
    h = strip_dangling_octave_shifts(root)
    c = strip_all_slurs(root)
    d = prune_invalid_ties(root)
    g = complete_chord_ties(root)
    e = strip_score_part_staves(root)
    f = strip_empty_lyrics(root)
    i = strip_measure_repeat_overlays(root)
    j = strip_spurious_articulations(root)
    ET.indent(root, space="  ")
    body = re.sub(r'<measure number="(\d+)"([^>]*?)\s*/>',
                  lambda mm: '<measure number="%s"%s></measure>'
                  % (mm.group(1), mm.group(2)),
                  ET.tostring(root, encoding="unicode"))
    out = ("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n" + doctype + "\n"
           + body + "\n")
    open(path, "w", encoding="utf-8").write(out)
    print("%s: rest-pos %d, wedges %d, octave-shifts %d, slurs %d, pruned-ties %d, "
          "added-chord-ties %d, sp-staves %d, empty-lyrics %d, repeat-overlays %d, spurious-art %d"
          % (path, a, b, h, c, d, g, e, f, i, j))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: clean_score_noise.py FILE [FILE ...]")
    for argv_path in sys.argv[1:]:
        process(argv_path)
