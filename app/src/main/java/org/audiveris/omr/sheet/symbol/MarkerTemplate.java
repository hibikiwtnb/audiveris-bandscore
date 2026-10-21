//------------------------------------------------------------------------------------------------//
//                                                                                                //
//                                   M a r k e r T e m p l a t e                                   //
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
package org.audiveris.omr.sheet.symbol;

import org.audiveris.omr.glyph.Glyph;
import org.audiveris.omr.glyph.Shape;
import org.audiveris.omr.sheet.Picture;
import org.audiveris.omr.sheet.Sheet;
import org.audiveris.omr.sheet.Staff;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import ij.process.ByteProcessor;

import java.awt.geom.Point2D;
import java.awt.image.BufferedImage;
import java.io.File;
import java.util.HashMap;
import java.util.Map;

import javax.imageio.ImageIO;

/**
 * Class <code>MarkerTemplate</code> finds the segno and coda marks of a system with templates
 * made from the book itself.
 * <p>
 * The folder given by {@code NoteHeadsBuilder.templateDir} may hold <code>segno.png</code> and
 * <code>coda.png</code>: a box just holding the mark, drawn at an interline of {@link #INTERLINE}
 * pixels, as made by {@code tools/learn_template.py} (bandscore-omr-skill). The page is gray, not
 * binarized, and the mark stands above the first staff, so no line has to be erased.
 * <p>
 * The match is tried around the provided glyph, which is already segmented but may be only a part
 * of the mark. The best normalized correlation over both templates is kept when it reaches
 * {@link #MIN_GRADE}. Without template files the behavior is unchanged.
 */
public class MarkerTemplate
{
    //~ Static fields/initializers -----------------------------------------------------------------

    private static final Logger logger = LoggerFactory.getLogger(MarkerTemplate.class);

    /** Staff interline of the template images. */
    public static final int INTERLINE = 20;

    /** Minimum normalized correlation for a mark. */
    private static final double MIN_GRADE = 0.70;

    /** Loaded templates, per folder. */
    private static final Map<String, Templates> loaded = new HashMap<>();

    //~ Constructors -------------------------------------------------------------------------------

    private MarkerTemplate ()
    {
    }

    //~ Methods ------------------------------------------------------------------------------------

    //-------//
    // match //
    //-------//
    /**
     * Try to match a segno or coda mark around the provided glyph.
     *
     * @param sheet the sheet
     * @param glyph the glyph already segmented above the first staff
     * @param staff the first staff of the system
     * @param dir   the book template folder
     * @return the best match, or null
     */
    public static Match match (Sheet sheet,
                               Glyph glyph,
                               Staff staff,
                               String dir)
    {
        final Templates templates = getLoaded(dir);

        if (templates.isEmpty()) {
            return null;
        }

        final ByteProcessor gray = sheet.getPicture().getSource(Picture.SourceKey.GRAY);

        if (gray == null) {
            return null;
        }

        final int il = staff.getSpecificInterline();
        final double scale = (double) il / INTERLINE;
        final Point2D center = glyph.getCenter2D();
        final int radius = Math.max(2, (int) Math.round(0.8 * il));

        Match best = null;

        for (Image img : templates.images) {
            for (int dy = -radius; dy <= radius; dy++) {
                for (int dx = -radius; dx <= radius; dx++) {
                    final double grade = img.correlation(
                            gray,
                            center.getX() + dx,
                            center.getY() + dy,
                            scale);

                    if ((best == null) || (grade > best.grade)) {
                        best = new Match(img.shape, grade);
                    }
                }
            }
        }

        if ((best != null) && (best.grade >= MIN_GRADE)) {
            logger.info(
                    "Marker {} from template around {} at {},{} grade {}",
                    best.shape,
                    glyph.getId(),
                    (int) center.getX(),
                    (int) center.getY(),
                    String.format("%.3f", best.grade));

            return best;
        }

        return null;
    }

    //--------------//
    // hasTemplates //
    //--------------//
    public static boolean hasTemplates (String dir)
    {
        return !getLoaded(dir).isEmpty();
    }

    //-----------//
    // getLoaded //
    //-----------//
    private static synchronized Templates getLoaded (String dir)
    {
        if ((dir == null) || dir.isBlank()) {
            return Templates.EMPTY;
        }

        return loaded.computeIfAbsent(dir, d -> load(new File(d)));
    }

    //------//
    // load //
    //------//
    private static Templates load (File dir)
    {
        final Templates templates = new Templates();

        for (Shape shape : new Shape[] { Shape.SEGNO, Shape.CODA }) {
            final File file = new File(dir, shape.name().toLowerCase() + ".png");

            if (!file.isFile()) {
                continue;
            }

            try {
                final BufferedImage img = ImageIO.read(file);
                final int w = img.getWidth();
                final int h = img.getHeight();
                final float[][] ink = new float[h][w];

                for (int y = 0; y < h; y++) {
                    for (int x = 0; x < w; x++) {
                        ink[y][x] = 1f - (img.getRaster().getSample(x, y, 0) / 255f);
                    }
                }

                templates.images.add(new Image(shape, ink));
                logger.info("Marker template {} {}x{} from {}", shape, w, h, dir);
            } catch (Exception ex) {
                logger.warn("Cannot read {}", file, ex);
            }
        }

        return templates;
    }

    //~ Inner Classes ------------------------------------------------------------------------------

    //--------//
    // Match //
    //--------//
    /** Result of a template match. */
    public static class Match
    {
        public final Shape shape;

        public final double grade;

        Match (Shape shape,
               double grade)
        {
            this.shape = shape;
            this.grade = grade;
        }
    }

    //-----------//
    // Templates //
    //-----------//
    private static class Templates
    {
        static final Templates EMPTY = new Templates();

        final java.util.List<Image> images = new java.util.ArrayList<>();

        boolean isEmpty ()
        {
            return images.isEmpty();
        }
    }

    //-------//
    // Image //
    //-------//
    private static class Image
    {
        final Shape shape;

        final int width;

        final int height;

        final float[][] ink;

        Image (Shape shape,
               float[][] ink)
        {
            this.shape = shape;
            this.ink = ink;
            this.height = ink.length;
            this.width = ink[0].length;
        }

        double correlation (ByteProcessor gray,
                            double cx,
                            double cy,
                            double scale)
        {
            final int n = width * height;
            double sumT = 0;
            double sumP = 0;
            double sumTT = 0;
            double sumPP = 0;
            double sumTP = 0;

            for (int ty = 0; ty < height; ty++) {
                final int py = (int) Math.round(cy + ((ty - (height / 2.0)) * scale));

                for (int tx = 0; tx < width; tx++) {
                    final int px = (int) Math.round(cx + ((tx - (width / 2.0)) * scale));

                    if ((px < 0) || (py < 0) || (px >= gray.getWidth()) || (py >= gray.getHeight())) {
                        return -1;
                    }

                    final double t = ink[ty][tx];
                    final double p = 1 - (gray.getPixel(px, py) / 255.0);

                    sumT += t;
                    sumP += p;
                    sumTT += t * t;
                    sumPP += p * p;
                    sumTP += t * p;
                }
            }

            final double num = (n * sumTP) - (sumT * sumP);
            final double den = Math.sqrt(
                    ((n * sumTT) - (sumT * sumT)) * ((n * sumPP) - (sumP * sumP)));

            return (den == 0) ? -1 : (num / den);
        }
    }
}
