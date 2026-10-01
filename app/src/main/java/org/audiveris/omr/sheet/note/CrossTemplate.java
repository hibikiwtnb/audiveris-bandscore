//------------------------------------------------------------------------------------------------//
//                                                                                                //
//                                    C r o s s T e m p l a t e                                   //
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
package org.audiveris.omr.sheet.note;

import org.audiveris.omr.glyph.Glyph;
import org.audiveris.omr.glyph.Shape;
import org.audiveris.omr.glyph.ShapeSet.HeadMotif;
import static org.audiveris.omr.image.PixelSource.BACKGROUND;
import static org.audiveris.omr.run.Orientation.VERTICAL;
import org.audiveris.omr.run.RunTable;
import org.audiveris.omr.run.RunTableFactory;
import org.audiveris.omr.score.DrumSet;
import org.audiveris.omr.sheet.Sheet;
import org.audiveris.omr.sheet.Staff;
import org.audiveris.omr.sig.inter.HeadInter;
import org.audiveris.omr.util.ByteUtil;
import org.audiveris.omr.util.HorizontalSide;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import ij.process.ByteProcessor;

import java.awt.image.BufferedImage;
import java.io.File;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;

import javax.imageio.ImageIO;

/**
 * Class <code>CrossTemplate</code> finds the cross heads of a drum staff by matching a
 * template made from the book itself (all the songs of a printed book share the same font).
 * <p>
 * The template folder holds <code>cross.png</code> (ink dark, drawn at a staff interline of
 * {@link #INTERLINE} pixels) and <code>cross_mask.png</code> (white = pixels used for matching:
 * the X strokes and the white around them, not the stem going up or down, nor ledgers).
 * Both are made once per book by <code>tools/learn_template.py</code> (bandscore-omr-skill).
 * <p>
 * On a drum staff, staff lines and ledger rows are erased where white above and below, then the
 * template is matched (normalized correlation over the mask) around every drum-set pitch where a
 * cross motif is defined. A match is kept when its correlation reaches the minimum grade and the
 * notches of the X are white (a black head fills them).
 */
public class CrossTemplate
{
    //~ Static fields/initializers -----------------------------------------------------------------

    private static final Logger logger = LoggerFactory.getLogger(CrossTemplate.class);

    /** Staff interline of the template images. */
    public static final int INTERLINE = 20;

    /** Maximum ink ratio in the notches of the X. */
    private static final double MAX_NOTCH_INK = 0.25;

    /** Loaded templates, per folder (null when the folder has no cross template). */
    private static final Map<String, CrossTemplate> loaded = new HashMap<>();

    //~ Instance fields ----------------------------------------------------------------------------

    /** Template ink (0..1) and mask, at INTERLINE. */
    private final float[][] ink;

    private final boolean[][] mask;

    /** Scaled versions, per staff interline. */
    private final Map<Integer, Scaled> scaled = new HashMap<>();

    //~ Constructors -------------------------------------------------------------------------------

    private CrossTemplate (float[][] ink,
                           boolean[][] mask)
    {
        this.ink = ink;
        this.mask = mask;
    }

    //~ Methods ------------------------------------------------------------------------------------

