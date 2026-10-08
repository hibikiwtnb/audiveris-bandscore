//------------------------------------------------------------------------------------------------//
//                                                                                                //
//                                 H i H a t T e m p l a t e                                      //
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

import org.audiveris.omr.constant.Constant;
import org.audiveris.omr.constant.ConstantSet;
import org.audiveris.omr.glyph.Shape;
import org.audiveris.omr.score.KeyAgreement;
import org.audiveris.omr.sheet.Picture;
import org.audiveris.omr.sheet.Staff;
import org.audiveris.omr.sheet.SystemInfo;
import org.audiveris.omr.sig.SIGraph;
import org.audiveris.omr.sig.inter.HeadInter;
import org.audiveris.omr.sig.inter.Inter;
import org.audiveris.omr.sig.inter.PlayingInter;
import org.audiveris.omr.sig.inter.StemInter;
import org.audiveris.omr.sig.relation.HeadPlayingRelation;
import org.audiveris.omr.util.HorizontalSide;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import ij.process.ByteProcessor;

import java.awt.Point;
import java.awt.Rectangle;
import java.awt.image.BufferedImage;
import java.io.File;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import javax.imageio.ImageIO;

/**
 * Class <code>HiHatTemplate</code> finds the open (circle 'o') and closed (plus '+') playing signs
 * of a drum staff by matching book-specific templates above Hi-Hat stems/heads.
 */
public class HiHatTemplate
{
    //~ Static fields/initializers -----------------------------------------------------------------

    private static final Logger logger = LoggerFactory.getLogger(HiHatTemplate.class);

    private static final Constants constants = new Constants();

    /** Staff interline of the template images. */
    public static final int INTERLINE = CrossTemplate.INTERLINE;

    /** Minimum darkness to consider ink in the search window (avoid matching on blank paper). */
    private static final double MIN_INK = 0.05;

    /** Loaded templates, per template folder. */
    private static final Map<String, HiHatTemplate> loaded = new HashMap<>();

    //~ Instance fields ----------------------------------------------------------------------------

    private final Image openImage;

    private final Image closedImage;

    //~ Constructors -------------------------------------------------------------------------------

    private HiHatTemplate (Image openImage,
                           Image closedImage)
    {
        this.openImage = openImage;
        this.closedImage = closedImage;
    }

    //~ Methods ------------------------------------------------------------------------------------

    //-------//
    // match //
    //-------//
    /**
     * Match hi-hat open/closed marks in the given system, if a book template folder is configured.
     *
     * @param system the system to process
     */
    public static void match (SystemInfo system)
    {
        final String templateDir = NoteHeadsBuilder.getTemplateDir();

        if ((templateDir == null) || templateDir.isBlank()) {
            return;
        }

        final HiHatTemplate tpl = getLoaded(templateDir);

        if (tpl == null) {
            return;
        }

        tpl.lookup(system);
    }

    //-----------//
    // getLoaded //
    //-----------//
    /**
     * Get or load the hi-hat template from the specified folder.
     *
     * @param dir template directory path
     * @return the loaded template instance or null if not available
     */
    public static synchronized HiHatTemplate getLoaded (String dir)
    {
        if ((dir == null) || dir.isBlank()) {
            return null;
        }

        if (loaded.containsKey(dir)) {
            return loaded.get(dir);
        }

        final File folder = new File(dir);

        if (!folder.isDirectory()) {
            loaded.put(dir, null);
            return null;
        }

        final Image open = loadImage(new File(folder, "open.png"));
        final Image closed = loadImage(new File(folder, "closed.png"));

        if ((open == null) && (closed == null)) {
            loaded.put(dir, null);
            return null;
        }

        final HiHatTemplate tpl = new HiHatTemplate(open, closed);
        loaded.put(dir, tpl);

        return tpl;
    }

