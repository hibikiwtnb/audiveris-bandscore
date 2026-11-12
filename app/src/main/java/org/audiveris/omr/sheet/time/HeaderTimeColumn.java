//------------------------------------------------------------------------------------------------//
//                                                                                                //
//                                 H e a d e r T i m e C o l u m n                                //
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
package org.audiveris.omr.sheet.time;

import org.audiveris.omr.constant.Constant;
import org.audiveris.omr.constant.ConstantSet;
import org.audiveris.omr.glyph.Grades;
import org.audiveris.omr.score.TimeRational;
import org.audiveris.omr.sheet.Staff;
import org.audiveris.omr.sheet.SystemInfo;
import org.audiveris.omr.sig.inter.AbstractTimeInter;
import org.audiveris.omr.text.OcrUtil;
import org.audiveris.omr.text.paddle.PaddleOCR;
import org.audiveris.omr.util.ChartPlotter;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.HashMap;
import java.util.Map;

/**
 * A subclass of {@link TimeColumn}, specifically meant for managing times in a system
 * header.
 *
 * @author Hervé Bitteur
 */
public class HeaderTimeColumn
        extends TimeColumn
{
    //~ Static fields/initializers -----------------------------------------------------------------

    private static final Constants constants = new Constants();

    private static final Logger logger = LoggerFactory.getLogger(HeaderTimeColumn.class);

    //~ Constructors -------------------------------------------------------------------------------

    /**
     * Creates a new <code>HeaderTimeColumn</code> object.
     *
     * @param system containing system
     */
    public HeaderTimeColumn (SystemInfo system)
    {
        super(system);
    }

    //~ Methods ------------------------------------------------------------------------------------

    //---------//
    // addPlot //
    //---------//
    /**
     * Contribute to the staff plotter with data related to time signature.
     * <p>
     * Since the user can ask for time plot at any time, we allocate an instance of
     * HeaderTimeBuilder on demand just to provide the plot information that pertains to the
     * desired staff. This saves us the need to keep rather useless instances in memory.
     *
     * @param plotter the staff plotter to populate
     * @param staff   the desired staff
     * @return the time chosen to be added to plot title
     */
    public String addPlot (ChartPlotter plotter,
                           Staff staff)
    {
        final int browseStart;

        if (staff.getKeyStop() != null) {
            browseStart = staff.getKeyStop();
        } else if (staff.getClefStop() != null) {
            browseStart = staff.getClefStop();
        } else {
            browseStart = staff.getHeaderStart();
        }

        HeaderTimeBuilder builder = new HeaderTimeBuilder(staff, this, browseStart);
        builder.addPlot(plotter);

        AbstractTimeInter timeInter = staff.getHeader().time;

        if (timeInter != null) {
            return "time:" + timeInter.getValue();
        } else {
            return null;
        }
    }

    @Override
    protected TimeBuilder allocateBuilder (Staff staff)
    {
        int browseStart = staff.getHeaderStop();

        return new HeaderTimeBuilder(staff, this, browseStart);
    }

    @Override
    protected void cleanup ()
    {
        for (TimeBuilder builder : builders.values()) {
            builder.cleanup();
        }
    }

    //------------------//
    // refineCandidates //
    //------------------//
    /**
     * Read the top and bottom numbers of every staff with the OCR (digits only) and, when more
     * than half of the staves agree on a supported num/den pair, impose it on all staves.
     * <p>
     * The glyph classifier misreads blurred low-resolution numbers (a filled 4 seen as 6, a whole
     * 4/4 seen as 2/4, the same way in every staff), which the OCR reads right. Only staves where
     * the classifier found some time candidate are read.
     */
    @Override
    protected void refineCandidates ()
    {
        if (!constants.useOcr.isSet() || !(OcrUtil.getOcr() instanceof PaddleOCR)) {
            return;
        }

        final Map<Integer, Integer> numVotes = new HashMap<>();
        final Map<Integer, Integer> denVotes = new HashMap<>();

        for (TimeBuilder builder : builders.values()) {
            final int[] nd = ((HeaderTimeBuilder) builder).ocrHalves();

            if (nd != null) {
                numVotes.merge(nd[0], 1, Integer::sum);
                denVotes.merge(nd[1], 1, Integer::sum);
            }
        }

        final Map.Entry<Integer, Integer> num = best(numVotes);
        final Map.Entry<Integer, Integer> den = best(denVotes);
        final int staves = builders.size();
        logger.debug("System#{} OCR time votes num:{} den:{}", system.getId(), numVotes, denVotes);

        if ((num == null) || (den == null) || (2 * num.getValue() <= staves)
                || (2 * den.getValue() <= staves) || (num.getKey() <= 0) || (den.getKey() <= 0)) {
            return;
        }

        if (!AbstractTimeInter.isSupported(new TimeRational(num.getKey(), den.getKey()))) {
            return;
        }

        // Confidence is the share of staves that agree
        final double grade = Grades.intrinsicRatio * Math.min(num.getValue(), den.getValue())
                / staves;
        logger.info("System#{} OCR reads time signature {}/{} in {} of {} staves", system.getId(),
                num.getKey(), den.getKey(), Math.min(num.getValue(), den.getValue()), staves);

        for (TimeBuilder builder : builders.values()) {
            ((HeaderTimeBuilder) builder).imposeTime(num.getKey(), den.getKey(), grade);
        }
    }

    private static Map.Entry<Integer, Integer> best (Map<Integer, Integer> votes)
    {
        return votes.entrySet().stream().max(Map.Entry.comparingByValue()).orElse(null);
    }

    //------------//
    // lookupTime //
    //------------//
    /**
     * Look up for a column of <b>existing</b> time-signatures near headers end.
     *
     * @return ending abscissa offset of time-sig column WRT measure start, or -1 if invalid
     */
    public int lookupTime ()
    {
        // Allocate one time-sig builder for each staff within system
        for (Staff staff : system.getStaves()) {
            if (!staff.isTablature()) {
                builders.put(staff, allocateBuilder(staff));
            }
        }

        // Process each staff on turn, to look up time-sig
        for (TimeBuilder builder : builders.values()) {
            // Look up header time
            AbstractTimeInter time = ((HeaderTimeBuilder) builder).lookupTime();

            if (time == null) {
                return -1;
            }
        }

        // Push abscissa end for each StaffHeader
        int maxTimeOffset = 0;

        for (Staff staff : system.getStaves()) {
            if (!staff.isTablature()) {
                int measureStart = staff.getHeaderStart();
                Integer timeStop = staff.getTimeStop();

                if (timeStop != null) {
                    maxTimeOffset = Math.max(maxTimeOffset, timeStop - measureStart);
                }
            }
        }

        return maxTimeOffset;
    }

    //--------------//
    // retrieveTime //
    //--------------//
    /**
     * {@inheritDoc}
     *
     * @return ending abscissa offset of time-sig column WRT measure start, or -1 if invalid
     */
    @Override
    public int retrieveTime ()
    {
        if (-1 != super.retrieveTime()) {
            // Push abscissa end for each StaffHeader
            int maxTimeOffset = 0;

            for (Staff staff : system.getStaves()) {
                if (!staff.isTablature()) {
                    int measureStart = staff.getHeaderStart();
                    Integer timeStop = staff.getTimeStop();

                    if (timeStop != null) {
                        maxTimeOffset = Math.max(maxTimeOffset, timeStop - measureStart);
                    }
                }
            }

            return maxTimeOffset;
        } else {
            return -1;
        }
    }

    //~ Inner Classes ------------------------------------------------------------------------------

    //-----------//
    // Constants //
    //-----------//
    private static final class Constants
            extends ConstantSet
    {
        private final Constant.Boolean useOcr = new Constant.Boolean(
                true,
                "Should the OCR (PaddleOCR, digits only) read the numbers of header time signatures?");
    }
}
