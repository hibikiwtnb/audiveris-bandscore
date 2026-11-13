//------------------------------------------------------------------------------------------------//
//                                                                                                //
//                                     S h e e t S c a n n e r                                    //
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

import org.audiveris.omr.OMR;
import org.audiveris.omr.constant.Constant;
import org.audiveris.omr.constant.ConstantSet;
import org.audiveris.omr.glyph.Glyph;
import org.audiveris.omr.glyph.GlyphFactory;
import org.audiveris.omr.glyph.ShapeSet;
import org.audiveris.omr.image.ImageUtil;
import org.audiveris.omr.image.Template;
import org.audiveris.omr.run.Orientation;
import org.audiveris.omr.run.RunTable;
import org.audiveris.omr.run.RunTableFactory;
import org.audiveris.omr.sheet.PageCleaner;
import org.audiveris.omr.sheet.Picture;
import org.audiveris.omr.sheet.Scale;
import org.audiveris.omr.sheet.Sheet;
import org.audiveris.omr.sheet.Staff;
import org.audiveris.omr.sheet.StaffManager;
import org.audiveris.omr.sheet.SystemInfo;
import org.audiveris.omr.sheet.ui.ImageView;
import org.audiveris.omr.sheet.ui.PixelBoard;
import org.audiveris.omr.sheet.ui.ScrollImageView;
import org.audiveris.omr.sig.SIGraph;
import org.audiveris.omr.sig.inter.HeadInter;
import org.audiveris.omr.sig.inter.Inter;
import org.audiveris.omr.sig.inter.LedgerInter;
import org.audiveris.omr.ui.BoardsPane;
import org.audiveris.omr.util.HorizontalSide;
import org.audiveris.omr.util.StopWatch;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import ij.process.ByteProcessor;

import java.awt.BasicStroke;
import java.awt.Color;
import java.awt.Graphics2D;
import java.awt.Point;
import java.awt.Rectangle;
import java.awt.Stroke;
import java.awt.geom.Area;
import java.awt.image.BufferedImage;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;

/**
 * Class <code>SheetScanner</code> runs OCR on the whole sheet, where good inters and
 * staves core areas have been blanked.
 * <p>
 * Tesseract is used in MULTI_BLOCK layout mode, meaning that the sheet may contain several blocks
 * of text.
 * <p>
 * The raw OCR output will later be processed at system level by dedicated TextBuilder instances.
 *
 * @author Hervé Bitteur
 */
public class SheetScanner
{
    //~ Static fields/initializers -----------------------------------------------------------------

    private static final Constants constants = new Constants();

    private static final Logger logger = LoggerFactory.getLogger(SheetScanner.class);

    //~ Instance fields ----------------------------------------------------------------------------

    /** Related sheet. */
    private final Sheet sheet;

    /** Buffer used by OCR. */
    private ByteProcessor buffer;

    /** Rehearsal frames found, erased from OCR buffer. */
    private List<RehearsalScanner.Frame> rehearsalFrames = new ArrayList<>();

    //~ Constructors -------------------------------------------------------------------------------

    /**
     * Creates a new <code>TextPageScanner</code> object.
     *
     * @param sheet the sheet to process
     */
    public SheetScanner (Sheet sheet)
    {
        this.sheet = sheet;
    }

    //~ Methods ------------------------------------------------------------------------------------

    //-----------//
    // getBuffer //
    //-----------//
    /**
     * @return the buffer
     */
    public ByteProcessor getBuffer ()
    {
        return buffer;
    }

    //--------------------//
    // getRehearsalFrames //
    //--------------------//
    /**
     * @return the rehearsal frames found (erased from the OCR buffer)
     */
    public List<RehearsalScanner.Frame> getRehearsalFrames ()
    {
        return rehearsalFrames;
    }

