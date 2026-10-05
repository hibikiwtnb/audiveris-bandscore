//------------------------------------------------------------------------------------------------//
//                                                                                                //
//                                      C h o r d F l a t s                                       //
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
package org.audiveris.omr.text;

import org.audiveris.omr.constant.Constant;
import org.audiveris.omr.constant.ConstantSet;
import org.audiveris.omr.sheet.Picture;
import org.audiveris.omr.sheet.Sheet;
import org.audiveris.omr.sheet.note.NoteHeadsBuilder;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import ij.process.ByteProcessor;

import java.awt.Rectangle;
import java.awt.image.BufferedImage;
import java.io.File;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import javax.imageio.ImageIO;

/**
 * Class <code>ChordFlats</code> finds the flats of chord names that the OCR misses: the OCR
 * reads the small raised flat of some fonts as nothing ("D" for D♭) or as math marks ("E$").
 * <p>
 * It works only when the song opens in a flat key ({@link Constants#openingFifths}, given by
 * the user in the hints) and the template folder of the book (NoteHeadsBuilder.templateDir)
 * holds chord templates: <code>chord_Ab.png</code>, <code>chord_Bb.png</code>, ... a square just
 * holding the root letter and its flat, drawn at a root letter height of {@link #CAP_HEIGHT}
 * pixels (ink dark), made by <code>tools/learn_template.py</code> (bandscore-omr-skill).
 * <p>
 * For every root letter read by the OCR (first char of a word, or char after "/") with a template,
 * the whole template is aligned on the gray page at the letter (the letter fixes the position),
 * then only its flat part (the columns right of the letter) is correlated: the letter would match
 * a plain letter as well. A correlation of at least {@link Constants#minFlatGrade} gives a flat:
 * the chars the OCR read over the flat are replaced by "b". Otherwise the OCR word is left as is.
 */
public abstract class ChordFlats
{
    //~ Static fields/initializers -----------------------------------------------------------------

    private static final Constants constants = new Constants();

    private static final Logger logger = LoggerFactory.getLogger(ChordFlats.class);

    /** Root letter height in the template images. */
    public static final int CAP_HEIGHT = 20;

    /** Gray level below which a pixel is ink (to find the root letter). */
    private static final int INK_GRAY = 160;

    /** Loaded templates per folder, per root letter (empty map when none). */
    private static final Map<String, Map<Character, Template>> loaded = new HashMap<>();

    //~ Constructors -------------------------------------------------------------------------------

    private ChordFlats ()
    {
    }

    //~ Static Methods -----------------------------------------------------------------------------

    //-------//
    // apply //
    //-------//
    /**
     * Restore the flats missed by the OCR in the provided lines.
     *
     * @param sheet the sheet
     * @param lines the text lines (sheet coordinates), modified in place
     */
    public static void apply (Sheet sheet,
                              List<TextLine> lines)
    {
        if (constants.openingFifths.getValue() >= 0) {
            return;
        }

        final Map<Character, Template> templates = getLoaded(NoteHeadsBuilder.getTemplateDir());

        if (templates.isEmpty()) {
            return;
        }

        final ByteProcessor gray = sheet.getPicture().getSource(Picture.SourceKey.GRAY);

        if (gray == null) {
            logger.warn("No gray image, chord flats not checked");
            return;
        }

        for (TextLine line : lines) {
            boolean modified = false;

            for (TextWord word : line.getWords()) {
                modified |= processWord(word, templates, gray);
            }

            if (modified) {
                line.invalidateCache();
            }
        }
    }

    //-----------//
    // getLoaded //
    //-----------//
    private static synchronized Map<Character, Template> getLoaded (String dir)
    {
        if ((dir == null) || dir.isBlank()) {
            return Map.of();
        }

        return loaded.computeIfAbsent(dir, d -> load(new File(d)));
    }

    //------//
    // load //
    //------//
    private static Map<Character, Template> load (File dir)
    {
        final Map<Character, Template> map = new HashMap<>();

        for (char root : "ABCDEFG".toCharArray()) {
            final File file = new File(dir, "chord_" + root + "b.png");

            if (!file.isFile()) {
                continue;
            }

            try {
                final BufferedImage img = ImageIO.read(file);
                final int n = img.getWidth();
                final float[][] ink = new float[n][n];

                for (int y = 0; y < n; y++) {
                    for (int x = 0; x < n; x++) {
                        ink[y][x] = 1f - (img.getRaster().getSample(x, y, 0) / 255f);
                    }
                }

                map.put(root, new Template(ink));
                logger.info("Chord template {}b {}x{} from {}", root, n, n, dir);
            } catch (Exception ex) {
                logger.warn("Cannot read {}", file, ex);
            }
        }

        return map;
    }

