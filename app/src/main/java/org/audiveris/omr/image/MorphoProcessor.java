//------------------------------------------------------------------------------------------------//
//                                                                                                //
//                                    M o r p h o P r o c e s s o r                               //
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
package org.audiveris.omr.image;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import ij.process.ByteProcessor;

/**
 * Class <code>MorphoProcessor</code>
 *
 * @author ?
 */
public class MorphoProcessor
        implements MorphoConstants
{
    //~ Static fields/initializers -----------------------------------------------------------------

    private static final Logger logger = LoggerFactory.getLogger(MorphoProcessor.class);

    public static final int BINF = -256;

    private static final int ORIG = 0;

    private static final int PLUS = 1;

    private static final int MINUS = -1;

    //~ Instance fields ----------------------------------------------------------------------------

    private final StructureElement se; //, down_se, up_se;

    private final StructureElement minus_se; //, down_se, up_se;

    private final StructureElement plus_se; //, down_se, up_se;

    private final LocalHistogram bh;

    private final LocalHistogram p_h;

    private final LocalHistogram m_h;

    private final int[][] pg;

    private final int[][] pg_plus;

    private final int[][] pg_minus;

    int width;

    int height;

    //~ Constructors -------------------------------------------------------------------------------

    /**
     * Creates a new instance of MorphoProcessor.
     *
     * @param se the structuring element for processing
     */
    public MorphoProcessor (StructureElement se)
    {
        this.se = se;
        width = se.getWidth();
        height = se.getHeight();
        minus_se = new StructureElement(se.H(se.Delta(SGRAD), HMINUS), width);
        plus_se = new StructureElement(se.H(se.Delta(NGRAD), HMINUS), width);
        bh = new LocalHistogram();
        p_h = new LocalHistogram();
        m_h = new LocalHistogram();
        pg = se.getVect();
        pg_plus = plus_se.getVect();
        pg_minus = minus_se.getVect();
    }

    //~ Methods ------------------------------------------------------------------------------------

    //-------//
    // close //
    //-------//
    /**
     * Performs graylevel dilation followed by graylevel erosion
     * with arbitrary structural element.
     * <p>
     * When the element is flat and each of its rows is a centered run (a circle, a square...),
     * the result is computed row by row: the max (min) over a run of half-width c is built from
     * the one of half-width c-1, then the rows of the element are combined. Same result as
     * {@link #closeNaive}, which scans the whole element at every pixel.
     *
     * @param ip the ImageProcessor
     */
    public void close (ByteProcessor ip)
    {
        final int[] halfWidths = rowHalfWidths();

        if (halfWidths == null) {
            closeNaive(ip);
            return;
        }

        final int w = ip.getWidth();
        final int h = ip.getHeight();
        final byte[] pixels = (byte[]) ip.getPixels();
        final byte[] dilated = new byte[pixels.length];
        final byte[] closed = new byte[pixels.length];
        extremum(pixels, dilated, w, h, halfWidths, true);
        extremum(dilated, closed, w, h, halfWidths, false);
        System.arraycopy(closed, 0, pixels, 0, pixels.length);
    }

    /**
     * Graylevel dilation (max) or erosion (min) by a flat element given as one centered run per
     * row. Outside the image a pixel counts as 0 (dilation) or 255 (erosion), so it never wins,
     * as in {@link #getMinMax}.
     */
    private static void extremum (byte[] src,
                                  byte[] dst,
                                  int w,
                                  int h,
                                  int[] halfWidths,
                                  boolean max)
    {
        final int p = halfWidths.length / 2;
        int cMax = 0;

        for (int c : halfWidths) {
            cMax = Math.max(cMax, c);
        }

        final int n = halfWidths.length;
        final int[][][] ring = new int[n][cMax + 1][w]; // per source row: run extremum per half-width
        final int[] acc = new int[w];
        int next = 0; // next source row to fill

        for (int y = 0; y < h; y++) {
            for (int last = Math.min(h - 1, y + p); next <= last; next++) {
                fillRuns(src, next * w, w, ring[next % n], max);
            }

            java.util.Arrays.fill(acc, max ? 0 : 255);

            for (int dy = -p; dy <= p; dy++) {
                final int c = halfWidths[dy + p];
                final int r = y + dy;

                if ((c < 0) || (r < 0) || (r >= h)) {
                    continue;
                }

                final int[] e = ring[r % n][c];

                if (max) {
                    for (int x = 0; x < w; x++) {
                        if (e[x] > acc[x]) {
                            acc[x] = e[x];
                        }
                    }
                } else {
                    for (int x = 0; x < w; x++) {
                        if (e[x] < acc[x]) {
                            acc[x] = e[x];
                        }
                    }
                }
            }

            final int base = y * w;

            for (int x = 0; x < w; x++) {
                dst[base + x] = (byte) acc[x];
            }
        }
    }

    /** runs[c][x] = max (min) of the source row over [x-c, x+c], clipped to the row. */
    private static void fillRuns (byte[] src,
                                  int offset,
                                  int w,
                                  int[][] runs,
                                  boolean max)
    {
        final int[] e0 = runs[0];

        for (int x = 0; x < w; x++) {
            e0[x] = src[offset + x] & 0xFF;
        }

        for (int c = 1; c < runs.length; c++) {
            final int[] prev = runs[c - 1];
            final int[] cur = runs[c];

            for (int x = 0; x < w; x++) {
                int v = prev[x];

                if (x - c >= 0) {
                    final int a = e0[x - c];
                    v = max ? Math.max(v, a) : Math.min(v, a);
                }

                if (x + c < w) {
                    final int b = e0[x + c];
                    v = max ? Math.max(v, b) : Math.min(v, b);
                }

                cur[x] = v;
            }
        }
    }

    /**
     * The element as one centered run per row: half-width per row offset -p..p, -1 for an empty
     * row. Null when the element is not flat (value 255), or a row is not a run centered on the
     * column of the origin, or the origin is not in it.
     */
    int[] rowHalfWidths ()
    {
        int p = 0;

        for (int[] v : pg) {
            p = Math.max(p, Math.abs(v[0]));
        }

        final int[] lo = new int[(2 * p) + 1];
        final int[] hi = new int[(2 * p) + 1];
        final int[] count = new int[(2 * p) + 1];
        java.util.Arrays.fill(lo, Integer.MAX_VALUE);
        java.util.Arrays.fill(hi, Integer.MIN_VALUE);
        boolean origin = false;

        for (int[] v : pg) {
            if (v[2] != 255) {
                return null;
            }

            final int k = v[0] + p;
            lo[k] = Math.min(lo[k], v[1]);
            hi[k] = Math.max(hi[k], v[1]);
            count[k]++;
            origin |= (v[0] == 0) && (v[1] == 0);
        }

        if (!origin) {
            return null;
        }

        final int[] halfWidths = new int[(2 * p) + 1];

        for (int k = 0; k < halfWidths.length; k++) {
            if (count[k] == 0) {
                halfWidths[k] = -1;
            } else if ((lo[k] != -hi[k]) || (count[k] != (hi[k] - lo[k] + 1))) {
                return null;
            } else {
                halfWidths[k] = hi[k];
            }
        }

        return halfWidths;
    }

    /**
     * Performs graylevel dilation followed by graylevel erosion
     * with arbitrary structural element, scanning the whole element at every pixel.
     *
     * @param ip the ImageProcessor
     */
    void closeNaive (ByteProcessor ip)
    {
        int width = ip.getWidth();
        int height = ip.getHeight();
        int w = this.width; //se.getWidth();
        int h = this.height; //se.getHeight();
        int min = 0; //,k=0,x=0,y=0;
        int max = 255; //,k=0,x=0,y=0;

        //  IJ.log("pg: "+pg.length);
        int sz = pg.length; //se.getWidth()*se.getHeight();

        byte[] pixels = (byte[]) ip.getPixels();
        byte[] newpix = new byte[pixels.length];
        byte[] newpix2 = new byte[pixels.length];
        int[] wnd = new int[sz];

        for (int row = 1; row <= height; row++) {
            for (int col = 0; col < width; col++) {
                int index = ((row - 1) * width) + col; //dilation step

                if (index < pixels.length) {
                    wnd = getMinMax(index, width, height, pixels, pg, DILATE);
                    max = wnd[1] - 255;
                    newpix[index] = (byte) (max & 0xFF);
                }

                int index2 = (((row - h - 1) * width) + col) - w; //erosion step

                if ((index2 >= 0) && (index2 < pixels.length)) {
                    wnd = getMinMax(index2, width, height, newpix, pg, ERODE);
                    min = wnd[0] + 255;
                    newpix2[index2] = (byte) (min & 0xFF);
                }
            }
        }

        for (int row = height; row <= (height + h); row++) {
            for (int col = 0; col < (width + w); col++) {
                int index2 = (((row - h - 1) * width) + col) - w; //erosion step

                if ((index2 >= 0) && (index2 < pixels.length)) {
                    wnd = getMinMax(index2, width, height, newpix, pg, ERODE);
                    min = wnd[0] + 255;
                    newpix2[index2] = (byte) (min & 0xFF);
                }
            }
        }

        System.arraycopy(newpix2, 0, pixels, 0, pixels.length);
    }

    //--------//
    // dilate //
    //--------//
    /**
     * Performs gray level dilation
     *
     * @param ip the ImageProcessor
     */
    public void dilate (ByteProcessor ip)
    {
        int width = ip.getWidth();
        int height = ip.getHeight();
        int max = 32_768; //,k=0,x=0,y=0;

        //int[][]pg=se.getVect();
        //  IJ.log("pg: "+pg.length);
        int sz = pg.length; //se.getWidth()*se.getHeight();

        byte[] pixels = (byte[]) ip.getPixels();
        int[] wnd = new int[sz];

        byte[] newpix = new byte[pixels.length];

        //int i,j=0;
        for (int c = 0; c < pixels.length; c++) {
            //i=c/width;
            //j=c%width;
            wnd = getMinMax(c, width, height, pixels, pg, DILATE);

            max = wnd[1] - 255;
            newpix[c] = (byte) (max & 0xFF);
        }

        System.arraycopy(newpix, 0, pixels, 0, pixels.length);
    }

    //-------//
    // erode //
    //-------//
    /**
     * Performs gray level erosion
     *
     * @param ip the ImageProcessor
     */
    public void erode (ByteProcessor ip)
    {
        int width = ip.getWidth();
        int height = ip.getHeight();
        int min = -32_767; //,k=0,x=0,y=0;

        int sz = pg.length; //se.getWidth()*se.getHeight();
        // byte[] p=(byte[])ip.convertToByte(false).getValues();

        byte[] pixels = (byte[]) ip.getPixels();

        int[] wnd = new int[sz];

        byte[] newpix = new byte[pixels.length];

        //int i,j=0;
        for (int c = 0; c < pixels.length; c++) {
            // i=c/width;
            // j=c%width;
            wnd = getMinMax(c, width, height, pixels, pg, ERODE);
            min = wnd[0] + 255;
            newpix[c] = (byte) (min & 0xFF);
        }

        System.arraycopy(newpix, 0, pixels, 0, pixels.length);
    }

    /**
     * Performs fast graylevel dilation followed by fast graylevel erosion
     * with arbitrary structural element
     *
     * @param ip the ImageProcessor
     */
    public void fclose (ByteProcessor ip)
    {
        //fastDilate(ip,se);
        //fastErode(ip,se);
        int width = ip.getWidth();
        int height = ip.getHeight();
        int max = 32_767; //,k=0,x=0,y=0;

        //int pgzise=pg.length;
        byte[] pixels = (byte[]) ip.getPixels();
        byte[] newpix = new byte[pixels.length];

        //String s="", s2="";
        int row = 0;

        //String s="", s2="";
        int z = 0;
        int index = 0;

        // Dilation loop
        for (row = 1; row <= height; row++) {
            z = (row - 1) * width;
            //    IJ.log("odd index  "+ z);
            bh.init(z, width, height, pixels, pg, 0);
            //  bh.doMaximum();
            max = bh.getMaximum();
            newpix[z] = (byte) (max & 0xFF);

            for (int col = 1; col < width; col++) {
                index = z + col;

                //          s2+=" "+index+"\r\n";
                try {
                    p_h.init(index, width, height, pixels, pg_plus, 0);
                    m_h.init(index - 1, width, height, pixels, pg_minus, 0);
                    bh.sub(m_h);
                    bh.add(p_h);
                    bh.doMaximum();
                    max = bh.getMaximum();
                    newpix[index] = (byte) (max & 0xFF);
                } catch (ArrayIndexOutOfBoundsException aiob) {
                    logger.warn(" out index: " + index);
                }
            } //odd loop
        }

        int min = -32_767; //,k=0,x=0,y=0;

        byte[] newpix2 = new byte[pixels.length];

        // Erosion loop
        //boolean changed=false;
        for (row = 1; row <= height; row++) {
            z = (row - 1) * width;
            //                                //    IJ.log("odd index  "+ z);
            bh.init(z, width, height, newpix, pg, 1);

            // bh.Log();
            //bh.doMinimum();
            min = bh.getMinimum();
            newpix2[z] = (byte) (min & 0xFF);

            for (int col = 1; col < width; col++) {
                index = z + col;

                try {
                    p_h.init(index, width, height, newpix, pg_plus, 1);
                    m_h.init(index - 1, width, height, newpix, pg_minus, 1);
                    bh.sub(m_h);
                    bh.add(p_h);

                    bh.doMinimum();

                    min = bh.getMinimum();
                    newpix2[index] = (byte) (min & 0xFF);
                } catch (ArrayIndexOutOfBoundsException aiob) {
                    logger.warn(" out index: {} min {}", index, min);
                }
            } //odd loop
        }

        System.arraycopy(newpix2, 0, pixels, 0, pixels.length);
    }

    private int[] getMinMax (int index,
                             int width,
                             int height,
                             byte[] pixels,
                             int[][] pg,
                             int type)
    {
        //  int[][]pg=se.getVectTransform(mType);
        int pgzise = pg.length;

        int[] wnd = new int[2];
        int i;
        int j;
        int k = 0;
        int x;
        int y = 0;
        int min = 255;
        int max = 0;

        i = index / width;
        j = index % width;

        for (int g = 0; g < pgzise; g++) {
            y = i + pg[g][0];
            x = j + pg[g][1];

            try {
                if ((x >= width) || (y >= height) || (x < 0) || (y < 0)) {
                    if (type == DILATE) {
                        k = 0;
                    }

                    if (type == ERODE) {
                        k = 255;
                    }
                } else {
                    k = pixels[x + (width * y)] & 0xFF;
                }
            } catch (ArrayIndexOutOfBoundsException ex) {
                k = x + (width * y);
                logger.warn("AIOB x: {} y: {} index: {}", x, y, k);
            }

            if (type == DILATE) {
                k += pg[g][2];
            }

            if (type == ERODE) {
                k -= pg[g][2];
            }

            if (k < min) {
                min = k;
            }

            if (k > max) {
                max = k;
            }
        }

        wnd[0] = min & 0xFF;
        wnd[1] = max & 0xFF;

        return wnd;
    }

    //------//
    // open //
    //------//
    /**
     * Performs graylevel erosion followed by graylevel dilation
     * with arbitrary structural element se
     *
     * @param ip the ImageProcessor
     */
    public void open (ByteProcessor ip)
    {
        int width = ip.getWidth();
        int height = ip.getHeight();
        int min = -32_767; //,k=0,x=0,y=0;
        int max = 32_768;
        int w = this.width; //se.getWidth();
        int h = this.height; //se.getHeight();
        // int[][] pg=se.getVect();

        int sz = pg.length;

        byte[] pixels = (byte[]) ip.getPixels();
        byte[] newpix = new byte[pixels.length];
        byte[] newpix2 = new byte[pixels.length];
        int[] wnd = new int[sz];

        //  int i,j=0;
        for (int row = 1; row <= height; row++) {
            for (int col = 0; col < width; col++) {
                int index = ((row - 1) * width) + col; //erosion step

                if (index < pixels.length) {
                    wnd = getMinMax(index, width, height, pixels, pg, ERODE);
                    min = wnd[0] + 255;
                    newpix[index] = (byte) (min & 0xFF);
                }

                int index2 = (((row - h - 1) * width) + col) - w; //dilation step

                if ((index2 >= 0) && (index2 < pixels.length)) {
                    wnd = getMinMax(index2, width, height, newpix, pg, DILATE);
                    max = wnd[1] - 255;
                    newpix2[index2] = (byte) (max & 0xFF);
                }
            }
        }

        for (int row = height; row <= (height + h); row++) {
            for (int col = 0; col < (width + w); col++) {
                int index2 = (((row - h - 1) * width) + col) - w; //dilation step

                if ((index2 >= 0) && (index2 < pixels.length)) {
                    wnd = getMinMax(index2, width, height, newpix, pg, DILATE);
                    max = wnd[1] - 255;
                    newpix2[index2] = (byte) (max & 0xFF);
                }
            }
        }

        System.arraycopy(newpix2, 0, pixels, 0, pixels.length);
    }
}
