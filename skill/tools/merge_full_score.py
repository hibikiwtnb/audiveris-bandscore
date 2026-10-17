#!/usr/bin/env python3
"""Merge a main partwise score with a second partwise score of the same song
(e.g. a separately printed Keyboard part) into one multi-part score for
MuseScore.

Measure i of the main score is aligned with measure i of the second score.
When one group has one extra measure (a typical print/OMR difference), pass
--insert-rest-in-main N or --insert-rest-in-extra N: an all-rest measure is put
at output measure N of that group and everything after it shifts one measure
later, so the two groups stay aligned to the end.

The main score keeps its own layout (<print> system/page breaks) and its
rehearsal marks.  The second score's <print> and rehearsal marks are dropped
(two sets of rehearsal letters are not wanted), and its part ids are renamed
Pn -> Kn so they do not collide with the main score's.

The output path defaults to <main>_Full_Score.musicxml.

    python3 tools/merge_full_score.py MAIN.musicxml EXTRA.musicxml [OUT]
    python3 tools/merge_full_score.py MAIN.musicxml EXTRA.musicxml --insert-rest-in-main 92
"""

import argparse
import copy
import os
import xml.etree.ElementTree as ET


def attr_divisions(measure):
    a = measure.find("attributes")
    if a is not None:
        d = a.find("divisions")
        if d is not None:
            return int(d.text)
    return None


def rename_ids(root, mapping):
    for el in root.iter():
        for key, val in list(el.attrib.items()):
            for old, new in mapping.items():
                if val == old:
                    el.set(key, new)
                elif val.startswith(old + "-"):
                    el.set(key, new + val[len(old):])


def drop_rehearsals(measure):
    for direction in measure.findall("direction"):
        for dt in direction.findall("direction-type"):
            for r in dt.findall("rehearsal"):
                dt.remove(r)
            if len(dt) == 0:
                direction.remove(dt)
        if direction.find("direction-type") is None:
            measure.remove(direction)


def rest_measure(number, divisions):
    m = ET.Element("measure", {"number": str(number)})
    note = ET.SubElement(m, "note")
    ET.SubElement(note, "rest", {"measure": "yes"})
    ET.SubElement(note, "duration").text = str(divisions * 4)
    ET.SubElement(note, "voice").text = "1"
    ET.SubElement(note, "type").text = "whole"
    return m


def build_parts(root, total, insert, clean):
    out = []
    for part in root.findall("part"):
        measures = part.findall("measure")
        divisions = []
        cur = 1
        for m in measures:
            d = attr_divisions(m)
            if d is not None:
                cur = d
            divisions.append(cur)
        new_part = ET.Element("part", {"id": part.get("id")})
        for i in range(1, total + 1):
            src = None
            if insert and i != insert:
                src = i - 1 if i < insert else i - 2
            elif not insert and i - 1 < len(measures):
                src = i - 1
            if src is not None and 0 <= src < len(measures):
                m = copy.deepcopy(measures[src])
                m.set("number", str(i))
                if clean:
                    pr = m.find("print")
                    if pr is not None:
                        m.remove(pr)
                    drop_rehearsals(m)
            else:
                m = rest_measure(i, divisions[min(i, len(divisions)) - 1])
            new_part.append(m)
        out.append(new_part)
    return out


def default_out(main):
    return os.path.splitext(main)[0] + "_Full_Score.musicxml"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("main")
    ap.add_argument("extra")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--insert-rest-in-main", type=int, default=0)
    ap.add_argument("--insert-rest-in-extra", type=int, default=0)
    args = ap.parse_args()

    main_root = ET.parse(args.main).getroot()
    extra_root = ET.parse(args.extra).getroot()

    n_main = len(main_root.findall("part")[0].findall("measure"))
    n_extra = len(extra_root.findall("part")[0].findall("measure"))
    if n_main != n_extra and not (args.insert_rest_in_main or args.insert_rest_in_extra):
        raise SystemExit("measure counts differ (%d vs %d): pass "
                         "--insert-rest-in-main/extra N" % (n_main, n_extra))
    total = max(n_main, n_extra)

    ex_ids = [sp.get("id") for sp in extra_root.find("part-list").findall("score-part")]
    rename_ids(extra_root, {old: "K%d" % (i + 1) for i, old in enumerate(ex_ids)})

    new_root = ET.Element("score-partwise", {"version": main_root.get("version", "4.0")})
    for tag in ("identification", "defaults"):
        el = main_root.find(tag)
        if el is not None:
            new_root.append(copy.deepcopy(el))
    part_list = ET.SubElement(new_root, "part-list")
    for sp in main_root.find("part-list").findall("score-part"):
        part_list.append(copy.deepcopy(sp))
    for sp in extra_root.find("part-list").findall("score-part"):
        part_list.append(copy.deepcopy(sp))

    first = main_root.findall("part")[0].findall("measure")[0]
    for p in build_parts(main_root, total, args.insert_rest_in_main, False):
        p.findall("measure")[0].set("implicit", first.get("implicit", "no"))
        new_root.append(p)
    for p in build_parts(extra_root, total, args.insert_rest_in_extra, True):
        p.findall("measure")[0].set("implicit", first.get("implicit", "no"))
        new_root.append(p)

    ET.indent(new_root, space="  ")
    out = args.out or default_out(args.main)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("<?xml version='1.0' encoding='UTF-8'?>\n")
        fh.write(ET.tostring(new_root, encoding="unicode"))
    print("wrote %s: %d parts, %d measures (main %d, extra %d)"
          % (out, len(new_root.findall("part")), total, n_main, n_extra))


if __name__ == "__main__":
    main()
