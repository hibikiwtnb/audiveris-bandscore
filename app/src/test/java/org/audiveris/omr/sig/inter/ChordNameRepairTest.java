//------------------------------------------------------------------------------------------------//
//                                                                                                //
//                             C h o r d N a m e R e p a i r T e s t                              //
//                                                                                                //
//------------------------------------------------------------------------------------------------//
package org.audiveris.omr.sig.inter;

import static org.junit.Assert.assertEquals;
import org.junit.Test;

/**
 * The OCR misreadings of chord names seen in the band scores.
 */
public class ChordNameRepairTest
{
    @Test
    public void testRepairs ()
    {
        assertEquals("F#m", ChordNameInter.repairOcr("F$m"));
        assertEquals("F#sus4", ChordNameInter.repairOcr("F$sus4"));
        assertEquals("D#m7", ChordNameInter.repairOcr("D^m7"));
        assertEquals("C#m7", ChordNameInter.repairOcr("C-m7"));
        assertEquals("C#dim", ChordNameInter.repairOcr("C-dim"));
        assertEquals("D#m7(b5)", ChordNameInter.repairOcr("D-m7(5)"));
        assertEquals("D#m7(b5)", ChordNameInter.repairOcr("D^m7(>5)"));
        assertEquals("Bm7(b5)", ChordNameInter.repairOcr("Bm765"));
        assertEquals("C#m7(b5)", ChordNameInter.repairOcr("C#m705"));
        assertEquals("Dm7(b5)", ChordNameInter.repairOcr("Dm7(65)"));
        assertEquals("Dm7(b5)", ChordNameInter.repairOcr("Dm7(5"));
        assertEquals("F#m7(b5)", ChordNameInter.repairOcr("F$m75"));
        // left alone
        assertEquals("C-7", ChordNameInter.repairOcr("C-7"));
        assertEquals("Am7", ChordNameInter.repairOcr("Am7"));
        assertEquals("Em7(9)", ChordNameInter.repairOcr("Em7(9)"));
        assertEquals("Am7(11)", ChordNameInter.repairOcr("Am7(11)"));
    }
}
