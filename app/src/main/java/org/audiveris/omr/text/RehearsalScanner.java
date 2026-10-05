//------------------------------------------------------------------------------------------------//
//                                                                                                //
//                                R e h e a r s a l S c a n n e r                                 //
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
import org.audiveris.omr.glyph.Glyph;
import org.audiveris.omr.glyph.GlyphFactory;
import org.audiveris.omr.glyph.Shape;
import org.audiveris.omr.run.Orientation;
import org.audiveris.omr.run.RunTable;
import org.audiveris.omr.run.RunTableFactory;
import org.audiveris.omr.sheet.Picture;
import org.audiveris.omr.sheet.Scale;
import org.audiveris.omr.sheet.Sheet;
import org.audiveris.omr.sheet.Staff;
import org.audiveris.omr.sheet.SystemInfo;
import org.audiveris.omr.sig.SIGraph;
import org.audiveris.omr.sig.inter.RehearsalInter;
import org.audiveris.omr.sig.inter.WordInter;
import org.audiveris.omr.sig.relation.Containment;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import ij.process.ByteProcessor;

import java.awt.Color;
import java.awt.Graphics2D;
import java.awt.Point;
import java.awt.Rectangle;
import java.awt.image.BufferedImage;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/**
 * Class <code>RehearsalScanner</code> finds the rehearsal marks printed in a rectangular frame
 * above a system, before the sheet OCR, so that neither the frame nor its text are read as part
 * of the other texts (a framed "C" read as a chord name, a frame side read as "$" in the chord
 * name below).
 * <p>
 * A frame is a glyph of the texts buffer drawn as a hollow rectangle: its four sides inked over
 * almost their whole length, its inside almost empty (the text inside is a separate glyph),
 * located above the first staff of a system.
 * The frame and its inside are erased from the texts buffer; the inside is OCR'd on its own and
 * becomes the text of a {@link RehearsalInter}.
 *
 * @author Hervé Bitteur
 */
public abstract class RehearsalScanner
{
    //~ Static fields/initializers -----------------------------------------------------------------

    private static final Constants constants = new Constants();

    private static final Logger logger = LoggerFactory.getLogger(RehearsalScanner.class);

    //~ Constructors -------------------------------------------------------------------------------

    private RehearsalScanner ()
    {
    }

    //~ Static Methods -----------------------------------------------------------------------------

    //-----------------//
    // buildRehearsals //
    //-----------------//
    /**
     * Read the text inside each frame of the system and create the rehearsal inters.
     *
     * @param system the system to process
     * @param frames the frames found in sheet
     */
    public static void buildRehearsals (SystemInfo system,
                                        List<Frame> frames)
    {
        final Sheet sheet = system.getSheet();

        for (Frame frame : frames) {
            if (frame.system() != system) {
                continue;
            }

            final Rectangle box = frame.glyph().getBounds();

            // Inside of the frame, frame pixels erased
            final ByteProcessor src = sheet.getPicture().getSource(Picture.SourceKey.BINARY);
            src.setRoi(box);
            final BufferedImage img = ((ByteProcessor) src.crop()).getBufferedImage();
            src.resetRoi();

            final Graphics2D g = img.createGraphics();
            g.setColor(Color.WHITE);
            frame.glyph().getRunTable().render(g, new Point(0, 0));
            g.dispose();

            final ByteProcessor buffer = new ByteProcessor(img);
            final List<TextLine> relativeLines = new BlockScanner(sheet).scanBuffer(
                    buffer,
                    sheet.getStub().getOcrLanguages(),
                    box.y);
            final List<TextLine> lines = new TextBuilder(system, Shape.TEXT).processBuffer(
                    buffer,
                    relativeLines,
                    box.getLocation());

            if (lines.size() != 1) {
                logger.info("{} text lines in rehearsal frame {}", lines.size(), box);
                continue;
            }

            final TextLine line = lines.get(0);
            line.getWords().forEach(w -> w.adjustFont());

            final Staff staff = system.getFirstStaff();
            final RehearsalInter rehearsal = new RehearsalInter(line.getConfidence(), box);
            rehearsal.setStaff(staff);

            final SIGraph sig = system.getSig();
            sig.addVertex(rehearsal);

            for (TextWord textWord : line.getWords()) {
                final WordInter word = new WordInter(textWord);
                word.setStaff(staff);
                sig.addVertex(word);
                sig.addEdge(rehearsal, word, new Containment());
            }

            rehearsal.setEnclosure(box); // Just to stick to the frame
            logger.info("{}", rehearsal);
        }
    }

