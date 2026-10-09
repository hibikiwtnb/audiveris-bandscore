//------------------------------------------------------------------------------------------------//
//                                                                                                //
//                             P a r e n t h e s i z e d C h o r d s                              //
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
package org.audiveris.omr.sheet.rhythm;

import org.audiveris.omr.constant.Constant;
import org.audiveris.omr.constant.ConstantSet;
import org.audiveris.omr.glyph.Glyph;
import org.audiveris.omr.glyph.GlyphFactory;
import org.audiveris.omr.math.GeoUtil;
import org.audiveris.omr.math.Rational;
import static org.audiveris.omr.math.Rational.ZERO;
import static org.audiveris.omr.run.Orientation.VERTICAL;
import org.audiveris.omr.run.RunTable;
import org.audiveris.omr.run.RunTableFactory;
import org.audiveris.omr.sheet.Picture;
import org.audiveris.omr.sheet.Staff;
import org.audiveris.omr.sheet.SystemInfo;
import org.audiveris.omr.sig.SIGraph;
import org.audiveris.omr.sig.inter.AbstractBeamInter;
import org.audiveris.omr.sig.inter.AbstractChordInter;
import org.audiveris.omr.sig.inter.AbstractFlagInter;
import org.audiveris.omr.sig.inter.AlterInter;
import org.audiveris.omr.sig.inter.ArticulationInter;
import org.audiveris.omr.sig.inter.AugmentationDotInter;
import org.audiveris.omr.sig.inter.Inter;
import org.audiveris.omr.sig.inter.SentenceInter;
import org.audiveris.omr.sig.inter.StemInter;
import org.audiveris.omr.sig.inter.TupletInter;
import org.audiveris.omr.sig.relation.Relation;
import static org.audiveris.omr.util.HorizontalSide.LEFT;
import static org.audiveris.omr.util.HorizontalSide.RIGHT;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import ij.process.Blitter;
import ij.process.ByteProcessor;

import java.awt.Rectangle;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Class <code>ParenthesizedChords</code> handles, in a measure of wrong length, the chords
 * written between a pair of tall parentheses under a later-pass text such as "2x" or "D.S.x".
 * <p>
 * Band scores write the notes played only on a later pass after the normal notes of the same
 * measure, between parentheses as tall as the staff, with "2x" or "D.S.x" above them. Read
 * together, the measure gets too long. When a voice of the measure has a wrong length, the
 * parentheses of each staff are looked for on the staff-free image (those of a text, like
 * "(Synth.)", do not count), and a pair is used only when a later-pass text lies above it.
 * Its chords are used only when every voice they belong to then gets the measure length exactly,
 * or nothing is left in it; otherwise the measure is kept as it is.
 * <p>
 * Under "2x" to "9x" (markLaterPasses), the chords are marked with their pass and kept out of the
 * measure rhythm: they are exported on their own voices, from the measure start, for that pass
 * only (MusicXML time-only), provided they fill the measure exactly.
 * Otherwise (D.S.x, D.C.x, or a later pass that does not fill the measure), they are dropped with
 * their stems, beams, flags, dots, accidentals, articulations and tuplets (dropParenthesized).
 */
public class ParenthesizedChords
{
    //~ Static fields/initializers -----------------------------------------------------------------

    private static final Constants constants = new Constants();

    private static final Logger logger = LoggerFactory.getLogger(ParenthesizedChords.class);

    /** Later-pass texts: "2x", "3X", "D.S.x", "D.C.x" ("1x" is the first pass). */
    private static final Pattern LATER_PASS = Pattern.compile(
            "(?i)(?<![a-z0-9])([2-9]\\s*[x×]|D\\.?\\s*[SC]\\.?\\s*[x×])(?![a-z])");

    /** Maximum number of voices in a later pass. */
    private static final int MAX_PASS_VOICES = 3;

    //~ Instance fields ----------------------------------------------------------------------------

    private final Measure measure;

    private final SystemInfo system;

    private final SIGraph sig;

    //~ Constructors -------------------------------------------------------------------------------

