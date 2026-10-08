//------------------------------------------------------------------------------------------------//
//                                                                                                //
//                                    K e y T e m p l a t e s                                     //
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
package org.audiveris.omr.sheet.key;

import org.audiveris.omr.constant.Constant;
import org.audiveris.omr.constant.ConstantSet;
import org.audiveris.omr.glyph.Shape;
import org.audiveris.omr.sheet.Picture;
import org.audiveris.omr.sheet.Staff;
import org.audiveris.omr.sheet.SystemInfo;
import org.audiveris.omr.sheet.header.StaffHeader;
import org.audiveris.omr.sheet.note.CrossTemplate;
import org.audiveris.omr.sheet.note.NoteHeadsBuilder;
import org.audiveris.omr.sig.SIGraph;
import org.audiveris.omr.sig.inter.ClefInter.ClefKind;
import org.audiveris.omr.sig.inter.Inter;
import org.audiveris.omr.sig.inter.KeyAlterInter;
import org.audiveris.omr.sig.inter.KeyInter;
import org.audiveris.omr.sig.relation.Containment;
import org.audiveris.omr.sig.relation.KeyAltersRelation;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import ij.process.ByteProcessor;

import java.awt.Rectangle;
import java.awt.image.BufferedImage;
import java.io.File;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import javax.imageio.ImageIO;

/**
 * Class <code>KeyTemplates</code> reads the key signature at the start of each staff of a
 * system with the book's sharp and flat templates (<code>key_sharp.png</code>,
 * <code>key_flat.png</code> in the folder of {@link NoteHeadsBuilder#getTemplateDir()}),
 * instead of counting the symbols cut out of the binary image.
 * <p>
 * The items of a key signature stand at fixed places, the same in the whole book: the n-th
 * one at a fixed distance right of the clef (gap + n * spacing, in interlines of the staff), at
 * the pitch of the clef table ({@link KeyInter#SHARP_PITCHES_MAP},
 * {@link KeyInter#FLAT_PITCHES_MAP}). These distances are measured once per book and kept in
 * <code>key_layout.txt</code> next to the templates (see {@link Layout}).
 * <p>
 * The 7 places of the sharps and the 7 places of the flats are all looked at, each in a small
 * window: best correlation with the template (gray image, staff lines erased as for the drum
 * templates) and ink (mean darkness in the template box). The first place is taken from the
 * clef, each next one from the previous item when it was seen (key items are evenly spaced; an
 * accidental right after the key stands further away). A place shows an item (+1) when it
 * matches the template well, no item (-1) when it is blank or matches badly, and leans one way
 * or the other in between. The key is then the one, among the 15 possible (no key, 1 to 7
 * sharps, 1 to 7 flats), that agrees best with all the places at once: items at its first n
 * places, none after. An item that matched a bit low between two good ones is thus counted,
 * and a head or a time signature further right does not add items.
 * <p>
 * Cut-out symbols were miscounted both ways: a flat whose stem is broken by the staff lines was
 * lost (4 flats read as 2), an accidental or a head next to the key was taken in (4 flats read
 * as 6). A template matched at a known place does neither.
 * <p>
 * When the reading differs from the key found by the {@link KeyColumn}, the latter is replaced.
 * Nothing is done for a book without these templates.
 */
public class KeyTemplates
{
    //~ Static fields/initializers -----------------------------------------------------------------

    private static final Constants constants = new Constants();

    private static final Logger logger = LoggerFactory.getLogger(KeyTemplates.class);

    /** Staff interline of the template images. */
    private static final int INTERLINE = CrossTemplate.INTERLINE;

    /** Loaded templates and layout per folder (no templates: empty). */
    private static final Map<String, Book> loaded = new HashMap<>();

    //~ Constructors -------------------------------------------------------------------------------

    private KeyTemplates ()
    {
    }

    //~ Static Methods -----------------------------------------------------------------------------

    //---------//
    // loaded  //
    //---------//
    private static synchronized Book getLoaded (String dir)
    {
        if ((dir == null) || dir.isBlank() || !new File(dir).isDirectory()) {
            return null;
        }

        return loaded.computeIfAbsent(dir, d -> {
            final Template sharp = Template.load(new File(d, "key_sharp.png"));
            final Template flat = Template.load(new File(d, "key_flat.png"));

            if ((sharp == null) || (flat == null)) {
                logger.info("No key_sharp / key_flat templates in {}", d);
                return new Book(null, null, null);
            }

            return new Book(sharp, flat, Layout.load(new File(d, "key_layout.txt")));
        });
    }