    //------------//
    // findFrames //
    //------------//
    /**
     * Find the rehearsal frames in the texts buffer.
     *
     * @param sheet  the sheet
     * @param buffer the texts buffer (binarized)
     * @return the frames found, perhaps empty
     */
    public static List<Frame> findFrames (Sheet sheet,
                                          ByteProcessor buffer)
    {
        final Scale scale = sheet.getScale();
        final int minHeight = scale.toPixels(constants.minHeight);
        final int maxHeight = scale.toPixels(constants.maxHeight);
        final int band = Math.max(2, scale.toPixels(constants.sideBand));
        final RunTable table = new RunTableFactory(Orientation.VERTICAL).createTable(buffer);
        final List<Frame> frames = new ArrayList<>();

        for (Glyph glyph : GlyphFactory.buildGlyphs(table, null)) {
            final Rectangle box = glyph.getBounds();

            if ((box.height < minHeight) || (box.height > maxHeight)
                    || (box.width < box.height * constants.minWidthRatio.getValue())
                    || (box.width > box.height * constants.maxWidthRatio.getValue())) {
                continue;
            }

            if (!isHollowRectangle(glyph, band)) {
                continue;
            }

            final SystemInfo system = getSystemBelow(sheet, box);

            if (system != null) {
                frames.add(new Frame(glyph, system));
            }
        }

        return frames;
    }

    //----------------//
    // getSystemBelow //
    //----------------//
    /**
     * Report the system whose first staff lies just below the provided box.
     *
     * @return the system, or null if the box is not above the first staff of a system
     */
    private static SystemInfo getSystemBelow (Sheet sheet,
                                              Rectangle box)
    {
        final Point center = new Point(box.x + box.width / 2, box.y + box.height / 2);
        final SystemInfo system = sheet.getSystemManager().getSystemsOf(center).stream().max(
                Comparator.comparingInt(SystemInfo::getId)).orElse(null);

        if (system == null) {
            return null;
        }

        final int staffY = system.getFirstStaff().getFirstLine().yAt(center.x);

        return (box.y + box.height <= staffY) ? system : null;
    }

    //-------------------//
    // isHollowRectangle //
    //-------------------//
    /**
     * Check whether the glyph is drawn as a hollow rectangle.
     *
     * @param glyph the glyph to check
     * @param band  thickness of the band checked along each side
     * @return true if each side is inked over at least minSideRatio of its length and the inside
     *         is inked at most maxInsideRatio
     */
    private static boolean isHollowRectangle (Glyph glyph,
                                              int band)
    {
        final ByteProcessor buf = glyph.getRunTable().getBuffer();
        final int w = buf.getWidth();
        final int h = buf.getHeight();

        if ((w <= 2 * band) || (h <= 2 * band)) {
            return false;
        }

        int top = 0, bottom = 0, left = 0, right = 0, inside = 0;

        for (int x = 0; x < w; x++) {
            top += inked(buf, x, x + 1, 0, band) ? 1 : 0;
            bottom += inked(buf, x, x + 1, h - band, h) ? 1 : 0;
        }

        for (int y = 0; y < h; y++) {
            left += inked(buf, 0, band, y, y + 1) ? 1 : 0;
            right += inked(buf, w - band, w, y, y + 1) ? 1 : 0;
        }

        for (int y = band; y < h - band; y++) {
            for (int x = band; x < w - band; x++) {
                inside += (buf.get(x, y) == 0) ? 1 : 0;
            }
        }

        final double minSide = constants.minSideRatio.getValue();

        return (top >= minSide * w) && (bottom >= minSide * w) //
                && (left >= minSide * h) && (right >= minSide * h)
                && (inside <= constants.maxInsideRatio.getValue() * (w - 2 * band) * (h
                        - 2 * band));
    }

    //-------//
    // inked //
    //-------//
    private static boolean inked (ByteProcessor buf,
                                  int x0,
                                  int x1,
                                  int y0,
                                  int y1)
    {
        for (int y = y0; y < y1; y++) {
            for (int x = x0; x < x1; x++) {
                if (buf.get(x, y) == 0) {
                    return true;
                }
            }
        }

        return false;
    }

    //~ Inner Classes ------------------------------------------------------------------------------

    //-------//
    // Frame //
    //-------//
    /**
     * A rehearsal frame: the frame glyph and the system just below.
     *
     * @param glyph  the frame glyph (the text inside not included)
     * @param system the system whose first staff lies below the frame
     */
    public static record Frame(Glyph glyph, SystemInfo system)
    {
    }

    //-----------//
    // Constants //
    //-----------//
    private static class Constants
            extends ConstantSet
    {
        private final Scale.Fraction minHeight = new Scale.Fraction(
                1.5,
                "Minimum height of a rehearsal frame");

        private final Scale.Fraction maxHeight = new Scale.Fraction(
                5.0,
                "Maximum height of a rehearsal frame");

        private final Constant.Ratio minWidthRatio = new Constant.Ratio(
                0.5,
                "Minimum frame width, as a ratio of its height");

        private final Constant.Ratio maxWidthRatio = new Constant.Ratio(
                6.0,
                "Maximum frame width, as a ratio of its height");

        private final Scale.Fraction sideBand = new Scale.Fraction(
                0.25,
                "Thickness of the band checked along each frame side");

        private final Constant.Ratio minSideRatio = new Constant.Ratio(
                0.95,
                "Minimum inked part of each frame side");

        private final Constant.Ratio maxInsideRatio = new Constant.Ratio(
                0.1,
                "Maximum inked part of the frame inside (the text is another glyph)");
    }
}