    private ParenthesizedChords (Measure measure)
    {
        this.measure = measure;
        this.system = measure.getPart().getSystem();
        this.sig = system.getSig();
    }

    //~ Methods ------------------------------------------------------------------------------------

    //----------------//
    // crossesDropped //
    //----------------//
    /**
     * Report whether the chord is in a tuplet which has dropped chords too.
     */
    private static boolean crossesDropped (AbstractChordInter chord,
                                           Set<AbstractChordInter> dropped)
    {
        final TupletInter tuplet = chord.getTuplet();

        return (tuplet != null) && tuplet.getChords().stream().anyMatch(dropped::contains);
    }

    //------//
    // drop //
    //------//
    private void drop (Set<AbstractChordInter> dropped)
    {
        final Set<Inter> victims = new LinkedHashSet<>();

        for (AbstractChordInter chord : dropped) {
            victims.add(chord);
            victims.addAll(chord.getMembers());

            final StemInter stem = chord.getStem();

            if (stem != null) {
                victims.add(stem);
            }
        }

        // What hangs on the dropped notes and stems
        for (Inter inter : new ArrayList<>(victims)) {
            for (Relation rel : sig.edgesOf(inter)) {
                final Inter other = sig.getOppositeInter(inter, rel);

                if ((other instanceof AugmentationDotInter) || (other instanceof AbstractFlagInter)
                        || (other instanceof AlterInter) || (other instanceof ArticulationInter)) {
                    victims.add(other);
                }
            }
        }

        // Beams only when all their chords go, tuplets always
        for (AbstractChordInter chord : dropped) {
            for (AbstractBeamInter beam : chord.getBeams()) {
                if (dropped.containsAll(beam.getChords())) {
                    victims.add(beam);
                }
            }

            // A tuplet across a parenthesis was a wrong guess
            final TupletInter tuplet = chord.getTuplet();

            if (tuplet != null) {
                victims.add(tuplet);
            }
        }

        final MeasureStack stack = measure.getStack();

        for (Inter inter : victims) {
            if (inter instanceof TupletInter) {
                measure.removeInter(inter);
                stack.removeInter(inter);
            }

            inter.remove();
        }
    }

    //-----------------//
    // findParentheses //
    //-----------------//
    /**
     * Find the tall parentheses on a staff, within the measure, out of the text boxes.
     *
     * @return the parentheses, as x of their center and side (-1 for '(', +1 for ')'),
     *         sorted by x
     */
    private List<int[]> findParentheses (Staff staff,
                                         List<Rectangle> textBoxes)
    {
        final List<int[]> found = new ArrayList<>();
        final ByteProcessor source = system.getSheet().getPicture().getSource(
                Picture.SourceKey.NO_STAFF);

        if (source == null) {
            return found;
        }

        final int il = staff.getSpecificInterline();
        final int left = measure.getAbscissa(LEFT, staff);
        final int right = measure.getAbscissa(RIGHT, staff);
        final int top = staff.getFirstLine().yAt(left) - (2 * il);
        final int bottom = staff.getLastLine().yAt(left) + (2 * il);
        final Rectangle rect = new Rectangle(left, top, right - left + 1, bottom - top + 1)
                .intersection(new Rectangle(0, 0, source.getWidth(), source.getHeight()));

        if (rect.isEmpty()) {
            return found;
        }

        final ByteProcessor buf = new ByteProcessor(rect.width, rect.height);
        buf.copyBits(source, -rect.x, -rect.y, Blitter.COPY);

        final RunTable runTable = new RunTableFactory(VERTICAL).createTable(buf);
        final List<Glyph> glyphs = GlyphFactory.buildGlyphs(runTable, rect.getLocation());

        // Expected height: the staff height (one-line staff: about 2 interlines)
        final double staffHeight = staff.isOneLineStaff() ? 2.0 * il
                : staff.getLastLine().yAt(left) - staff.getFirstLine().yAt(left);
        final double minHeight = staffHeight * constants.minHeightRatio.getValue();
        final double maxHeight = staffHeight + (constants.maxHeightMargin.getValue() * il);
        final int midY = staff.getMidLine().yAt(left);

        GLYPHS:
        for (Glyph glyph : glyphs) {
            final Rectangle b = glyph.getBounds();

            if ((b.height < minHeight) || (b.height > maxHeight)) {
                continue;
            }

            if ((b.width > (constants.maxWidth.getValue() * il))
                    || (glyph.getWeight() > (b.height * constants.maxThickness.getValue() * il))) {
                continue;
            }

            if ((b.y > midY) || ((b.y + b.height) < midY)) {
                continue; // Not across the staff middle
            }

            for (Rectangle box : textBoxes) {
                if (box.intersects(b)) {
                    continue GLYPHS; // Parenthesis of a text
                }
            }

            final int side = bowSide(glyph, il);

            if (side != 0) {
                found.add(new int[]{b.x + (b.width / 2), side});
            }
        }

        found.sort(Comparator.comparingInt(p -> p[0]));

        return found;
    }