    //--------//
    // lookup //
    //--------//
    /**
     * Find the cross heads of the provided drum staff.
     *
     * @param staff    the drum staff
     * @param image    the binary sheet image
     * @param minGrade minimum correlation for a cross
     * @return the cross heads found (not yet in sig)
     */
    public List<HeadInter> lookup (Staff staff,
                                   ByteProcessor image,
                                   double minGrade)
    {
        final List<HeadInter> heads = new ArrayList<>();
        final int il = staff.getSpecificInterline();
        final Scaled t = scaledFor(il);
        final int h = t.half;
        final Set<Integer> pitches = crossPitches(staff.getLineCount());

        if (pitches.isEmpty()) {
            return heads;
        }

        // Band of the staff, staff lines and ledger rows erased
        final int x0 = staff.getHeaderStop();
        final int x1 = Math.min(
                (int) Math.ceil(staff.getLastLine().getEndPoint(HorizontalSide.RIGHT).getX()),
                image.getWidth() - 1);
        final int top = (int) Math.floor(
                staff.pitchToOrdinate(x0, pitches.iterator().next()) - il) - h;
        final int bot = (int) Math.ceil(
                staff.pitchToOrdinate(x0, ((TreeSet<Integer>) pitches).last()) + il) + h;
        final Band band = new Band(image, staff, x0, x1, top, bot);

        // Correlation around every cross pitch row
        final List<double[]> found = new ArrayList<>(); // x, y, corr, pitch
        for (int x = x0 + h; x < x1 - h; x++) {
            for (int p : pitches) {
                final int yc = (int) Math.round(staff.pitchToOrdinate(x, p));

                for (int y = yc - il / 3; y <= yc + il / 3; y++) {
                    if (t.foreInk(band, x, y) < 0.5) {
                        continue; // Not even the X strokes inked
                    }

                    final double c = t.correlation(band, x, y);

                    if (c >= minGrade && t.notchInk(band, x, y) <= MAX_NOTCH_INK) {
                        found.add(new double[] { x, y, c, p });
                    }
                }
            }
        }

        // Peaks: best first, none closer than 0.6 interline to a better one
        found.sort(Comparator.comparingDouble((double[] f) -> -f[2]));
        final double win = 0.6 * il;
        final List<double[]> peaks = new ArrayList<>();

        for (double[] f : found) {
            boolean free = true;

            for (double[] k : peaks) {
                if (Math.abs(f[0] - k[0]) <= win && Math.abs(f[1] - k[1]) <= win) {
                    free = false;
                    break;
                }
            }

            if (free) {
                peaks.add(f);
            }
        }

        final Sheet sheet = staff.getSystem().getSheet();

        for (double[] f : peaks) {
            final HeadInter head = t.createHead(
                    band,
                    (int) f[0],
                    (int) f[1],
                    f[2],
                    staff,
                    (int) f[3],
                    sheet);

            if (head != null) {
                heads.add(head);
            }
        }

        logger.info("Staff#{} {} cross heads from template", staff.getId(), heads.size());

        return heads;
    }

    //-----------//
    // scaledFor //
    //-----------//
    private synchronized Scaled scaledFor (int il)
    {
        return scaled.computeIfAbsent(il, k -> new Scaled(ink, mask, (double) k / INTERLINE));
    }

    //--------------//
    // crossPitches //
    //--------------//
    /**
     * Pitch positions where the drum set defines a cross motif, ascending.
     */
    private static Set<Integer> crossPitches (int lineCount)
    {
        final Set<Integer> set = new TreeSet<>();
        final Map<Integer, Map<DrumSet.MotifSign, DrumSet.DrumInstrument>> staffSet = DrumSet
                .getInstance().getStaffSet(lineCount);

        if (staffSet != null) {
            for (Map.Entry<Integer, Map<DrumSet.MotifSign, DrumSet.DrumInstrument>> e : staffSet
                    .entrySet()) {
                for (DrumSet.MotifSign ms : e.getValue().keySet()) {
                    if (ms.motif == HeadMotif.cross) {
                        set.add(e.getKey());
                    }
                }
            }
        }

        return set;
    }

    //-----------//
    // getLoaded //
    //-----------//
    /**
     * Report the cross template of the provided folder.
     *
     * @param dir the template folder (empty for none)
     * @return the template, or null if none
     */
    public static synchronized CrossTemplate getLoaded (String dir)
    {
        if ((dir == null) || dir.isBlank()) {
            return null;
        }

        if (!loaded.containsKey(dir)) {
            loaded.put(dir, load(new File(dir)));
        }

        return loaded.get(dir);
    }