    //--------//
    // lookup //
    //--------//
    /**
     * Search for open/closed marks above hi-hat note heads in the system.
     *
     * @param system the containing system
     */
    public void lookup (SystemInfo system)
    {
        final ByteProcessor gray = system.getSheet().getPicture().getSource(Picture.SourceKey.GRAY);

        if (gray == null) {
            return;
        }

        final SIGraph sig = system.getSig();
        final Set<Point> matchedCenters = new HashSet<>();
        final double minGrade = constants.hihatMinGrade.getValue();
        final Set<Staff> drums = NoteHeadsBuilder.hintedDrumStaves(system);

        for (Staff staff : system.getStaves()) {
            if (!isDrumStaff(staff, drums)) {
                continue;
            }

            final int il = staff.getSpecificInterline();
            final Scaled openScaled = (openImage != null) ? openImage.scaledFor(il) : null;
            final Scaled closedScaled = (closedImage != null) ? closedImage.scaledFor(il) : null;

            if ((openScaled == null) && (closedScaled == null)) {
                continue;
            }

            // Create Band for the staff (lines erased)
            final int left = staff.getAbscissa(HorizontalSide.LEFT);
            final int right = staff.getAbscissa(HorizontalSide.RIGHT);
            final int x0 = Math.max(0, left - (2 * il));
            final int x1 = Math.min(gray.getWidth() - 1, right + (2 * il));
            final int top = Math.max(0, (int) Math.round(staff.getFirstLine().yAt(left) - (8 * il)));
            final int bot = Math.min(gray.getHeight() - 1,
                    (int) Math.round(staff.getLastLine().yAt(left) + (4 * il)));
            final CrossTemplate.Band band = new CrossTemplate.Band(gray, staff, x0, x1, top, bot);

            // Collect all cross heads on this staff, sorted top-to-bottom
            final List<HeadInter> candidateHeads = new ArrayList<>();

            for (Inter inter : sig.inters(staff, HeadInter.class)) {
                final HeadInter head = (HeadInter) inter;
                if ((head.getShape() == Shape.NOTEHEAD_CROSS)
                        && (head.getPlayingSign() == null)) {
                    candidateHeads.add(head);
                }
            }

            candidateHeads.sort(Comparator.comparingInt(h -> h.getBounds().y));

            for (HeadInter head : candidateHeads) {
                if (head.getPlayingSign() != null) {
                    continue;
                }

                int refX = (int) Math.round(head.getCenter().x);
                int refY = head.getBounds().y;

                final Set<StemInter> stems = head.getStems();
                if (!stems.isEmpty()) {
                    final StemInter stem = stems.iterator().next();

                    // If stem already has a head with a playing sign, skip
                    boolean stemHandled = false;
                    for (HeadInter sib : stem.getHeads()) {
                        if (sib.getPlayingSign() != null) {
                            stemHandled = true;
                            break;
                        }
                    }
                    if (stemHandled) {
                        continue;
                    }

                    if (stem.getBounds().y < head.getBounds().y) {
                        // Stem points UP: search above stem tip
                        refX = (int) Math.round(stem.getCenter().x);
                        refY = stem.getBounds().y;
                    }
                }

                final int yCenter = (int) Math.round(refY - (0.85 * il));
                final int xCenter = refX;
                final int dxRange = (int) Math.round(0.4 * il);
                final int dyRange = (int) Math.round(0.5 * il);

                double bestOpen = -1;
                Point bestOpenPt = null;
                double bestClosed = -1;
                Point bestClosedPt = null;

                for (int dy = -dyRange; dy <= dyRange; dy++) {
                    for (int dx = -dxRange; dx <= dxRange; dx++) {
                        final int cx = xCenter + dx;
                        final int cy = yCenter + dy;

                        if (openScaled != null) {
                            final double sc = openScaled.correlation(band, cx, cy);
                            if (sc > bestOpen) {
                                bestOpen = sc;
                                bestOpenPt = new Point(cx, cy);
                            }
                        }

                        if (closedScaled != null) {
                            final double sc = closedScaled.correlation(band, cx, cy);
                            if (sc > bestClosed) {
                                bestClosed = sc;
                                bestClosedPt = new Point(cx, cy);
                            }
                        }
                    }
                }

                final double bestGrade = Math.max(bestOpen, bestClosed);

                if (bestGrade >= minGrade) {
                    final boolean isOpen = bestOpen > bestClosed;
                    final Shape markShape = isOpen ? Shape.PLAYING_OPEN : Shape.PLAYING_CLOSED;
                    final Point markPt = isOpen ? bestOpenPt : bestClosedPt;
                    final int half = isOpen ? openScaled.half : closedScaled.half;

                    // Avoid duplicate playing mark at essentially the same location
                    boolean duplicate = false;
                    for (Point pt : matchedCenters) {
                        if (markPt.distance(pt) < (0.6 * il)) {
                            duplicate = true;
                            break;
                        }
                    }
                    if (duplicate) {
                        continue;
                    }

                    matchedCenters.add(markPt);
                    final PlayingInter playing = new PlayingInter(null, markShape, bestGrade);
                    playing.setBounds(new Rectangle(markPt.x - half, markPt.y - half,
                            (2 * half) + 1, (2 * half) + 1));
                    sig.addVertex(playing);

                    final HeadPlayingRelation rel = new HeadPlayingRelation();
                    rel.setOutGaps(0, 0, 0);
                    rel.setGrade(bestGrade);
                    sig.addEdge(head, playing, rel);

                    logger.info("Hi-Hat {} (grade {}) attached to head#{} at ({},{}) on staff#{}",
                            markShape, String.format("%.2f", bestGrade), head.getId(), markPt.x,
                            markPt.y, staff.getId());
                }
            }
        }
    }