    //--------//
    // reread //
    //--------//
    /**
     * Read again the key signature at the start of each pitched staff of the system, with the
     * book templates if any, and replace the key found when it differs.
     *
     * @param system the system whose headers have been processed (clefs selected)
     */
    public static void reread (SystemInfo system)
    {
        final Book book = getLoaded(NoteHeadsBuilder.getTemplateDir());

        if ((book == null) || (book.sharp == null)) {
            return;
        }

        final ByteProcessor gray = system.getSheet().getPicture().getSource(
                Picture.SourceKey.GRAY);

        final java.util.Set<Staff> drums = NoteHeadsBuilder.hintedDrumStaves(system);

        for (Staff staff : system.getStaves()) {
            if (staff.isTablature() || staff.isOneLineStaff() || staff.isDrum() || drums
                    .contains(staff)) {
                continue;
            }

            final StaffHeader header = staff.getHeader();

            if ((header == null) || (header.clef == null)) {
                continue;
            }

            final ClefKind kind = header.clef.getKind();
            final int[] sharpPitches = KeyInter.SHARP_PITCHES_MAP.get(kind);
            final int[] flatPitches = KeyInter.FLAT_PITCHES_MAP.get(kind);

            if ((sharpPitches == null) || (flatPitches == null)) {
                continue;
            }

            final int il = staff.getSpecificInterline();
            final Rectangle clefBox = header.clef.getBounds();
            final int x0 = clefBox.x + clefBox.width;
            final int x1 = x0 + (int) Math.round(11 * il);
            final int top = (int) Math.round(staff.getFirstLine().yAt(x0) - (4 * il));
            final int bot = (int) Math.round(staff.getLastLine().yAt(x0) + (4 * il));
            final CrossTemplate.Band band = new CrossTemplate.Band(gray, staff, x0 - il, x1, top,
                    bot);
            final boolean bass = header.clef.getShape() == Shape.F_CLEF;
            final Layout lay = book.layout;

            final Places sharps = look(book.sharp.scaledFor(il), band, staff, x0, sharpPitches,
                    bass ? lay.sharpGapBass : lay.sharpGapTreble, lay.sharpSpacing, lay.sharpDy,
                    il);
            final Places flats = look(book.flat.scaledFor(il), band, staff, x0, flatPitches,
                    bass ? lay.flatGapBass : lay.flatGapTreble, lay.flatSpacing, lay.flatDy, il);
            final int ns = sharps.count();
            final int nf = flats.count();
            final boolean flat = (nf > 0) && ((ns == 0) || (flats.agreement(nf) > sharps
                    .agreement(ns)) || ((flats.agreement(nf) == sharps.agreement(ns))
                            && (flats.mean(nf) > sharps.mean(ns))));
            final Places best = flat ? flats : sharps;
            final int n = flat ? nf : ns;
            final int fifths = flat ? -n : n;
            final KeyInter old = header.key;
            final int oldFifths = ((old != null) && (old.getFifths() != null)) ? old.getFifths()
                    : 0;

            if (fifths == oldFifths) {
                if (old != null && n > 0) {
                    old.setFromTemplate(true);
                }
                continue;
            }

            logger.info("{} staff#{} key {} read with the templates, not {} (sharps {}; flats {})",
                    system.getSheet().getId(), staff.getId(), fifths, oldFifths, sharps, flats);
            replace(staff, old, best.series(n), flat ? Shape.FLAT : Shape.SHARP,
                    flat ? flatPitches : sharpPitches);
        }
    }