    //------//
    // fits //
    //------//
    /**
     * Report whether, without the provided chords, every voice they belong to gets the
     * expected measure length exactly (or gets empty).
     * <p>
     * The remaining chords of a voice are summed up in sequence (a voice of the measure has no
     * gap).
     */
    private boolean fits (Set<AbstractChordInter> dropped,
                          Rational expected)
    {
        boolean touched = false;

        for (Voice voice : measure.getVoices()) {
            final List<AbstractChordInter> chords = voice.getChords();

            if (chords.stream().noneMatch(dropped::contains)) {
                continue;
            }

            touched = true;

            for (AbstractChordInter ch : chords) {
                if (ch.getDuration() == null) {
                    return false;
                }
            }

            // Remaining chords, in sequence, a tuplet across a parenthesis being dropped
            Rational end = ZERO;

            for (AbstractChordInter ch : chords) {
                if (!dropped.contains(ch)) {
                    end = end.plus(
                            crossesDropped(ch, dropped) ? ch.getDurationSansTuplet()
                                    : ch.getDuration());
                }
            }

            if (end.equals(ZERO)) {
                end = null; // Nothing left
            }

            if ((end != null) && !end.equals(expected)) {
                return false;
            }
        }

        return touched;
    }

    //----------------//
    // laterPassBoxes //
    //----------------//
    /**
     * Report the boxes of the later-pass texts just above the staff.
     *
     * @return the pass of each text box (0 for D.S.x or D.C.x)
     */
    private Map<Rectangle, Integer> laterPassBoxes (Staff staff,
                                                    List<SentenceInter> sentences)
    {
        final Map<Rectangle, Integer> boxes = new HashMap<>();
        final int il = staff.getSpecificInterline();

        for (SentenceInter sentence : sentences) {
            final int pass = passOf(sentence.getValue());

            if (pass < 0) {
                continue;
            }

            final Rectangle b = sentence.getBounds();
            final double x = b.getCenterX();
            final double bottom = b.y + b.height;

            // Staff just below the text
            Staff below = null;
            double best = Double.MAX_VALUE;

            for (Staff s : system.getStaves()) {
                final double dy = s.getFirstLine().yAt(x) - bottom;

                if ((dy > -il) && (dy < best)) {
                    best = dy;
                    below = s;
                }
            }

            if ((below == staff) && (best <= (constants.maxTextGap.getValue() * il))) {
                boxes.put(b, pass);
            }
        }

        return boxes;
    }