    //-------------//
    // isDrumStaff //
    //-------------//
    private static boolean isDrumStaff (Staff staff,
                                        Set<Staff> drums)
    {
        return staff.isDrum() || drums.contains(staff) || KeyAgreement.isDrums(staff.getPart());
    }

    //-----------//
    // loadImage //
    //-----------//
    private static Image loadImage (File file)
    {
        if (!file.isFile()) {
            return null;
        }

        try {
            final BufferedImage ii = ImageIO.read(file);
            final int n = ii.getWidth();
            final float[][] ink = new float[n][n];

            for (int y = 0; y < n; y++) {
                for (int x = 0; x < n; x++) {
                    ink[y][x] = 1f - (ii.getRaster().getSample(x, y, 0) / 255f);
                }
            }

            logger.info("Loaded hi-hat template {} {}x{} from {}", file.getName(), n, n,
                    file.getAbsolutePath());
            return new Image(ink);
        } catch (Exception ex) {
            logger.warn("Cannot read template from {}", file.getAbsolutePath(), ex);
            return null;
        }
    }

    //~ Inner Classes ------------------------------------------------------------------------------

    //-----------//
    // Constants //
    //-----------//
    private static class Constants
            extends ConstantSet
    {
        private final Constant.Ratio hihatMinGrade = new Constant.Ratio(
                0.72,
                "Minimum correlation for hi-hat open/closed marks");
    }

    //-------//
    // Image //
    //-------//
    private static class Image
    {
        final float[][] ink;

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
    private static class Scaled
    {
        final int half;

        final int n;

        final int[] dx, dy;

        final double[] tc;

        final double tNorm;

        Scaled (float[][] ink,
                double s)
        {
            final int n0 = ink.length;
            final int h0 = n0 / 2;
            half = (int) Math.round(h0 * s);
            n = (2 * half) + 1;

            final List<int[]> m = new ArrayList<>();
            final List<Double> v = new ArrayList<>();

            for (int y = 0; y < n; y++) {
                for (int x = 0; x < n; x++) {
                    final int sx = Math.min(n0 - 1,
                            Math.max(0, (int) Math.round((x - half) / s) + h0));
                    final int sy = Math.min(n0 - 1,
                            Math.max(0, (int) Math.round((y - half) / s) + h0));

                    final double val = ink[sy][sx];
                    m.add(new int[] { x - half, y - half });
                    v.add(val);
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
        }

        double correlation (CrossTemplate.Band b,
                            int x,
                            int y)
        {
            double num = 0;
            double sum = 0;
            double sum2 = 0;

            for (int i = 0; i < dx.length; i++) {
                final double val = b.at(x + dx[i], y + dy[i]);
                num += tc[i] * val;
                sum += val;
                sum2 += val * val;
            }

            final double meanInk = sum / dx.length;

            if (meanInk < MIN_INK) {
                return 0;
            }

            final double var = sum2 - ((sum * sum) / dx.length);

            if (var <= 1e-9) {
                return 0;
            }

            return num / (Math.sqrt(var) * tNorm);
        }
    }
}