    //------//
    // load //
    //------//
    private static CrossTemplate load (File dir)
    {
        final File inkFile = new File(dir, "cross.png");
        final File maskFile = new File(dir, "cross_mask.png");

        if (!inkFile.isFile() || !maskFile.isFile()) {
            logger.info("No cross template in {}", dir.getAbsolutePath());
            return null;
        }

        try {
            final BufferedImage ii = ImageIO.read(inkFile);
            final BufferedImage mi = ImageIO.read(maskFile);
            final int n = ii.getWidth();
            final float[][] ink = new float[n][n];
            final boolean[][] mask = new boolean[n][n];

            for (int y = 0; y < n; y++) {
                for (int x = 0; x < n; x++) {
                    ink[y][x] = 1f - (ii.getRaster().getSample(x, y, 0) / 255f);
                    mask[y][x] = mi.getRaster().getSample(x, y, 0) > 127;
                }
            }

            logger.info("Cross template {}x{} from {}", n, n, dir.getAbsolutePath());

            return new CrossTemplate(ink, mask);
        } catch (Exception ex) {
            logger.warn("Cannot read cross template in {}", dir.getAbsolutePath(), ex);
            return null;
        }
    }

    //~ Inner Classes ------------------------------------------------------------------------------

    //------//
    // Band //
    //------//
    /**
     * The ink of a staff band, staff lines and ledger rows erased where white above and below.
     */
    private static class Band
    {
        final int x0, y0, w, hgt;

        final boolean[][] ink; // [y - y0][x - x0]

        Band (ByteProcessor image,
              Staff staff,
              int x0,
              int x1,
              int top,
              int bot)
        {
            this.x0 = x0;
            this.y0 = Math.max(top, 0);
            this.w = x1 - x0;
            this.hgt = Math.min(bot, image.getHeight()) - y0;
            ink = new boolean[hgt][w];

            for (int y = 0; y < hgt; y++) {
                for (int x = 0; x < w; x++) {
                    ink[y][x] = image.get(x + x0, y + y0) == 0;
                }
            }

            // Line rows: staff lines and three ledger rows on each side
            final int lc = staff.getLineCount();
            final int t = staff.getSystem().getSheet().getScale().getFore() / 2 + 1;
            final boolean[][] orig = new boolean[hgt][];

            for (int y = 0; y < hgt; y++) {
                orig[y] = ink[y].clone();
            }

            for (int x = 0; x < w; x++) {
                for (int p = -(lc - 1) - 6; p <= (lc - 1) + 6; p += 2) {
                    final int yl = (int) Math.round(staff.pitchToOrdinate(x + x0, p)) - y0;

                    if ((yl - t - 1 < 0) || (yl + t + 1 >= hgt)) {
                        continue;
                    }

                    if (!orig[yl - t - 1][x] && !orig[yl + t + 1][x]) {
                        for (int y = yl - t; y <= yl + t; y++) {
                            ink[y][x] = false;
                        }
                    }
                }
            }
        }

        boolean at (int x,
                    int y)
        {
            final int bx = x - x0;
            final int by = y - y0;
            return (bx >= 0) && (by >= 0) && (bx < w) && (by < hgt) && ink[by][bx];
        }
    }

    //--------//
    // Scaled //
    //--------//
    /**
     * The template at a given staff interline.
     */
    private static class Scaled
    {
        final int half;

        final int n;

        /** Mask offsets (dx, dy) and centered template values there. */
        final int[] dx, dy;

        final double[] tc;

        final double tNorm;

        /** Notch offsets: mask pixels left white by the template near the center. */
        final int[] ndx, ndy;

        /** Ink offsets: template pixels mostly ink (glyph and bounds). */
        final int[] idx, idy;

