//------------------------------------------------------------------------------------------------//
//                                                                                                //
//                              M o r p h o P r o c e s s o r T e s t                             //
//                                                                                                //
//------------------------------------------------------------------------------------------------//
package org.audiveris.omr.image;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;
import org.junit.Test;

import ij.process.ByteProcessor;

import java.util.Random;

/**
 * The row-by-row close gives the same bytes as the naive one.
 */
public class MorphoProcessorTest
{
    private static byte[] closeBoth (byte[] pixels,
                                     int w,
                                     int h,
                                     StructureElement se)
    {
        final MorphoProcessor mp = new MorphoProcessor(se);
        final ByteProcessor fast = new ByteProcessor(w, h, pixels.clone());
        final ByteProcessor naive = new ByteProcessor(w, h, pixels.clone());
        mp.close(fast);
        mp.closeNaive(naive);
        assertArrayEquals((byte[]) naive.getPixels(), (byte[]) fast.getPixels());
        return (byte[]) fast.getPixels();
    }

    @Test
    public void testCircles ()
    {
        final Random rnd = new Random(20261017);
        final int[][] sizes = { { 1, 1 }, { 3, 2 }, { 7, 30 }, { 40, 5 }, { 97, 61 }, { 300, 200 } };
        int checked = 0;

        // beam heights 3..20 px, as in SpotsBuilder (diameter = 0.8 * beam) and BlackHeadSizer
        for (int beam = 3; beam <= 20; beam++) {
            final double diameter = beam * 0.8;
            final float radius = (float) (diameter - 1) / 2;
            final StructureElement se = new StructureElement(0, 1, radius, new int[] { 0, 0 });
            assertNotNull("circle takes the row-by-row path", new MorphoProcessor(se).rowHalfWidths());

            for (int[] size : sizes) {
                final int w = size[0];
                final int h = size[1];
                final byte[] noise = new byte[w * h];
                rnd.nextBytes(noise);
                closeBoth(noise, w, h, se);

                // sparse dark spots and bars on white, like a page buffer
                final byte[] page = new byte[w * h];
                java.util.Arrays.fill(page, (byte) 255);

                for (int k = 0; k < (w * h) / 20; k++) {
                    page[rnd.nextInt(w * h)] = (byte) rnd.nextInt(256);
                }

                for (int y = h / 3; y < Math.min(h, (h / 3) + beam); y++) {
                    for (int x = w / 4; x < (3 * w) / 4; x++) {
                        page[(y * w) + x] = 0;
                    }
                }

                closeBoth(page, w, h, se);
                checked++;
            }
        }

        assertTrue(checked > 0);
    }

    @Test
    public void testOtherShapes ()
    {
        final Random rnd = new Random(7);

        // square (row runs), diamond (row runs) and lines: fast path or fallback, same bytes
        for (int type : new int[] { MorphoConstants.DIAMOND, MorphoConstants.VLINE, MorphoConstants.HLINE, MorphoConstants.SQUARE }) {
            for (float radius = 0.5f; radius < 6; radius += 0.7f) {
                final StructureElement se = new StructureElement(type, 1, radius, new int[] { 0, 0 });
                final byte[] noise = new byte[61 * 43];
                rnd.nextBytes(noise);
                closeBoth(noise, 61, 43, se);
            }
        }
    }
}