    //-------------//
    // processWord //
    //-------------//
    private static boolean processWord (TextWord word,
                                        Map<Character, Template> templates,
                                        ByteProcessor gray)
    {
        final List<TextChar> chars = word.getChars();
        boolean modified = false;

        for (int i = 0; i < chars.size(); i++) {
            final String v = chars.get(i).getValue();
            final boolean rootPlace = (i == 0) || "/".equals(chars.get(i - 1).getValue());

            if (!rootPlace || (v == null) || (v.length() != 1)) {
                continue;
            }

            final Template template = templates.get(v.charAt(0));
            final Rectangle box = chars.get(i).getBounds();

            if ((template == null) || (box == null)) {
                continue;
            }

            // The OCR box of a lone letter may be far off (narrow and high): the letter is the
            // largest ink piece it touches
            final Rectangle root = letterInk(gray, box);

            if ((root == null) || (root.height < 4)) {
                continue;
            }

            final Rectangle flat = template.findFlat(gray, root);

            if (flat == null) {
                continue;
            }

            // Chars read over the flat are replaced by it
            while ((i + 1 < chars.size()) && (chars.get(i + 1).getBounds() != null)
                    && (chars.get(i + 1).getBounds().getCenterX() <= flat.x + flat.width)) {
                chars.remove(i + 1);
            }

            chars.add(i + 1, new TextChar(flat, "b"));
            modified = true;
        }

        if (modified) {
            final StringBuilder sb = new StringBuilder();
            chars.forEach(c -> sb.append(c.getValue()));

            if (!sb.toString().equals(word.getValue())) {
                logger.info("Chord flat: {} -> {}", word.getValue(), sb);
            }

            word.setValue(sb.toString());
            word.setBounds(TextItem.boundsOf(chars));
        }

        return modified;
    }

    //-----------//
    // letterInk //
    //-----------//
    /**
     * Report the bounds of the largest ink piece (gray below INK_GRAY) touching the OCR box,
     * searched within one box height around it.
     */
    private static Rectangle letterInk (ByteProcessor gray,
                                        Rectangle box)
    {
        final int h = box.height;
        final int ax = Math.max(0, box.x - h);
        final int ay = Math.max(0, box.y - h);
        final int aw = Math.min(gray.getWidth(), box.x + box.width + h) - ax;
        final int ah = Math.min(gray.getHeight(), box.y + box.height + h) - ay;

        if ((aw <= 0) || (ah <= 0)) {
            return null;
        }

        final boolean[][] seen = new boolean[ah][aw];
        final java.util.ArrayDeque<int[]> queue = new java.util.ArrayDeque<>();
        Rectangle best = null;
        int bestCount = 0;

        for (int y = box.y; y < box.y + box.height; y++) {
            for (int x = box.x; x < box.x + box.width; x++) {
                final int sx = x - ax;
                final int sy = y - ay;

                if ((sx < 0) || (sy < 0) || (sx >= aw) || (sy >= ah) || seen[sy][sx]
                        || (gray.get(x, y) >= INK_GRAY)) {
                    continue;
                }

                // One ink piece, 8-connected, within the area
                seen[sy][sx] = true;
                queue.add(new int[] { sx, sy });
                int count = 0;
                int x0 = sx, y0 = sy, x1 = sx, y1 = sy;

                while (!queue.isEmpty()) {
                    final int[] p = queue.poll();
                    count++;
                    x0 = Math.min(x0, p[0]);
                    y0 = Math.min(y0, p[1]);
                    x1 = Math.max(x1, p[0]);
                    y1 = Math.max(y1, p[1]);

                    for (int dy = -1; dy <= 1; dy++) {
                        for (int dx = -1; dx <= 1; dx++) {
                            final int nx = p[0] + dx;
                            final int ny = p[1] + dy;

                            if ((nx >= 0) && (ny >= 0) && (nx < aw) && (ny < ah) && !seen[ny][nx]
                                    && (gray.get(nx + ax, ny + ay) < INK_GRAY)) {
                                seen[ny][nx] = true;
                                queue.add(new int[] { nx, ny });
                            }
                        }
                    }
                }

                if (count > bestCount) {
                    bestCount = count;
                    best = new Rectangle(ax + x0, ay + y0, x1 - x0 + 1, y1 - y0 + 1);
                }
            }
        }

        return best;
    }

    //~ Inner Classes ------------------------------------------------------------------------------

    //----------//
    // Template //
    //----------//
    /**
     * A root letter and its flat, at CAP_HEIGHT.
     */
    private static class Template
    {
        final float[][] ink;

        final int n;

        /** First column of the letter. */
        final int letterLeft;

        /** First column of the flat part (the blank column after the letter). */
        final int flatLeft;

        /** First row of the letter (its cap top). */
        final int letterTop;

        Template (float[][] ink)
        {
            this.ink = ink;
            n = ink.length;

            final float[] colMax = new float[n];
            float top = 0;

            for (int y = 0; y < n; y++) {
                for (int x = 0; x < n; x++) {
                    colMax[x] = Math.max(colMax[x], ink[y][x]);
                    top = Math.max(top, ink[y][x]);
                }
            }

            int x = 0;

            while ((x < n) && (colMax[x] <= 0.5 * top)) {
                x++;
            }

            letterLeft = x;

            while ((x < n) && (colMax[x] > 0.15 * top)) {
                x++;
            }

            flatLeft = x;

            int y = 0;

            outer:
            for (; y < n; y++) {
                for (int xx = letterLeft; xx < flatLeft; xx++) {
                    if (ink[y][xx] > 0.5 * top) {
                        break outer;
                    }
                }
            }

            letterTop = y;
        }

