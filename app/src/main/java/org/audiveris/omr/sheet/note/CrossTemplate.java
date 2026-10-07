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

import java.awt.Rectangle;
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
 * The template folder holds <code>cross.png</code>: a square just holding the X (ink dark,
 * drawn at a staff interline of {@link #INTERLINE} pixels), the average of a few examples picked
 * by eye on the book's pages. Every pixel of the square is matched.
 * It may also hold <code>cross_line.png</code> (a cross crossed by a staff line or ledger) and
 * <code>cross_ledger.png</code> (a cross standing on a short thick ledger): the same symbol
 * looks different there. At every place all are tried, the best correlation counts.
 * They are made once per book by <code>tools/learn_template.py</code> (bandscore-omr-skill).
 * <p>
 * Templates and page are gray, never binarized: the page darkness (0 white .. 1 black) after a
 * 3x3 median, as when learning.
 * Horizontal lines (staff lines, ledgers) are erased (made white) where white above and
 * below, then the template is matched (normalized correlation, which does not depend on how dark
 * the print is) around every drum-set pitch where a cross motif is defined. A match is kept when
 * its correlation reaches the minimum grade and the notches of the X are white (a black head
 * fills them).
 * <p>
 * The same matching finds the slashes of a guitar staff (the previous chord again, with the
 * slash rhythm) with <code>slash.png</code>, around the pitches given by the caller.
 */
public class CrossTemplate
{
    //~ Static fields/initializers -----------------------------------------------------------------

    private static final Logger logger = LoggerFactory.getLogger(CrossTemplate.class);

    /** Staff interline of the template images. */
    public static final int INTERLINE = 20;

    /** Gray level below which a pixel is ink: only to locate lines and to shape the glyph. */
    private static final int INK_GRAY = 160;

    /** Gray level below which a pixel may belong to a (pale) staff line or ledger. */
    private static final int LINE_GRAY = 200;

    /** Darkness of INK_GRAY. */
    private static final double INK_DARK = 1 - (INK_GRAY / 255.0);

    /** Darkness of LINE_GRAY. */
    private static final double LINE_DARK = 1 - (LINE_GRAY / 255.0);

    /** Maximum mean darkness in the notches of the X. */
    private static final double MAX_NOTCH_INK = 0.25;

    /** Loaded templates, per folder and shape (null when the folder has no such template). */
    private static final Map<String, CrossTemplate> loaded = new HashMap<>();

    //~ Instance fields ----------------------------------------------------------------------------

    /** The template images: cross, then cross on a line if any (or slash). */
    private final List<Image> images;

    /** Shape of the heads found. */
    private final Shape shape;

    //~ Constructors -------------------------------------------------------------------------------

    private CrossTemplate (List<Image> images,
                           Shape shape)
    {
        this.images = images;
        this.shape = shape;
    }

    //~ Methods ------------------------------------------------------------------------------------

    //--------//
    // lookup //
    //--------//
    /**
     * Find the heads (crosses or slashes) of the provided staff.
     *
     * @param staff    the staff
     * @param image    the gray sheet image
     * @param minGrade minimum correlation for a head
     * @param pitches  the pitch positions to look around, ascending
     * @return the heads found (not yet in sig)
     */
    public List<HeadInter> lookup (Staff staff,
                                   ByteProcessor image,
                                   double minGrade,
                                   Set<Integer> pitches)
    {
        final List<HeadInter> heads = new ArrayList<>();
        final int il = staff.getSpecificInterline();
        final List<Scaled> ts = new ArrayList<>();

        for (Image image0 : images) {
            ts.add(image0.scaledFor(il));
        }

        final int h = ts.stream().mapToInt(t -> t.half).max().getAsInt();

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

        // Correlation around every cross pitch row, with each template
        final List<double[]> found = new ArrayList<>(); // x, y, corr, pitch, template
        final double[] best = { 0, 0, 0, 0 }; // corr, notch ink, x, y: for the log line
        for (int x = x0 + h; x < x1 - h; x++) {
            for (int p : pitches) {
                final int yc = (int) Math.round(staff.pitchToOrdinate(x, p));

                for (int y = yc - il / 3; y <= yc + il / 3; y++) {
                    for (int i = 0; i < ts.size(); i++) {
                        final Scaled t = ts.get(i);

                        final double c = t.correlation(band, x, y);

                        if (c > best[0]) {
                            best[0] = c;
                            best[1] = t.notchInk(band, x, y);
                            best[2] = x;
                            best[3] = y;
                        }

                        if (c >= minGrade && t.notchInk(band, x, y) <= MAX_NOTCH_INK) {
                            found.add(new double[] { x, y, c, p, i });
                        }
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
            int pitch = (int) f[3];
            if (shape != Shape.NOTEHEAD_SLASH && !pitches.isEmpty()) {
                double minDiff = Double.MAX_VALUE;
                for (int p : pitches) {
                    double ord = staff.pitchToOrdinate(f[0], p);
                    double diff = Math.abs(f[1] - ord);
                    if (diff < minDiff) {
                        minDiff = diff;
                        pitch = p;
                    }
                }
            }

            final HeadInter head = ts.get((int) f[4]).createHead(
                    shape,
                    band,
                    (int) f[0],
                    (int) f[1],
                    f[2],
                    staff,
                    (shape == Shape.NOTEHEAD_SLASH) ? 0 : pitch, // A slash has no pitch
                    sheet);

            if (head != null) {
                heads.add(head);
            }
        }

        logger.info(
                "Staff#{} {} {} heads from template (best correlation {} notch ink {} at {},{},"
                        + " interline {})",
                staff.getId(),
                heads.size(),
                shape,
                String.format("%.2f", best[0]),
                String.format("%.2f", best[1]),
                (int) best[2],
                (int) best[3],
                il);

        return heads;
    }

    //--------------//
    // crossPitches //
    //--------------//
    /**
     * Pitch positions where the drum set defines a cross motif, ascending.
     *
     * @param lineCount staff line count
     * @return the pitch positions
     */
    public static Set<Integer> crossPitches (int lineCount)
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
     * Report the cross or slash template of the provided folder.
     *
     * @param dir   the template folder (empty for none)
     * @param shape NOTEHEAD_CROSS or NOTEHEAD_SLASH
     * @return the template, or null if none
     */
    public static synchronized CrossTemplate getLoaded (String dir,
                                                        Shape shape)
    {
        if ((dir == null) || dir.isBlank()) {
            return null;
        }

        if (!new File(dir).isDirectory()) {
            throw new IllegalStateException("templateDir not found: " + dir);
        }

        final String key = dir + "|" + shape;

        if (!loaded.containsKey(key)) {
            loaded.put(key, load(new File(dir), shape));
        }

        return loaded.get(key);
    }

    //------//
    // load //
    //------//
    private static CrossTemplate load (File dir,
                                       Shape shape)
    {
        final List<Image> images = new ArrayList<>();
        final String[] names = (shape == Shape.NOTEHEAD_SLASH) ? new String[] { "slash" }
                : new String[] { "cross", "cross_line", "cross_ledger" };

        for (String name : names) {
            final File inkFile = new File(dir, name + ".png");

            if (!inkFile.isFile()) {
                continue;
            }

            try {
                final BufferedImage ii = ImageIO.read(inkFile);
                final int n = ii.getWidth();
                final float[][] ink = new float[n][n];

                for (int y = 0; y < n; y++) {
                    for (int x = 0; x < n; x++) {
                        ink[y][x] = 1f - (ii.getRaster().getSample(x, y, 0) / 255f);
                    }
                }

                logger.info("Template {} {}x{} from {}", name, n, n, dir.getAbsolutePath());
                images.add(new Image(ink));
            } catch (Exception ex) {
                logger.warn("Cannot read {} template in {}", name, dir.getAbsolutePath(), ex);
                return null;
            }
        }

        if (images.isEmpty() || !new File(dir, names[0] + ".png").isFile()) {
            logger.info("No {} template in {}", names[0], dir.getAbsolutePath());
            return null;
        }

        return new CrossTemplate(images, shape);
    }

    //~ Inner Classes ------------------------------------------------------------------------------

    //------//
    // Band //
    //------//
    /**
     * The darkness of a staff band, horizontal lines (staff lines, ledgers) erased (made white)
     * where white above and below: the same rule as tools/learn_template.py, so that page and
     * template look alike.
     */
    public static class Band
    {
        final int x0, y0, w, hgt;

        final float[][] dark; // [y - y0][x - x0], 0 white .. 1 black

        public Band (ByteProcessor image,
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
            dark = new float[hgt][w];
            final boolean[][] orig = new boolean[hgt][w]; // ink: is it white above and below?
            final boolean[][] line = new boolean[hgt][w]; // dark enough for a line

            for (int y = 0; y < hgt; y++) {
                for (int x = 0; x < w; x++) {
                    final int g = median3(image, x + x0, y + y0);
                    dark[y][x] = 1f - (g / 255f);
                    orig[y][x] = g < INK_GRAY;
                    line[y][x] = g < LINE_GRAY;
                }
            }

            // Lines: runs of a row at least 1.2 interline long, erased where white above and
            // below (the X strokes crossing a line stay), with the rows next to them
            final int il = staff.getSpecificInterline();
            final int len = (int) Math.round(1.2 * il);
            final int d = Math.max(1, (int) Math.round(il / 5.0));
            final boolean[][] erase = new boolean[hgt][w];

            for (int y = d; y < hgt - d; y++) {
                int x = 0;

                while (x < w) {
                    if (!line[y][x]) {
                        x++;
                        continue;
                    }

                    int e = x;

                    while ((e < w) && line[y][e]) {
                        e++;
                    }

                    if (e - x >= len) {
                        for (int k = x; k < e; k++) {
                            erase[y][k] = !orig[y - d][k] && !orig[y + d][k];
                        }
                    }

                    x = e;
                }
            }

            for (int y = 0; y < hgt; y++) {
                for (int x = 0; x < w; x++) {
                    if (erase[y][x]) {
                        for (int yy = Math.max(0, y - 1); yy <= Math.min(hgt - 1, y + 1); yy++) {
                            dark[yy][x] = 0;
                        }
                    }
                }
            }
        }

        /** Median gray level of the 3x3 neighborhood (scan speckles out). */
        private static int median3 (ByteProcessor image,
                                    int x,
                                    int y)
        {
            final int[] v = new int[9];
            int n = 0;

            for (int dy = -1; dy <= 1; dy++) {
                for (int dx = -1; dx <= 1; dx++) {
                    final int xx = Math.min(Math.max(x + dx, 0), image.getWidth() - 1);
                    final int yy = Math.min(Math.max(y + dy, 0), image.getHeight() - 1);
                    v[n++] = image.get(xx, yy);
                }
            }

            java.util.Arrays.sort(v);

            return v[4];
        }

        /** Darkness at (x, y), 0 outside the band. */
        public double at (int x,
                   int y)
        {
            final int bx = x - x0;
            final int by = y - y0;
            return ((bx >= 0) && (by >= 0) && (bx < w) && (by < hgt)) ? dark[by][bx] : 0;
        }
    }

    //-------//
    // Image //
    //-------//
    /**
     * One template image: ink (0..1) at INTERLINE, with its scaled versions.
     */
    private static class Image
    {
        final float[][] ink;

        /** Scaled versions, per staff interline. */
        final Map<Integer, Scaled> scaled = new HashMap<>();

        Image (float[][] ink)
        {
            this.ink = ink;
        }

        synchronized Scaled scaledFor (int il)
        {
            return scaled.computeIfAbsent(il, k -> new Scaled(ink, (double) k / INTERLINE));
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

        /** Template offsets (dx, dy) and centered template values there. */
        final int[] dx, dy;

        final double[] tc;

        final double tNorm;

        /** Notch offsets: pixels left white by the template near the center. */
        final int[] ndx, ndy;

        /**
         * Ink offsets: template pixels at least half as dark as its darkest one, head body only
         * (glyph and bounds).
         */
        final int[] idx, idy;

        /** Whole symbol offsets: template pixels at least a tenth as dark as its darkest one. */
        final int[] wdx, wdy;

        Scaled (float[][] ink,
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
            final List<int[]> whole = new ArrayList<>();
            final double r = 0.6 * INTERLINE * s;
            float top = 0; // Darkest template pixel: the template is as pale as its page

            for (float[] row : ink) {
                for (float val : row) {
                    top = Math.max(top, val);
                }
            }

            for (int y = 0; y < n; y++) {
                for (int x = 0; x < n; x++) {
                    // Nearest source pixel
                    final int sx = Math.min(n0 - 1, (int) Math.round((x - half) / s) + h0);
                    final int sy = Math.min(n0 - 1, (int) Math.round((y - half) / s) + h0);

                    if ((sx < 0) || (sy < 0)) {
                        continue;
                    }

                    final double val = ink[sy][sx];
                    m.add(new int[] { x - half, y - half });
                    v.add(val);

                    if ((val < (0.15 * top)) && (Math.hypot(x - half, y - half) <= r)) {
                        notch.add(new int[] { x - half, y - half });
                    }

                    if (val >= (0.5 * top)) {
                        fore.add(new int[] { x - half, y - half });
                    }

                    if (val >= (0.1 * top)) {
                        whole.add(new int[] { x - half, y - half });
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
            // Head body only: drop the rows as thin as a stem (a stem the seeds shared, going
            // up or down from the head, would else enlarge the head and shift its stem anchors)
            final Map<Integer, Integer> perRow = new HashMap<>();
            fore.forEach(a -> perRow.merge(a[1], 1, Integer::sum));
            final int widest = perRow.values().stream().max(Integer::compare).orElse(0);
            final List<int[]> body = new ArrayList<>();

            for (int[] a : fore) {
                if (perRow.get(a[1]) >= (widest / 4.0)) {
                    body.add(a);
                }
            }

            idx = body.stream().mapToInt(a -> a[0]).toArray();
            idy = body.stream().mapToInt(a -> a[1]).toArray();
            wdx = whole.stream().mapToInt(a -> a[0]).toArray();
            wdy = whole.stream().mapToInt(a -> a[1]).toArray();
        }

        /** Normalized correlation of template and band darkness at (x, y). */
        double correlation (Band b,
                            int x,
                            int y)
        {
            double num = 0;
            double sum = 0;
            double sum2 = 0;

            for (int i = 0; i < dx.length; i++) {
                final double v = b.at(x + dx[i], y + dy[i]);
                num += tc[i] * v; // tc is centered
                sum += v;
                sum2 += v * v;
            }

            final double var = sum2 - ((sum * sum) / dx.length);

            if (var <= 1e-9) {
                return 0;
            }

            return num / (Math.sqrt(var) * tNorm);
        }

        /** Mean darkness in the notches of the X at (x, y). */
        double notchInk (Band b,
                         int x,
                         int y)
        {
            if (ndx.length == 0) {
                return 1;
            }

            double sum = 0;

            for (int i = 0; i < ndx.length; i++) {
                sum += b.at(x + ndx[i], y + ndy[i]);
            }

            return sum / ndx.length;
        }

        /**
         * Head at (x, y): bounds of the band ink under the head body, glyph made of the band ink
         * under the whole symbol (so that no stroke end is left to be taken for another symbol).
         */
        HeadInter createHead (Shape shape,
                              Band b,
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

                if (b.at(px, py) >= INK_DARK) {
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

            final Rectangle bounds = new Rectangle(
                    xMin,
                    yMin,
                    xMax - xMin + 1,
                    yMax - yMin + 1);

            for (int i = 0; i < wdx.length; i++) {
                final int px = x + wdx[i];
                final int py = y + wdy[i];

                if (b.at(px, py) >= LINE_DARK) { // Pale stroke ends too
                    pts.add(new int[] { px, py });
                    xMin = Math.min(xMin, px);
                    yMin = Math.min(yMin, py);
                    xMax = Math.max(xMax, px);
                    yMax = Math.max(yMax, py);
                }
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
                    bounds,
                    shape,
                    new HeadInter.Impacts(grade),
                    staff,
                    (double) pitch);
            head.setGlyph(glyph);

            return head;
        }
    }
}