    //---------------//
    // getCleanImage //
    //---------------//
    private BufferedImage getCleanImage ()
    {
        Picture picture = sheet.getPicture();
        ByteProcessor buf = picture.getSource(Picture.SourceKey.NO_STAFF);

        BufferedImage img = buf.getBufferedImage();
        buffer = new ByteProcessor(img);

        final Graphics2D g = img.createGraphics();
        TextsCleaner cleaner = new TextsCleaner(buffer, g, sheet);
        cleaner.eraseInters();

        // Rehearsal frames, with the text inside, are read apart
        rehearsalFrames = RehearsalScanner.findFrames(sheet, buffer);
        g.setColor(Color.WHITE);
        rehearsalFrames.forEach(f -> g.fill(f.glyph().getBounds()));

        // Display for visual check?
        if (constants.displayTexts.isSet() && (OMR.gui != null)) {
            sheet.getStub().getAssembly().addViewTab(
                    "Texts",
                    new ScrollImageView(sheet, new ImageView(img)
                    {
                        @Override
                        protected void renderItems (Graphics2D g)
                        {
                            sheet.renderItems(g); // Apply registered sheet renderers
                        }
                    }),
                    new BoardsPane(new PixelBoard(sheet)));
        }

        // Save a copy on disk?
        if (constants.saveTextsBuffer.isSet()) {
            ImageUtil.saveOnDisk(img, sheet.getId(), "text");
        }

        return img;
    }

    //-----------//
    // scanSheet //
    //-----------//
    /**
     * Get a clean image of whole sheet and run OCR on it.
     *
     * @return the list of OCR'd lines found and filtered
     */
    public List<TextLine> scanSheet ()
    {
        final StopWatch watch = new StopWatch("scanSheet");

        try {
            // Get clean sheet image
            watch.start("getCleanImage");
            final BufferedImage image = getCleanImage(); // This also sets buffer member

            // Perform OCR on whole image
            final String languages = sheet.getStub().getOcrLanguages();
            logger.debug("scanSheet lan:{} on {}", languages, sheet);
            watch.start("OCR recognize");

            return OcrUtil.scan(image, OCR.LayoutMode.MULTI_BLOCK, languages, sheet, sheet.getId());
        } finally {
            if (constants.printWatch.isSet()) {
                watch.print();
            }
        }
    }

    //------------//
    // scanStaves //
    //------------//
    /**
     * Run OCR on the inside of the staves, which {@link #scanSheet()} erases, to catch a
     * text printed within the staff lines (like "Add Sequenced Synth." in an empty measure).
     * <p>
     * Staff lines are kept, so the spelling is approximate. A line is kept only if it lies within
     * the staff lines and contains a run of several letters, since notes give no such word.
     * The letters that look like notes (o, d, b, p, q) are ignored in this count, and the line
     * OCR confidence must be high enough.
     * For a kept line, the stem-less heads found on its letters are removed and its pixels are
     * put back into the buffer, for the words glyphs.
     * To be called after {@link #scanSheet()}.
     *
     * @return the text lines found within staves
     */
    public List<TextLine> scanStaves ()
    {
        final List<TextLine> kept = new ArrayList<>();

        if (!constants.scanStaves.isSet() || (buffer == null)) {
            return kept;
        }

        final Picture picture = sheet.getPicture();
        final ByteProcessor binary = picture.getSource(Picture.SourceKey.BINARY);
        final int margin = sheet.getScale().getInterline();
        final Area outside = new Area(new Rectangle(0, 0, binary.getWidth(), binary.getHeight()));
        final List<Staff> staves = new ArrayList<>();

        for (SystemInfo system : sheet.getSystems()) {
            for (Staff staff : system.getStaves()) {
                if (!staff.isTablature()) {
                    staves.add(staff);
                    outside.subtract(StaffManager.getCoreArea(staff, 0, margin));
                }
            }
        }

        if (staves.isEmpty()) {
            return kept;
        }

        final BufferedImage img = new ByteProcessor(binary.getBufferedImage()).getBufferedImage();
        final Graphics2D g = img.createGraphics();
        g.setColor(Color.WHITE);
        g.fill(outside);
        g.dispose();

        final List<TextLine> lines = OcrUtil.scan(
                img,
                OCR.LayoutMode.MULTI_BLOCK,
                sheet.getStub().getOcrLanguages(),
                sheet,
                sheet.getId() + "-staves");
        final ByteProcessor noStaff = picture.getSource(Picture.SourceKey.NO_STAFF);
        // Letters that look like a note (a ring, with or without a stem) do not count
        final String noteLike = "[" + constants.noteLikeLetters.getValue() + "]";
        final Pattern letterRun = Pattern.compile(
                "\\p{L}{" + constants.minStaffWordLetters.getValue() + ",}");

        for (TextLine line : lines) {
            final Rectangle box = line.getBounds();
            final Staff staff = staffAround(staves, box);

            // Notes can give formula-like garbage ("$b\\frac{}$"), never a run of letters
            final Double conf = line.getConfidence();

            if ((staff == null) || (conf == null) || (conf < constants.minStaffLineConfidence
                    .getValue()) || line.getValue().contains("$") || line.getWords().stream()
                    .noneMatch(
                            w -> letterRun.matcher(w.getValue().replaceAll(noteLike, "")).find())) {
                continue;
            }

            // Heads found on the letters
            int heads = 0;

            for (Inter inter : staff.getSystem().getSig().inters(HeadInter.class)) {
                if (ShapeSet.StemLessHeads.contains(inter.getShape()) && box.contains(
                        inter.getCenter())) {
                    inter.remove();
                    heads++;
                }
            }

            // Pixels for the words glyphs
            final Rectangle clip = box.intersection(
                    new Rectangle(0, 0, buffer.getWidth(), buffer.getHeight()));

            for (int y = clip.y; y < (clip.y + clip.height); y++) {
                for (int x = clip.x; x < (clip.x + clip.width); x++) {
                    buffer.set(x, y, (noStaff.get(x, y) < 127) ? 0 : 255);
                }
            }

            logger.info(
                    "Staff#{} text within staff lines \"{}\", {} stem-less heads removed",
                    staff.getId(),
                    line.getValue(),
                    heads);
            kept.add(line);
        }

        return kept;
    }