    //------//
    // look //
    //------//
    /**
     * Look at the 7 places of one key kind: best correlation with the template in a small
     * window around each place, and ink there.
     */
    private static Places look (Scaled t,
                                CrossTemplate.Band band,
                                Staff staff,
                                int x0,
                                int[] pitches,
                                double gap,
                                double spacing,
                                double centerShift,
                                int il)
    {
        final Places places = new Places();
        final int wx1 = Math.max(1, (int) Math.round(constants.xWindow.getValue() * il));
        final int wxn = Math.max(1, (int) Math.round(constants.xNextWindow.getValue() * il));
        final int wy = Math.max(1, (int) Math.round(constants.yWindow.getValue() * il));
        final int dx = (int) Math.round(spacing * il);
        Integer prevX = null; // Abscissa of the previous item, when it was seen

        for (int i = 0; i < pitches.length; i++) {
            // The first place from the clef, each next one from the previous item if seen:
            // key items are evenly spaced, an accidental next to the key stands further away
            final int xc = (prevX != null) ? (prevX + dx)
                    : (x0 + (int) Math.round((gap + (i * spacing)) * il));
            final int wx = (prevX != null) ? wxn : wx1;
            double bestGrade = -1;
            int bx = xc;
            int by = 0;

            for (int x = xc - wx; x <= xc + wx; x++) {
                final int yc = (int) Math.round(staff.pitchToOrdinate(x, pitches[i])
                        + (centerShift * il));

                if (x == xc) {
                    by = yc;
                }

                for (int y = yc - wy; y <= yc + wy; y++) {
                    final double g = t.correlation(band, x, y);

                    if (g > bestGrade) {
                        bestGrade = g;
                        bx = x;
                        by = y;
                    }
                }
            }

            places.add(new Rectangle(bx - t.halfW, by - t.halfH, (2 * t.halfW) + 1, (2
                    * t.halfH) + 1), bestGrade, t.ink(band, bx, by));
            prevX = (places.evidence(i) > 0) ? bx : null;
        }

        return places;
    }

    //---------//
    // replace //
    //---------//
    /**
     * Replace the key of the staff header (if any) by the series read.
     */
    private static void replace (Staff staff,
                                 KeyInter old,
                                 Series series,
                                 Shape shape,
                                 int[] pitches)
    {
        final StaffHeader header = staff.getHeader();

        if (old != null) {
            for (Inter member : new ArrayList<>(old.getMembers())) {
                member.remove();
            }

            old.remove();
            header.key = null;
        }

        if (series.size() == 0) {
            header.keyRange = null;

            return;
        }

        final SIGraph sig = staff.getSystem().getSig();
        final List<KeyAlterInter> alters = new ArrayList<>();

        for (int i = 0; i < series.size(); i++) {
            final KeyAlterInter alter = new KeyAlterInter(
                    null,
                    shape,
                    series.grades.get(i),
                    staff,
                    (double) pitches[i],
                    (double) pitches[i]);
            alter.setBounds(series.boxes.get(i));
            sig.addVertex(alter);
            alters.add(alter);
        }

        for (int i = 0; i < alters.size(); i++) {
            for (KeyAlterInter sibling : alters.subList(i + 1, alters.size())) {
                sig.addEdge(alters.get(i), sibling, new KeyAltersRelation());
            }
        }

        // Key with its fifths value set (as KeyInter.buildKey does), members contained
        final Rectangle box = new Rectangle(series.boxes.get(0));
        series.boxes.forEach(box::add);

        final KeyInter key = new KeyInter(series.mean(), (shape == Shape.FLAT) ? -series.size()
                : series.size(), shape);
        key.setFromTemplate(true);
        key.setStaff(staff);
        key.setBounds(box);
        sig.addVertex(key);
        alters.forEach(alter -> sig.addEdge(key, alter, new Containment()));
        header.key = key;

        if (header.keyRange != null) {
            final Rectangle last = series.boxes.get(series.size() - 1);
            staff.setKeyStop(last.x + last.width - 1);
        }
    }

    //~ Inner Classes ------------------------------------------------------------------------------

    //-----------//
    // Constants //
    //-----------//
    private static class Constants
            extends ConstantSet
    {
        private final Constant.Ratio itemGrade = new Constant.Ratio(
                0.6,
                "Correlation from which a place shows a key item");

        private final Constant.Ratio noItemGrade = new Constant.Ratio(
                0.35,
                "Correlation under which a place shows no key item");

        private final Constant.Ratio noItemInk = new Constant.Ratio(
                0.04,
                "Mean darkness in the template box under which a place is blank");

        private final Constant.Ratio xWindow = new Constant.Ratio(
                0.35,
                "Horizontal search window around the first key place (interlines, each side)");

        private final Constant.Ratio xNextWindow = new Constant.Ratio(
                0.2,
                "Horizontal search window around a key place after an item seen (interlines)");

        private final Constant.Ratio yWindow = new Constant.Ratio(
                0.3,
                "Vertical search window around each key place (interlines, each side)");
    }

    //--------//
    // Series //
    //--------//
    /** The items of the key read: box and correlation of each. */
    private static class Series
    {
        final List<Rectangle> boxes = new ArrayList<>();

