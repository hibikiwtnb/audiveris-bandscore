//------------------------------------------------------------------------------------------------//
//                                                                                                //
//                                    K e y A g r e e m e n t                                     //
//                                                                                                //
//------------------------------------------------------------------------------------------------//
// <editor-fold defaultstate="collapsed" desc="hdr">
//
//  Copyright © Audiveris 2026. All rights reserved.
//
//  This program is free software: you can redistribute it and/or modify it under the terms of the
//  GNU Affero General Public License as published by the Free Software Foundation, either version
//  3 of the License, or (at your option) any later version.
//
//  This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
//  without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
//  See the GNU Affero General Public License for more details.
//
//  You should have received a copy of the GNU Affero General Public License along with this
//  program.  If not, see <http://www.gnu.org/licenses/>.
//------------------------------------------------------------------------------------------------//
// </editor-fold>
package org.audiveris.omr.score;

import org.audiveris.omr.sheet.Part;
import org.audiveris.omr.sheet.Staff;
import org.audiveris.omr.sheet.SystemInfo;
import org.audiveris.omr.sheet.rhythm.Measure;
import org.audiveris.omr.sheet.rhythm.MeasureStack;
import org.audiveris.omr.sig.inter.KeyInter;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Class <code>KeyAgreement</code> gives, for each measure stack of a page, the one concert key
 * shared by all pitched staves: apart from transposing instruments, a measure cannot have
 * different keys.
 * <p>
 * Each pitched staff (not drum, tablature or one-line staff) votes in each measure stack: the key
 * signature recognized there if any. Without one, a staff does not vote at system start (key
 * signatures are often missed there, even on most staves), and votes the key in force elsewhere
 * (so that a key change read on a few staves only is overruled). A transposing instrument votes
 * its key brought back to concert pitch (see {@link #transpositionOf}).
 * <p>
 * The most voted key wins; on a tie, the key in force if it is among the tied ones, otherwise the
 * key of the topmost staff among them. With no vote, the key in force goes on (none yet: C).
 * The staves voting otherwise are reported (WARN): a key signature missed on some staves no
 * longer exports their notes in C.
 * <p>
 * A key change inside a system is often read on a few staves only (naturals that cancel the
 * former key are poorly recognized), and would be overruled by the silent staves until the next
 * system. Hence, when the key in force wins inside a system while some staff reads there the
 * very key that the next system clearly starts with, this key is taken from that measure on.
 * This does not apply to a courtesy key signature printed at the end of the system (last
 * measure, key in its right half): the change is for the next system.
 * <p>
 * A guitar with a capo (parts hint ":capoN") is written N semitones below concert pitch, a guitar
 * or bass tuned down (":downN") N semitones above: it votes and is exported like a transposing
 * instrument.
 */
public class KeyAgreement
{
    //~ Static fields/initializers -----------------------------------------------------------------

    private static final Logger logger = LoggerFactory.getLogger(KeyAgreement.class);

    /** Explicit key of an instrument in its name, e.g. "Trumpet in C", "Cl. in A". */
    private static final Pattern IN_KEY = Pattern.compile(
            "(?i)\\bin\\s*([A-G])\\s*(b|\u266d|#|\u266f)?(?![a-z])");

    /** Instruments in B flat (lower case names and abbreviations). */
    private static final Pattern IN_B_FLAT = Pattern.compile(
            "trumpet|cornet|flugel|clarinet|soprano sax|tenor sax"
                    + "|^(tp|trp|tpt|cl|b\\. ?cl|s\\. ?sax|sop\\. ?sax|t\\. ?sax|ten\\. ?sax)\\b");

    /** Instruments in E flat. */
    private static final Pattern IN_E_FLAT = Pattern.compile(
            "alto sax|baritone sax|bari sax|^(a\\. ?sax|b\\. ?sax|bar\\. ?sax|bari\\. ?sax)\\b");

    /** Instruments in F. */
    private static final Pattern IN_F = Pattern.compile(
            "^(french |english )?horns?\\b|cor anglais|^(hr|hn|e\\. ?h)\\b");

    /**
     * Diatonic steps of the interval of N semitones (index N, 1..11) between what a guitar with
     * a capo on fret N writes and what it sounds: minor second, major second, minor third...
     */
    private static final int[] CAPO_STEPS = {0, 1, 1, 2, 2, 3, 3, 4, 5, 5, 6, 6};

    /**
     * Diatonic steps of the interval of N semitones (index N, 1..11) between what an instrument
     * tuned down N semitones writes and what it sounds: augmented unison (A written for A flat),
     * major second, minor third...
     */
    private static final int[] DOWN_STEPS = {0, 0, 1, 2, 2, 3, 3, 4, 5, 5, 6, 6};

    //~ Instance fields ----------------------------------------------------------------------------

    /** Concert key (fifths) of each measure stack. */
    private final Map<MeasureStack, Integer> keys = new HashMap<>();

    //~ Constructors -------------------------------------------------------------------------------

    /**
     * Vote the concert key of each measure stack of the page.
     *
     * @param page the page at hand
     */
    public KeyAgreement (Page page)
    {
        Integer inForce = null;
        final List<SystemInfo> systems = page.getSystems();

        for (int index = 0; index < systems.size(); index++) {
            final SystemInfo system = systems.get(index);
            final List<MeasureStack> stacks = system.getStacks();

            // The key the next system clearly starts with, if any
            final Integer nextStart = (index + 1 < systems.size()) ? startKeyOf(
                    systems.get(index + 1)) : null;
            boolean systemStart = true;

            for (MeasureStack stack : stacks) {
                // Votes in top-down order of the staves: key -> staff ids
                final Map<Integer, List<Integer>> votes = new LinkedHashMap<>();

                // Keys actually read in this stack: key -> key signatures
                final Map<Integer, List<KeyInter>> read = new LinkedHashMap<>();

                for (Part part : system.getParts()) {
                    if (isDrums(part)) {
                        continue;
                    }

                    final Measure measure = stack.getMeasureAt(part);

                    if (measure == null) {
                        continue;
                    }

                    final int shift = transpositionOf(part);

                    for (Staff staff : part.getStaves()) {
                        if (staff.isTablature() || staff.isOneLineStaff() || staff.isDrum()) {
                            continue;
                        }

                        final KeyInter key = measure.getKey(staff);

                        if (key != null && key.getFifths() != null) {
                            final int concert = enharmonic(key.getFifths() - shift);
                            read.computeIfAbsent(concert, k -> new ArrayList<>()).add(key);
                            votes.computeIfAbsent(concert, k -> new ArrayList<>()).add(staff.getId());
                        }
                    }
                }

                if (!votes.isEmpty()) {
                    final int max = votes.values().stream().mapToInt(List::size).max().getAsInt();
                    Integer winner = null;

                    for (Map.Entry<Integer, List<Integer>> entry : votes.entrySet()) {
                        if (entry.getValue().size() == max) {
                            if (entry.getKey().equals(inForce)) {
                                winner = inForce;

                                break;
                            }

                            if (winner == null) {
                                winner = entry.getKey();
                            }
                        }
                    }

                    // A courtesy key at the end of a system is for the next system
                    final boolean last = stack == stacks.get(stacks.size() - 1);
                    if (last && (winner != null) && read.containsKey(winner) && isCourtesy(
                            stack, read.get(winner))) {
                        logger.info("{} m{}: key {} at system end is for the next system",
                                page.getSheet().getId(), stack.getIdValue(), winner);
                        winner = inForce;
                    } else if (!systemStart && (inForce != null) && (max == 1)
                            && !winner.equals(inForce)
                            && !winner.equals(nextStart)) {
                        // A lone unconfirmed change inside a system does not overturn inForce
                        winner = inForce;
                    }

                    if (votes.size() > 1) {
                        final Map<Integer, List<Integer>> others = new LinkedHashMap<>(votes);
                        others.remove(winner);
                        others.values().forEach(ids -> ids.removeIf(id -> {
                            for (Part p : system.getParts()) {
                                final Measure m = stack.getMeasureAt(p);
                                if (m != null) {
                                    for (Staff s : p.getStaves()) {
                                        if (s.getId() == id) {
                                            final KeyInter k = m.getKey(s);
                                            return (k != null) && k.isFromTemplate();
                                        }
                                    }
                                }
                            }
                            return false;
                        }));
                        others.entrySet().removeIf(e -> e.getValue().isEmpty());

                        if (!others.isEmpty()) {
                            logger.warn("{} m{}: key {} by most staves, staves (key) {} overruled",
                                    page.getSheet().getId(), stack.getIdValue(), winner, others);
                        }
                    }

                    inForce = winner;
                }

                keys.put(stack, (inForce != null) ? inForce : 0);
                systemStart = false;
            }
        }
    }

    //~ Methods ------------------------------------------------------------------------------------

    //---------------//
    // getConcertKey //
    //---------------//
    /**
     * Report the concert key of a measure stack.
     *
     * @param stack the measure stack
     * @return the key (fifths), null if the stack is not in the page
     */
    public Integer getConcertKey (MeasureStack stack)
    {
        return keys.get(stack);
    }

    //~ Static Methods -----------------------------------------------------------------------------

    //--------//
    // capoOf //
    //--------//
    /**
     * Report the capo fret of a part, as given by the parts hint (":capoN"), or minus the
     * semitones it is tuned down (":downN").
     *
     * @param part the part at hand
     * @return the capo fret (1..11), minus the semitones tuned down (-11..-1), or null if none
     */
    public static Integer capoOf (Part part)
    {
        final Map<String, Integer> capos = PartCollation.getHintedCapos();

        if (capos.isEmpty()) {
            return null;
        }

        final LogicalPart logical = part.getLogicalPart();
        final String name = (logical != null) ? logical.getName() : part.getName();

        return (name != null) ? capos.get(name) : null;
    }

    //------------//
    // enharmonic //
    //------------//
    /**
     * Bring a key brought to or from concert pitch back among the printable keys (7 flats to
     * 7 sharps), by its enharmonic equivalent: a guitar tuned down a semitone writes B flat
     * (2 flats) for A (3 sharps), 9 flats once taken back, 3 sharps here.
     *
     * @param fifths the key, perhaps beyond 7 flats or sharps
     * @return the same key, as printed
     */
    public static int enharmonic (int fifths)
    {
        int result = fifths;

        while (result > 7) {
            result -= 12;
        }

        while (result < -7) {
            result += 12;
        }

        return result;
    }

    //------------//
    // isCourtesy //
    //------------//
    /**
     * Report whether all these key signatures stand in the right half of the stack: at the
     * end of a system, such a key announces the key of the next system.
     */
    private static boolean isCourtesy (MeasureStack stack,
                                       List<KeyInter> keys)
    {
        final double middle = (stack.getLeft() + stack.getRight()) / 2.0;

        for (KeyInter key : keys) {
            if (key.getCenter().x <= middle) {
                return false;
            }
        }

        return true;
    }

    //------------//
    // startKeyOf //
    //------------//
    /**
     * Report the concert key most read in the first measure stack of a system.
     *
     * @return the key (fifths), null if no key is read there or no single key is read most
     */
    private static Integer startKeyOf (SystemInfo system)
    {
        final List<MeasureStack> stacks = system.getStacks();

        if (stacks.isEmpty()) {
            return null;
        }

        final MeasureStack stack = stacks.get(0);
        final Map<Integer, Integer> counts = new LinkedHashMap<>();

        for (Part part : system.getParts()) {
            if (isDrums(part)) {
                continue;
            }

            final Measure measure = stack.getMeasureAt(part);

            if (measure == null) {
                continue;
            }

            final int shift = transpositionOf(part);

            for (Staff staff : part.getStaves()) {
                if (staff.isTablature() || staff.isOneLineStaff() || staff.isDrum()) {
                    continue;
                }

                final KeyInter key = measure.getKey(staff);

                if ((key != null) && (key.getFifths() != null)) {
                    counts.merge(enharmonic(key.getFifths() - shift), 1, Integer::sum);
                }
            }
        }

        Integer best = null;
        int bestCount = 0;
        boolean tie = false;

        for (Map.Entry<Integer, Integer> entry : counts.entrySet()) {
            if (entry.getValue() > bestCount) {
                best = entry.getKey();
                bestCount = entry.getValue();
                tie = false;
            } else if (entry.getValue() == bestCount) {
                tie = true;
            }
        }

        return tie ? null : best;
    }

    //---------//
    // isDrums //
    //---------//
    public static boolean isDrums (Part part)
    {
        if (part.isDrumPart()) {
            return true;
        }

        final LogicalPart logical = part.getLogicalPart();
        final String name = (logical != null) ? logical.getName() : null;

        return (name != null) && PartCollation.getHintedDrumNames().contains(name);
    }

    //-----------------//
    // transpositionOf //
    //-----------------//
    /**
     * Report how many fifths the key of a part is above the concert key, from its names.
     * <p>
     * A key in the name ("Trumpet in C", "Cl. in A") is taken as is; otherwise instruments in
     * B flat (trumpet, cornet, flugelhorn, clarinet, soprano and tenor saxophones), in E flat
     * (alto and baritone saxophones) and in F (horn, english horn, named first) are known by name or usual
     * abbreviation. Any other part is at concert pitch. Octave transpositions (guitar, bass,
     * piccolo...) do not change the key.
     * <p>
     * A part hinted with a capo (":capoN") comes first: written N semitones below concert
     * pitch, e.g. capo 1 writes G (1 sharp) for A flat (4 flats), 5 fifths above. So does a
     * part tuned down (":downN"), written N semitones above concert pitch, e.g. down 1 writes
     * A (3 sharps) for A flat, 7 fifths above.
     *
     * @param part the part at hand
     * @return the key shift in fifths (e.g. 2 for an instrument in B flat)
     */
    public static int transpositionOf (Part part)
    {
        final Integer capo = capoOf(part);

        if (capo != null) {
            return (capo > 0) ? (12 * CAPO_STEPS[capo]) - (7 * capo)
                    : (-7 * capo) - (12 * DOWN_STEPS[-capo]);
        }

        final LogicalPart logical = part.getLogicalPart();
        final List<String> names = new ArrayList<>();

        if (logical != null) {
            names.add(logical.getName());
            names.add(logical.getAbbreviation());
        } else {
            names.add(part.getName());
        }

        for (String name : names) {
            if (name == null) {
                continue;
            }

            final Matcher matcher = IN_KEY.matcher(name);

            if (matcher.find()) {
                final int letter = "FCGDAEB".indexOf(matcher.group(1).toUpperCase(Locale.ROOT))
                        - 1;
                final String acc = matcher.group(2);
                final int alter = (acc == null) ? 0
                        : (acc.equals("#") || acc.equals("\u266f")) ? 7 : -7;

                return -(letter + alter);
            }
        }

        for (String name : names) {
            if (name == null) {
                continue;
            }

            final String lower = name.toLowerCase(Locale.ROOT).trim();

            if (IN_B_FLAT.matcher(lower).find()) {
                return 2;
            }

            if (IN_E_FLAT.matcher(lower).find()) {
                return 3;
            }

            if (IN_F.matcher(lower).find()) {
                return 1;
            }
        }

        return 0;
    }
}