    //-------------//
    // staffAround //
    //-------------//
    /**
     * Report the staff whose lines embrace the center of the provided box, if any.
     */
    private static Staff staffAround (List<Staff> staves,
                                      Rectangle box)
    {
        final double x = box.getCenterX();
        final double y = box.getCenterY();

        for (Staff staff : staves) {
            if ((x >= staff.getAbscissa(HorizontalSide.LEFT)) && (x <= staff.getAbscissa(
                    HorizontalSide.RIGHT)) && (y >= staff.getFirstLine().yAt(x)) && (y <= staff
                            .getLastLine().yAt(x))) {
                return staff;
            }
        }

        return null;
    }

    //~ Inner Classes ------------------------------------------------------------------------------

    //-----------//
    // Constants //
    //-----------//
    private static class Constants
            extends ConstantSet
    {
        private final Constant.Boolean printWatch = new Constant.Boolean(
                false,
                "Should we print out the stop watch?");

        private final Constant.Boolean displayTexts = new Constant.Boolean(
                false,
                "Should we display the texts image?");

        private final Constant.Boolean saveTextsBuffer = new Constant.Boolean(
                false,
                "Should we save texts buffer on disk?");

        private final Constant.Boolean scanStaves = new Constant.Boolean(
                false, // Off: one more OCR request per sheet, whole notes come from a template
                "Should we also run OCR on the inside of staves?");

        private final Constant.String noteLikeLetters = new Constant.String(
                "oOdbpq0",
                "Characters ignored in a text found within staff lines (they look like notes)");

        private final Constant.Integer minStaffWordLetters = new Constant.Integer(
                "letters",
                4,
                "Minimum run of (not note-like) letters to accept a text line within staff lines");

        private final Constant.Ratio minStaffLineConfidence = new Constant.Ratio(
                0.8,
                "Minimum OCR confidence to accept a text line within staff lines");

        private final Scale.Fraction staffHorizontalMargin = new Scale.Fraction(
                0.25,
                "Horizontal margin around staff core area");

        private final Scale.Fraction staffVerticalMargin = new Scale.Fraction(
                0.25,
                "Vertical margin around staff core area");
    }