        /**
         * Align the template on the root letter and check its flat part.
         *
         * @param gray the gray page
         * @param root the root letter bounds, as read by the OCR
         * @return the flat bounds on the page, or null if no flat
         */
        Rectangle findFlat (ByteProcessor gray,
                            Rectangle root)
        {
            final double s = (double) root.height / CAP_HEIGHT;
            final int m = (int) Math.round(n * s);
            final float[][] t = new float[m][m];

            for (int y = 0; y < m; y++) {
                for (int x = 0; x < m; x++) {
                    t[y][x] = ink[Math.min(n - 1, (int) (y / s))][Math.min(n - 1, (int) (x / s))];
                }
            }

            final int fl = (int) Math.round(flatLeft * s);
            final int r = Math.max(2, (int) Math.round(0.3 * root.height));
            final int x0 = root.x - (int) Math.round(letterLeft * s);
            final int y0 = root.y - (int) Math.round(letterTop * s);

            // Page darkness around the search area
            final int px = x0 - r;
            final int py = y0 - r;
            final int pw = m + 2 * r;
            final float[][] page = new float[pw][pw];

            for (int y = 0; y < pw; y++) {
                for (int x = 0; x < pw; x++) {
                    page[y][x] = 1f - (median3(gray, px + x, py + y) / 255f);
                }
            }

            // Alignment by the whole template
            double best = -1;
            int bx = 0, by = 0;

            for (int dy = 0; dy <= 2 * r; dy++) {
                for (int dx = 0; dx <= 2 * r; dx++) {
                    final double c = correlation(t, page, dx, dy, 0, m);

                    if (c > best) {
                        best = c;
                        bx = dx;
                        by = dy;
                    }
                }
            }

            // Decision by the flat part only
            final double flat = correlation(t, page, bx, by, fl, m);

            if (flat < constants.minFlatGrade.getValue()) {
                return null;
            }

            // Flat bounds: the ink of the template flat part
            int xMin = Integer.MAX_VALUE, yMin = Integer.MAX_VALUE;
            int xMax = Integer.MIN_VALUE, yMax = Integer.MIN_VALUE;

            for (int y = 0; y < m; y++) {
                for (int x = fl; x < m; x++) {
                    if (t[y][x] >= 0.3) {
                        xMin = Math.min(xMin, x);
                        yMin = Math.min(yMin, y);
                        xMax = Math.max(xMax, x);
                        yMax = Math.max(yMax, y);
                    }
                }
            }

            if (xMin > xMax) {
                return null;
            }

            return new Rectangle(
                    px + bx + xMin,
                    py + by + yMin,
                    xMax - xMin + 1,
                    yMax - yMin + 1);
        }

        /** Normalized correlation of template columns [c0, c1) and page at (dx, dy). */
        private static double correlation (float[][] t,
                                           float[][] page,
                                           int dx,
                                           int dy,
                                           int c0,
                                           int c1)
        {
            int count = 0;
            double st = 0, sp = 0, stt = 0, spp = 0, stp = 0;

            for (int y = 0; y < t.length; y++) {
                for (int x = c0; x < c1; x++) {
                    final double a = t[y][x];
                    final double b = page[dy + y][dx + x];
                    st += a;
                    sp += b;
                    stt += a * a;
                    spp += b * b;
                    stp += a * b;
                    count++;
                }
            }

            final double vt = stt - st * st / count;
            final double vp = spp - sp * sp / count;

            if ((vt <= 1e-9) || (vp <= 1e-9)) {
                return 0;
            }

            return (stp - st * sp / count) / Math.sqrt(vt * vp);
        }

        /** Median gray level of the 3x3 neighborhood (scan speckles out). */
        private static int median3 (ByteProcessor image,
                                    int x,
                                    int y)
        {
            final int[] v = new int[9];
            int k = 0;

            for (int dy = -1; dy <= 1; dy++) {
                for (int dx = -1; dx <= 1; dx++) {
                    final int xx = Math.min(Math.max(x + dx, 0), image.getWidth() - 1);
                    final int yy = Math.min(Math.max(y + dy, 0), image.getHeight() - 1);
                    v[k++] = image.get(xx, yy);
                }
            }

            java.util.Arrays.sort(v);

            return v[4];
        }
    }

    //-----------//
    // Constants //
    //-----------//
    private static class Constants
            extends ConstantSet
    {
        private final Constant.Integer openingFifths = new Constant.Integer(
                "Fifths",
                0,
                "Opening key of the song (negative: flats), given in the hints;"
                        + " chord flats are checked by the book templates in a flat key only");

        private final Constant.Ratio minFlatGrade = new Constant.Ratio(
                0.55,
                "Minimum correlation of the flat part of a chord template");
    }
}