    //---------//
    // process //
    //---------//
    private boolean process (Rational expected)
    {
        final List<SentenceInter> sentences = new ArrayList<>();
        final List<Rectangle> textBoxes = new ArrayList<>();

        for (Inter inter : sig.inters(SentenceInter.class)) {
            sentences.add((SentenceInter) inter);
            textBoxes.add(inter.getBounds());
        }

        final List<AbstractChordInter> chords = new ArrayList<>();
        chords.addAll(measure.getHeadChords());
        chords.addAll(measure.getRestChords());
        boolean done = false;

        for (Staff staff : measure.getPart().getStaves()) {
            if (staff.isTablature()) {
                continue;
            }

            final Map<Rectangle, Integer> texts = laterPassBoxes(staff, sentences);

            if (texts.isEmpty()) {
                continue;
            }

            final List<int[]> parens = findParentheses(staff, textBoxes);
            final int margin = (int) Math.rint(
                    constants.maxTextShift.getValue() * staff.getSpecificInterline());
            Integer open = null;

            for (int[] paren : parens) {
                if (paren[1] < 0) {
                    open = paren[0];
                    continue;
                }

                if (open == null) {
                    continue;
                }

                final int xOpen = open;
                final int xClose = paren[0];
                open = null;

                // A later-pass text above the pair
                Integer pass = null;

                for (Map.Entry<Rectangle, Integer> entry : texts.entrySet()) {
                    final Rectangle t = entry.getKey();

                    if ((t.x <= xClose) && ((t.x + t.width) >= (xOpen - margin))) {
                        pass = entry.getValue();
                        break;
                    }
                }

                if (pass == null) {
                    continue;
                }

                final Set<AbstractChordInter> inside = new LinkedHashSet<>();

                for (AbstractChordInter chord : chords) {
                    final int x = chord.getCenter().x;

                    if (!chord.isRemoved() && chord.getStaves().contains(staff) && (x > xOpen)
                            && (x < xClose)) {
                        inside.add(chord);
                    }
                }

                if (inside.isEmpty()) {
                    continue;
                }

                if (fits(inside, expected)) {
                    if ((pass >= 2) && constants.markLaterPasses.isSet()
                            && (laterPassVoices(inside, expected) != null)) {
                        mark(inside, pass);
                        done = true;
                        logger.info(
                                "{} {} x {}-{}: {} parenthesized chords played on pass {} only",
                                measure,
                                staff,
                                xOpen,
                                xClose,
                                inside.size(),
                                pass);
                    } else if (constants.dropParenthesized.isSet()) {
                        drop(inside);
                        done = true;
                        logger.info(
                                "{} {} x {}-{}: {} parenthesized chords of a later pass dropped",
                                measure,
                                staff,
                                xOpen,
                                xClose,
                                inside.size());
                    } else {
                        logger.info(
                                "{} {} x {}-{}: parenthesized chords kept, not a full pass",
                                measure,
                                staff,
                                xOpen,
                                xClose);
                    }
                } else {
                    logger.info(
                            "{} {} x {}-{}: parenthesized chords kept, the measure would not fit",
                            measure,
                            staff,
                            xOpen,
                            xClose);
                }
            }
        }

        return done;
    }

    //------//
    // mark //
    //------//
    /**
     * Mark the chords as played on the provided pass only, out of the measure rhythm.
     * A tuplet across a parenthesis was a wrong guess.
     */
    private void mark (Set<AbstractChordInter> chords,
                       int pass)
    {
        final MeasureStack stack = measure.getStack();

        for (AbstractChordInter chord : chords) {
            chord.setPass(pass);

            final TupletInter tuplet = chord.getTuplet();

            if ((tuplet != null) && !chords.containsAll(tuplet.getChords())) {
                measure.removeInter(tuplet);
                stack.removeInter(tuplet);
                tuplet.remove();
            }
        }
    }

    //--------//
    // passOf //
    //--------//
    /**
     * Report the pass of a later-pass text.
     *
     * @return the pass (2 for "2x"), 0 for "D.S.x" or "D.C.x", -1 for no later-pass text
     */
    private static int passOf (String value)
    {
        if (value == null) {
            return -1;
        }

        final Matcher matcher = LATER_PASS.matcher(value);

        if (!matcher.find()) {
            return -1;
        }

        final char c = matcher.group(1).charAt(0);

        return Character.isDigit(c) ? (c - '0') : 0;
    }

    //------------------//
    // isLaterPassText //
    //------------------//
    /**
     * Report whether the text is a later-pass text, like "2x" or "D.S.x".
     *
     * @param value the text value
     * @return true if so
     */
    public static boolean isLaterPassText (String value)
    {
        return passOf(value) >= 0;
    }