        Scaled (float[][] ink,
                boolean[][] mask,
                double s)
        {
            final int n0 = ink.length;
            final int h0 = n0 / 2;
            half = (int) Math.round(h0 * s);
            n = 2 * half + 1;

            final List<int[]> m = new ArrayList<>();
            final List<Double> v = new ArrayList<>();
            final List<int[]> notch = new ArrayList<>();
            final List<int[]> fore = new ArrayList<>();
            final double r = 0.6 * INTERLINE * s;

            for (int y = 0; y < n; y++) {
                for (int x = 0; x < n; x++) {
                    // Nearest source pixel
                    final int sx = Math.min(n0 - 1, (int) Math.round((x - half) / s) + h0);
                    final int sy = Math.min(n0 - 1, (int) Math.round((y - half) / s) + h0);

                    if ((sx < 0) || (sy < 0) || !mask[sy][sx]) {
                        continue;
                    }

                    final double val = ink[sy][sx];
                    m.add(new int[] { x - half, y - half });
                    v.add(val);

                    if ((val < 0.15) && (Math.hypot(x - half, y - half) <= r)) {
                        notch.add(new int[] { x - half, y - half });
                    }

                    if (val >= 0.5) {
                        fore.add(new int[] { x - half, y - half });
                    }
                }
            }

            final double mean = v.stream().mapToDouble(d -> d).average().orElse(0);
            dx = new int[m.size()];
            dy = new int[m.size()];
            tc = new double[m.size()];
            double norm = 0;

            for (int i = 0; i < m.size(); i++) {
                dx[i] = m.get(i)[0];
                dy[i] = m.get(i)[1];
                tc[i] = v.get(i) - mean;
                norm += tc[i] * tc[i];
            }

            tNorm = Math.sqrt(norm);
            ndx = notch.stream().mapToInt(a -> a[0]).toArray();
            ndy = notch.stream().mapToInt(a -> a[1]).toArray();
            idx = fore.stream().mapToInt(a -> a[0]).toArray();
            idy = fore.stream().mapToInt(a -> a[1]).toArray();
        }

        /** Normalized correlation of template and band ink at (x, y), over the mask. */
        double correlation (Band b,
                            int x,
                            int y)
        {
            double num = 0;
            int count = 0;

            for (int i = 0; i < dx.length; i++) {
                if (b.at(x + dx[i], y + dy[i])) {
                    num += tc[i];
                    count++;
                }
            }

            if (count == 0) {
                return 0;
            }

            // Ink values are 0/1: sum((I - mean)^2) = count - count^2 / size
            final double var = count - ((double) count * count / dx.length);

            if (var <= 0) {
                return 0;
            }

            return num / (Math.sqrt(var) * tNorm);
        }

        /** Ink ratio under the X strokes at (x, y). */
        double foreInk (Band b,
                        int x,
                        int y)
        {
            int count = 0;

            for (int i = 0; i < idx.length; i++) {
                if (b.at(x + idx[i], y + idy[i])) {
                    count++;
                }
            }

            return (idx.length == 0) ? 0 : (double) count / idx.length;
        }

        /** Ink ratio in the notches of the X at (x, y). */
        double notchInk (Band b,
                         int x,
                         int y)
        {
            if (ndx.length == 0) {
                return 1;
            }

            int count = 0;

            for (int i = 0; i < ndx.length; i++) {
                if (b.at(x + ndx[i], y + ndy[i])) {
                    count++;
                }
            }

            return (double) count / ndx.length;
        }

        /** Cross head at (x, y): glyph made of the band ink under the template strokes. */
        HeadInter createHead (Band b,
                              int x,
                              int y,
                              double grade,
                              Staff staff,
                              int pitch,
                              Sheet sheet)
        {
            int xMin = Integer.MAX_VALUE, yMin = Integer.MAX_VALUE;
            int xMax = Integer.MIN_VALUE, yMax = Integer.MIN_VALUE;
            final List<int[]> pts = new ArrayList<>();

            for (int i = 0; i < idx.length; i++) {
                final int px = x + idx[i];
                final int py = y + idy[i];

                if (b.at(px, py)) {
                    pts.add(new int[] { px, py });
                    xMin = Math.min(xMin, px);
                    yMin = Math.min(yMin, py);
                    xMax = Math.max(xMax, px);
                    yMax = Math.max(yMax, py);
                }
            }

            if (pts.isEmpty()) {
                return null;
            }

            final ByteProcessor buf = new ByteProcessor(xMax - xMin + 1, yMax - yMin + 1);
            ByteUtil.fill(buf, BACKGROUND);

            for (int[] p : pts) {
                buf.set(p[0] - xMin, p[1] - yMin, 0);
            }

            final RunTable runTable = new RunTableFactory(VERTICAL).createTable(buf);
            final Glyph glyph = sheet.getGlyphIndex().registerOriginal(
                    new Glyph(xMin, yMin, runTable));
            final HeadInter head = new HeadInter(
                    glyph.getBounds(),
                    Shape.NOTEHEAD_CROSS,
                    new HeadInter.Impacts(grade),
                    staff,
                    (double) pitch);
            head.setGlyph(glyph);

            return head;
        }
    }
}