        final List<Double> grades = new ArrayList<>();

        void add (Rectangle box,
                  double grade)
        {
            boxes.add(box);
            grades.add(grade);
        }

        double mean ()
        {
            return grades.stream().mapToDouble(d -> d).average().orElse(0);
        }

        int size ()
        {
            return boxes.size();
        }
    }

    //--------//
    // Places //
    //--------//
    /** What the 7 places of one key kind show: best box, correlation and ink of each. */
    private static class Places
    {
        final List<Rectangle> boxes = new ArrayList<>();

        final List<Double> grades = new ArrayList<>();

        final List<Double> inks = new ArrayList<>();

        void add (Rectangle box,
                  double grade,
                  double ink)
        {
            boxes.add(box);
            grades.add(grade);
            inks.add(ink);
        }

        /**
         * How much the place shows an item: +1 from itemGrade on, -1 under noItemGrade or when
         * blank, in proportion in between (a grade a bit under itemGrade still leans to an item).
         */
        double evidence (int i)
        {
            if (inks.get(i) < constants.noItemInk.getValue()) {
                return -1;
            }

            final double lo = constants.noItemGrade.getValue();
            final double hi = constants.itemGrade.getValue();
            final double e = ((2 * (grades.get(i) - lo)) / (hi - lo)) - 1;

            return Math.max(-1, Math.min(1, e));
        }

        /** Agreement of all places with a key of n items: items before n, none from n on. */
        double agreement (int n)
        {
            double sum = 0;

            for (int i = 0; i < grades.size(); i++) {
                sum += (i < n) ? evidence(i) : -evidence(i);
            }

            return sum;
        }

        /** The number of items (0 to 7) that agrees best, the smaller one on a tie. */
        int count ()
        {
            int best = 0;

            for (int n = 1; n <= grades.size(); n++) {
                if (agreement(n) > agreement(best)) {
                    best = n;
                }
            }

            return best;
        }

        double mean (int n)
        {
            return grades.subList(0, n).stream().mapToDouble(d -> d).average().orElse(0);
        }

        Series series (int n)
        {
            final Series series = new Series();

            for (int i = 0; i < n; i++) {
                series.add(boxes.get(i), grades.get(i));
            }

            return series;
        }

        @Override
        public String toString ()
        {
            final StringBuilder sb = new StringBuilder();

            for (int i = 0; i < grades.size(); i++) {
                sb.append(String.format(" %.2f/%.2f", grades.get(i), inks.get(i)));
            }

            return sb.toString().trim();
        }
    }

    //--------//
    // Layout //
    //--------//
    /**
     * Places of the key items in a book, in interlines of the staff: from the clef right side
     * to the center of the first item (treble and bass clef), from one item center to the next,
     * and from the pitch line or space to the item center (a flat stands above its pitch).
     * <p>
     * Read from <code>key_layout.txt</code> next to the templates (lines "name = value", "#"
     * for comments); the defaults are those measured on the first book.
     */
    private static class Layout
    {
        double sharpGapTreble = 1.45;

        double sharpGapBass = 1.27;

        double sharpSpacing = 1.18;

        double sharpDy = 0;

        double flatGapTreble = 1.31;

        double flatGapBass = 1.14;

        double flatSpacing = 1.03;

        double flatDy = -0.56;

        static Layout load (File file)
        {
            final Layout lay = new Layout();

            if (!file.isFile()) {
                logger.info("No {}, default key places", file);

                return lay;
            }

            try (java.io.Reader reader = new java.io.InputStreamReader(new java.io.FileInputStream(
                    file), java.nio.charset.StandardCharsets.UTF_8)) {
                final java.util.Properties props = new java.util.Properties();
                props.load(reader);
                lay.sharpGapTreble = get(props, "sharp.gap.treble", lay.sharpGapTreble);
                lay.sharpGapBass = get(props, "sharp.gap.bass", lay.sharpGapBass);
                lay.sharpSpacing = get(props, "sharp.spacing", lay.sharpSpacing);
                lay.sharpDy = get(props, "sharp.dy", lay.sharpDy);
                lay.flatGapTreble = get(props, "flat.gap.treble", lay.flatGapTreble);
                lay.flatGapBass = get(props, "flat.gap.bass", lay.flatGapBass);
                lay.flatSpacing = get(props, "flat.spacing", lay.flatSpacing);
                lay.flatDy = get(props, "flat.dy", lay.flatDy);
                logger.info("Key places {}", file);
            } catch (Exception ex) {
                logger.warn("Cannot read {}", file, ex);
            }

            return lay;
        }