    //-----------------//
    // laterPassVoices //
    //-----------------//
    /**
     * Lay out the chords of a later pass, written in sequence from the measure start, into
     * voices.
     * <p>
     * Chords whose heads overlap in abscissa start together; the shortest of them gives the
     * start of the next ones. Each chord goes to the first voice free at its start, from top to
     * bottom.
     *
     * @param chords   the chords of a later pass on a staff
     * @param expected the measure duration, or null for no check
     * @return the voices, each as its chords with their time offsets in sequence, or null if the
     *         chords do not fill the expected duration exactly
     */
    public static List<Map<AbstractChordInter, Rational>> laterPassVoices (
            Collection<AbstractChordInter> chords,
            Rational expected)
    {
        final List<AbstractChordInter> sorted = new ArrayList<>(chords);
        sorted.sort(Comparator.comparingInt(ch -> headsBox(ch).x));

        // Columns of chords starting together
        final List<List<AbstractChordInter>> columns = new ArrayList<>();
        Rectangle columnBox = null;

        for (AbstractChordInter chord : sorted) {
            final Rectangle box = headsBox(chord);

            if ((columnBox == null) || (GeoUtil.xOverlap(columnBox, box) <= 0)) {
                columns.add(new ArrayList<>());
                columnBox = new Rectangle(box);
            } else {
                columnBox.add(box);
            }

            columns.get(columns.size() - 1).add(chord);
        }

        final List<Map<AbstractChordInter, Rational>> voices = new ArrayList<>();
        final List<Rational> ends = new ArrayList<>();
        Rational offset = ZERO;

        for (List<AbstractChordInter> column : columns) {
            column.sort(Comparator.comparingInt(ch -> headsBox(ch).y));
            Rational shortest = null;

            for (AbstractChordInter chord : column) {
                final Rational dur = chord.isMeasureRest() ? null : chord.getDuration();

                if (dur == null) {
                    return null;
                }

                if ((shortest == null) || (dur.compareTo(shortest) < 0)) {
                    shortest = dur;
                }

                int v = 0;

                while ((v < ends.size()) && (ends.get(v).compareTo(offset) > 0)) {
                    v++;
                }

                if (v == ends.size()) {
                    if (v == MAX_PASS_VOICES) {
                        return null;
                    }

                    voices.add(new LinkedHashMap<>());
                    ends.add(ZERO);
                }

                voices.get(v).put(chord, offset);
                ends.set(v, offset.plus(dur));
            }

            offset = offset.plus(shortest);
        }

        if (expected != null) {
            if (!offset.equals(expected)) {
                return null;
            }

            for (Rational end : ends) {
                if (end.compareTo(expected) > 0) {
                    return null;
                }
            }
        }

        return voices;
    }

    //----------//
    // headsBox //
    //----------//
    private static Rectangle headsBox (AbstractChordInter chord)
    {
        Rectangle box = null;

        for (Inter note : chord.getMembers()) {
            if (box == null) {
                box = note.getBounds();
            } else {
                box.add(note.getBounds());
            }
        }

        return (box != null) ? box : chord.getBounds();
    }

    //---------//
    // bowSide //
    //---------//
    /**
     * Report the side of the bow of a thin tall glyph: -1 for '(' (middle on the left of
     * the ends), +1 for ')', 0 for neither.
     */
    private static int bowSide (Glyph glyph,
                                int interline)
    {
        final RunTable table = glyph.getRunTable();
        final int w = table.getWidth();
        final int h = table.getHeight();
        final int q = h / 6;
        final double[] sum = new double[3];
        final int[] count = new int[3];

        for (int y = 0; y < h; y++) {
            // Bands: top sixth, central third, bottom sixth
            final int band = (y < q) ? 0 : ((y >= (h - q)) ? 2 : 1);

            if ((band == 1) && ((y < (h / 3)) || (y >= (h - h / 3)))) {
                continue;
            }

            for (int x = 0; x < w; x++) {
                if (table.get(x, y) == 0) { // Foreground
                    sum[band] += x;
                    count[band]++;
                }
            }
        }

        if ((count[0] == 0) || (count[1] == 0) || (count[2] == 0)) {
            return 0;
        }

        final double top = sum[0] / count[0];
        final double mid = sum[1] / count[1];
        final double bot = sum[2] / count[2];

        if (Math.abs(top - bot) > (constants.maxEndShift.getValue() * interline)) {
            return 0;
        }

        final double bow = mid - ((top + bot) / 2);
        final double minBow = constants.minBow.getValue() * interline;

        return (bow <= -minBow) ? -1 : ((bow >= minBow) ? 1 : 0);
    }

