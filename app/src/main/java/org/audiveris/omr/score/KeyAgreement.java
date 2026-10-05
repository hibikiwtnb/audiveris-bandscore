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

        for (SystemInfo system : page.getSystems()) {
            boolean systemStart = true;

            for (MeasureStack stack : system.getStacks()) {
                // Votes in top-down order of the staves: key -> staff ids
                final Map<Integer, List<Integer>> votes = new LinkedHashMap<>();

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
                        final int concert;

                        if (key != null && key.getFifths() != null) {
                            concert = key.getFifths() - shift;
                        } else if (systemStart || (inForce == null)) {
                            continue;
                        } else {
                            concert = inForce;
                        }

                        votes.computeIfAbsent(concert, k -> new ArrayList<>()).add(staff.getId());
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

                    if (votes.size() > 1) {
                        final Map<Integer, List<Integer>> others = new LinkedHashMap<>(votes);
                        others.remove(winner);
                        logger.warn("{} m{}: key {} by most staves, staves (key) {} overruled",
                                page.getSheet().getId(), stack.getIdValue(), winner, others);
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

    //---------//
    // isDrums //
    //---------//
    private static boolean isDrums (Part part)
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
     *
     * @param part the part at hand
     * @return the key shift in fifths (e.g. 2 for an instrument in B flat)
     */
    public static int transpositionOf (Part part)
    {
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