    //--------------//
    // TextsCleaner //
    //--------------//
    /**
     * Class <code>TextsCleaner</code> erases shapes to prepare texts retrieval.
     */
    private static class TextsCleaner
            extends PageCleaner
    {
        /** Scale-dependent parameters. */
        private final Parameters params;

        /**
         * Creates a new <code>TextsCleaner</code> object.
         *
         * @param buffer page buffer
         * @param g      graphics context on buffer
         * @param sheet  related sheet
         */
        TextsCleaner (ByteProcessor buffer,
                      Graphics2D g,
                      Sheet sheet)
        {
            super(buffer, g, sheet);
            params = new Parameters(sheet.getScale());
        }

        //-------------------//
        // eraseBorderGlyphs //
        //-------------------//
        /**
         * Erase from text image the glyphs that intersect or touch a staff core area.
         * <p>
         * (We also tried to remove too small glyphs, but this led to poor recognition by OCR)
         *
         * @param glyphs all the glyph instances in image
         * @param cores  all staves cores
         */
        private void eraseBorderGlyphs (List<Glyph> glyphs,
                                        List<Area> cores)
        {
            for (Glyph glyph : glyphs) {
                // Check position WRT staves cores
                Rectangle glyphBox = glyph.getBounds();
                glyphBox.grow(1, 1); // To catch touching glyphs (on top of intersecting ones)

                for (Area core : cores) {
                    if (core.intersects(glyphBox)) {
                        glyph.getRunTable().render(g, glyph.getTopLeft());

                        break;
                    }
                }
            }
        }

        //-------------//
        // eraseInters //
        //-------------//
        /**
         * Erase from image graphics all instances of good inter instances.
         */
        public void eraseInters ()
        {
            List<Area> cores = new ArrayList<>();

            for (SystemInfo system : sheet.getSystems()) {
                final SIGraph sig = system.getSig();
                final List<Inter> erased = new ArrayList<>();

                for (Inter inter : sig.vertexSet()) {
                    if (!inter.isRemoved()) {
                        if (canHide(inter)) {
                            erased.add(inter);
                        }
                    }
                }

                // Erase the inters
                for (Inter inter : erased) {
                    inter.accept(this);
                }

                // Erase the core area of each staff
                for (Staff staff : system.getStaves()) {
                    Area core = StaffManager.getCoreArea(staff, params.hMargin, params.vMargin);
                    cores.add(core);
                    ///staff.addAttachment("core", core); // Just for visual check
                    g.fill(core);
                }
            }

            // Binarize
            buffer.threshold(127);

            // Build all glyphs out of buffer and erase those that intersect a staff core area
            RunTable table = new RunTableFactory(Orientation.VERTICAL).createTable(buffer);
            List<Glyph> glyphs = GlyphFactory.buildGlyphs(table, null);
            eraseBorderGlyphs(glyphs, cores);
        }

        //-------//
        // visit //
        //-------//
        @Override
        public void visit (HeadInter inter)
        {
            final Template template = inter.getTemplate();
            final Rectangle tplBox = template.getBounds(inter.getBounds());

            // Use underlying glyph (enlarged)
            final List<Point> fores = template.getForegroundPixels(tplBox, buffer, true);

            // Erase foreground pixels
            for (final Point p : fores) {
                g.fillRect(tplBox.x + p.x, tplBox.y + p.y, 1, 1);
            }
        }

        //-------//
        // visit //
        //-------//
        @Override
        public void visit (LedgerInter ledger)
        {
            // Thicken the ledgerline 1 pixel above & 1 pixel below
            final Stroke oldStroke = g.getStroke();
            float thickness = (float) ledger.getThickness();
            thickness += 2;
            g.setStroke(new BasicStroke(thickness, BasicStroke.CAP_BUTT, BasicStroke.JOIN_ROUND));
            g.draw(ledger.getMedian());
            g.setStroke(oldStroke);
        }

        //------------//
        // Parameters //
        //------------//
        private static class Parameters
        {
            final int hMargin;

            final int vMargin;

            Parameters (Scale scale)
            {
                hMargin = scale.toPixels(constants.staffHorizontalMargin);
                vMargin = scale.toPixels(constants.staffVerticalMargin);
            }
        }
    }
}