    //------------------//
    // removeLaterPasses //
    //------------------//
    /**
     * In a measure with a voice of wrong length, take the parenthesized chords of a later pass
     * out of the measure rhythm (marked with their pass, or dropped) when the measure then fits,
     * if so set.
     *
     * @param measure the measure, with its rhythm processed
     * @return true if some chords were marked or dropped (rhythm to be processed again)
     */
    public static boolean removeLaterPasses (Measure measure)
    {
        if (!constants.markLaterPasses.isSet() && !constants.dropParenthesized.isSet()) {
            return false;
        }

        final MeasureStack stack = measure.getStack();
        final Rational expected = stack.getExpectedDuration();

        if ((expected == null) || stack.isImplicit()) {
            return false;
        }

        // Only a measure with a voice of wrong length
        boolean wrong = false;

        for (Voice voice : measure.getVoices()) {
            if (voice.isMeasureRest()) {
                continue;
            }

            Rational end = ZERO;

            for (AbstractChordInter ch : voice.getChords()) {
                if ((ch.getTimeOffset() == null) || (ch.getDuration() == null)) {
                    end = null;
                    break;
                }

                final Rational chEnd = ch.getTimeOffset().plus(ch.getDuration());

                if (chEnd.compareTo(end) > 0) {
                    end = chEnd;
                }
            }

            if ((end == null) || !end.equals(expected)) {
                wrong = true;
                break;
            }
        }

        return wrong && new ParenthesizedChords(measure).process(expected);
    }

    //~ Inner Classes ------------------------------------------------------------------------------

    //-----------//
    // Constants //
    //-----------//
    private static class Constants
            extends ConstantSet
    {
        private final Constant.Boolean markLaterPasses = new Constant.Boolean(
                true,
                "Should the parenthesized chords of a later pass (2x) be exported for that pass"
                        + " only (MusicXML time-only), in a measure of wrong length?");

        private final Constant.Boolean dropParenthesized = new Constant.Boolean(
                false,
                "Should the parenthesized chords of a later pass (2x, D.S.x) be dropped"
                        + " from a measure of wrong length?");

        private final Constant.Ratio minHeightRatio = new Constant.Ratio(
                0.9,
                "Minimum parenthesis height, as ratio of staff height");

        private final Constant.Ratio maxHeightMargin = new Constant.Ratio(
                2.5,
                "Maximum parenthesis height above staff height, in interlines");

        private final Constant.Ratio maxWidth = new Constant.Ratio(
                0.8,
                "Maximum parenthesis width, in interlines");

        private final Constant.Ratio maxThickness = new Constant.Ratio(
                0.35,
                "Maximum mean parenthesis thickness (weight / height), in interlines");

        private final Constant.Ratio minBow = new Constant.Ratio(
                0.12,
                "Minimum parenthesis bow (middle vs ends), in interlines");

        private final Constant.Ratio maxEndShift = new Constant.Ratio(
                0.4,
                "Maximum abscissa shift between parenthesis ends, in interlines");

        private final Constant.Ratio maxTextGap = new Constant.Ratio(
                4.0,
                "Maximum gap between a later-pass text and the staff below, in interlines");

        private final Constant.Ratio maxTextShift = new Constant.Ratio(
                4.0,
                "Maximum distance of a later-pass text left of the opening parenthesis,"
                        + " in interlines");
    }
}