        private static double get (java.util.Properties props,
                                   String key,
                                   double def)
        {
            final String value = props.getProperty(key);

            return (value != null) ? Double.parseDouble(value.trim()) : def;
        }
    }

    //------//
    // Book //
    //------//
    /** The key templates and places of a book (no templates: sharp and flat null). */
    private static class Book
    {
        final Template sharp;

        final Template flat;

        final Layout layout;

        Book (Template sharp,
              Template flat,
              Layout layout)
        {
            this.sharp = sharp;
            this.flat = flat;
            this.layout = layout;
        }
    }

    //----------//
    // Template //
    //----------//
    /** One template image (ink 0..1 at INTERLINE), with its scaled versions. */
    private static class Template
    {
        final float[][] ink;

        final Map<Integer, Scaled> scaled = new HashMap<>();

        Template (float[][] ink)
        {
            this.ink = ink;
        }

        static Template load (File file)
        {
            if (!file.isFile()) {
                return null;
            }

            try {
                final BufferedImage img = ImageIO.read(file);
                final float[][] ink = new float[img.getHeight()][img.getWidth()];

                for (int y = 0; y < img.getHeight(); y++) {
                    for (int x = 0; x < img.getWidth(); x++) {
                        ink[y][x] = 1f - (img.getRaster().getSample(x, y, 0) / 255f);
                    }
                }

                logger.info("Template {} {}x{}", file, img.getWidth(), img.getHeight());

                return new Template(ink);
            } catch (Exception ex) {
                logger.warn("Cannot read template {}", file, ex);

                return null;
            }
        }

        synchronized Scaled scaledFor (int il)
        {
            return scaled.computeIfAbsent(il, k -> new Scaled(ink, (double) k / INTERLINE));
        }
    }

    //--------//
    // Scaled //
    //--------//
    /** A template at a staff interline: offsets and centered values. */
    private static class Scaled
    {
        final int halfW;

        final int halfH;

        final int[] dx;

        final int[] dy;

        final double[] tc;

        final double tNorm;

        Scaled (float[][] ink,
                double s)
        {
            final int h0 = ink.length / 2;
            final int w0 = ink[0].length / 2;
            halfH = (int) Math.round(h0 * s);
            halfW = (int) Math.round(w0 * s);

            final int n = ((2 * halfH) + 1) * ((2 * halfW) + 1);
            dx = new int[n];
            dy = new int[n];

            final double[] v = new double[n];
            int k = 0;
            double sum = 0;

            for (int y = -halfH; y <= halfH; y++) {
                for (int x = -halfW; x <= halfW; x++) {
                    final int sx = Math.min(ink[0].length - 1, Math.max(0, (int) Math.round(x / s)
                            + w0));
                    final int sy = Math.min(ink.length - 1, Math.max(0, (int) Math.round(y / s)
                            + h0));
                    dx[k] = x;
                    dy[k] = y;
                    v[k] = ink[sy][sx];
                    sum += v[k];
                    k++;
                }
            }

            final double mean = sum / n;
            tc = new double[n];
            double norm = 0;

            for (int i = 0; i < n; i++) {
                tc[i] = v[i] - mean;
                norm += tc[i] * tc[i];
            }

            tNorm = Math.sqrt(norm);
        }

        /** Mean darkness of the band in the template box centered at (x, y). */
        double ink (CrossTemplate.Band b,
                    int x,
                    int y)
        {
            double sum = 0;

            for (int i = 0; i < dx.length; i++) {
                sum += b.at(x + dx[i], y + dy[i]);
            }

            return sum / dx.length;
        }

        /** Normalized correlation of template and band darkness, template centered at (x, y). */
        double correlation (CrossTemplate.Band b,
                            int x,
                            int y)
        {
            double num = 0;
            double sum = 0;
            double sum2 = 0;

            for (int i = 0; i < dx.length; i++) {
                final double v = b.at(x + dx[i], y + dy[i]);
                num += tc[i] * v;
                sum += v;
                sum2 += v * v;
            }

            final double var = sum2 - ((sum * sum) / dx.length);

            if (var <= 1e-9) {
                return 0;
            }

            return num / (Math.sqrt(var) * tNorm);
        }
    }
}
