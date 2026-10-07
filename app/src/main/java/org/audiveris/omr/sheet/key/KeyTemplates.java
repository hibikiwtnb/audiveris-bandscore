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
 * The items of a key signature stand at fixed places: the first one right after the clef, at
 * the pitch of the clef table ({@link KeyInter#SHARP_PITCHES_MAP},
 * {@link KeyInter#FLAT_PITCHES_MAP}), each next one about an interline further right at its own
 * pitch. Each place is matched with the template (normalized correlation of the gray image,
 * staff lines erased as for the drum templates); the items are counted from the first one on,
 * up to the first place that does not match. Sharps and flats are both tried, the longer series
 * wins. The first item needs a higher correlation than the next ones: the dots of a bass clef,
 * right where its first sharp would be, match a sharp at about 0.6, a true item at 0.8 or more.
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

    /** Loaded templates per folder: sharp then flat (null when missing). */
    private static final Map<String, Template[]> loaded = new HashMap<>();

    //~ Constructors -------------------------------------------------------------------------------

    private KeyTemplates ()
    {
    }

    //~ Static Methods -----------------------------------------------------------------------------

    //---------//
    // loaded  //
    //---------//
    private static synchronized Template[] getLoaded (String dir)
    {
        if ((dir == null) || dir.isBlank() || !new File(dir).isDirectory()) {
            return null;
        }

        return loaded.computeIfAbsent(dir, d -> {
            final Template sharp = Template.load(new File(d, "key_sharp.png"));
            final Template flat = Template.load(new File(d, "key_flat.png"));

            if ((sharp == null) || (flat == null)) {
                logger.info("No key_sharp / key_flat templates in {}", d);
                return new Template[0];
            }

            return new Template[] { sharp, flat };
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
        final Template[] templates = getLoaded(NoteHeadsBuilder.getTemplateDir());

        if ((templates == null) || (templates.length == 0)) {
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
            final int x1 = x0 + (int) Math.round(10 * il);
            final int top = (int) Math.round(staff.getFirstLine().yAt(x0) - (4 * il));
            final int bot = (int) Math.round(staff.getLastLine().yAt(x0) + (4 * il));
            final CrossTemplate.Band band = new CrossTemplate.Band(gray, staff, x0 - il, x1, top,
                    bot);

            final Series sharps = read(templates[0].scaledFor(il), band, staff, x0, sharpPitches,
                    0, il);
            final Series flats = read(templates[1].scaledFor(il), band, staff, x0, flatPitches,
                    constants.flatCenterShift.getValue(), il);
            final Series best = (flats.size() > sharps.size()) ? flats
                    : (sharps.size() > flats.size()) ? sharps
                    : (flats.mean() > sharps.mean()) ? flats : sharps;
            final int fifths = (best == flats) ? -best.size() : best.size();
            final KeyInter old = header.key;
            final int oldFifths = ((old != null) && (old.getFifths() != null)) ? old.getFifths()
                    : 0;

            if (fifths == oldFifths) {
                continue;
            }

            logger.info("{} staff#{} key {} read with the templates, not {} (grades {}; sharps {}"
                    + " flats {})", system.getSheet().getId(), staff.getId(), fifths, oldFifths,
                    best.grades(), sharps.grades(), flats.grades());
            replace(staff, old, best, (best == flats) ? Shape.FLAT : Shape.SHARP,
                    (best == flats) ? flatPitches : sharpPitches);
        }
    }

    //------//
    // read //
    //------//
    /**
     * Match the items of one key kind from the first one on, up to the first that misses.
     */
    private static Series read (Scaled t,
                                CrossTemplate.Band band,
                                Staff staff,
                                int x0,
                                int[] pitches,
                                double centerShift,
                                int il)
    {
        final Series series = new Series();
        final double minGrade = constants.minGrade.getValue();
        final double minFirstGrade = constants.minFirstGrade.getValue();
        final int dy = Math.max(1, (int) Math.round(constants.maxPitchShift.getValue() * il));
        int from = x0 - (int) Math.round(0.3 * il);
        int to = x0 + (int) Math.round(constants.maxFirstGap.getValue() * il);

        for (int i = 0; i < pitches.length; i++) {
            double bestGrade = -1;
            int bx = 0;
            int by = 0;

            for (int x = from; x <= to; x++) {
                final int yc = (int) Math.round(staff.pitchToOrdinate(x, pitches[i])
                        + (centerShift * il));

                for (int y = yc - dy; y <= yc + dy; y++) {
                    final double g = t.correlation(band, x, y);

                    if (g > bestGrade) {
                        bestGrade = g;
                        bx = x;
                        by = y;
                    }
                }
            }

            if (bestGrade < ((i == 0) ? minFirstGrade : minGrade)) {
                series.stop = String.format("%.2f@%d,%d", bestGrade, bx, by);
                break;
            }

            series.add(new Rectangle(bx - t.halfW, by - t.halfH, 2 * t.halfW + 1, 2 * t.halfH
                    + 1), bestGrade);
            from = bx + (int) Math.round(constants.minItemDx.getValue() * il);
            to = bx + (int) Math.round(constants.maxItemDx.getValue() * il);
        }

        return series;
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
        private final Constant.Ratio minGrade = new Constant.Ratio(
                0.5,
                "Minimum correlation of a key item with the book template");

        private final Constant.Ratio minFirstGrade = new Constant.Ratio(
                0.75,
                "Minimum correlation of the first key item (the dots of a bass clef match 0.6)");

        private final Constant.Ratio maxFirstGap = new Constant.Ratio(
                2.5,
                "Maximum distance from the clef right side to the first key item (interlines)");

        private final Constant.Ratio minItemDx = new Constant.Ratio(
                0.7,
                "Minimum distance from one key item to the next (interlines)");

        private final Constant.Ratio maxItemDx = new Constant.Ratio(
                1.6,
                "Maximum distance from one key item to the next (interlines)");

        private final Constant.Ratio maxPitchShift = new Constant.Ratio(
                0.25,
                "Maximum vertical shift of a key item from its pitch (interlines)");

        private final Constant.Double flatCenterShift = new Constant.Double(
                "interline",
                -0.56,
                "Center of the flat template above its pitch (interlines, measured on the books)");
    }

    //--------//
    // Series //
    //--------//
    /** The items matched for one key kind, from the first one on. */
    private static class Series
    {
        final List<Rectangle> boxes = new ArrayList<>();

        final List<Double> grades = new ArrayList<>();

        /** Grade and place of the first place that missed, for the log. */
        String stop = "";

        void add (Rectangle box,
                  double grade)
        {
            boxes.add(box);
            grades.add(grade);
        }

        String grades ()
        {
            final StringBuilder sb = new StringBuilder();

            for (double g : grades) {
                sb.append(String.format(" %.2f", g));
            }

            return sb.toString().trim() + " | " + stop;
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
