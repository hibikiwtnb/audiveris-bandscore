//------------------------------------------------------------------------------------------------//
//                                                                                                //
//                                       P a d d l e O C R                                        //
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
package org.audiveris.omr.text.paddle;

import org.audiveris.omr.constant.Constant;
import org.audiveris.omr.constant.ConstantSet;
import org.audiveris.omr.sheet.Sheet;
import org.audiveris.omr.text.FontInfo;
import org.audiveris.omr.text.OCR;
import org.audiveris.omr.text.TextChar;
import org.audiveris.omr.text.TextLine;
import org.audiveris.omr.text.TextWord;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.awt.Point;
import java.awt.Rectangle;
import java.awt.geom.Line2D;
import java.awt.image.BufferedImage;
import java.io.ByteArrayOutputStream;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.SortedSet;
import java.util.TreeSet;

import javax.imageio.ImageIO;

/**
 * Class <code>PaddleOCR</code> is an OCR implementation that delegates recognition to a local
 * PP-OCR server (see <code>dev/paddleocr/paddle_ocr_server.py</code>).
 * <p>
 * The server is expected to be already running, its base URL is defined by the
 * <code>serverUrl</code> constant.
 * Recognition language is defined by the server models, the language specification is ignored.
 * Lyric lines can be read again by the lyrics model of the server, see
 * {@link #recognizeLyrics}.
 *
 */
public class PaddleOCR
        implements OCR
{
    //~ Static fields/initializers -----------------------------------------------------------------

    private static final Constants constants = new Constants();

    private static final Logger logger = LoggerFactory.getLogger(PaddleOCR.class);

    /** Singleton. */
    private static volatile PaddleOCR INSTANCE;

    //~ Instance fields ----------------------------------------------------------------------------

    private final HttpClient client = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(3)).build();

    /** Server identification, null if server could not be reached. */
    private String serverId;

    /** Has server availability been checked?. */
    private boolean checked;

    //~ Constructors -------------------------------------------------------------------------------

    private PaddleOCR ()
    {
    }

    //~ Methods ------------------------------------------------------------------------------------

    //------------------//
    // getMinConfidence //
    //------------------//
    @Override
    public double getMinConfidence ()
    {
        return constants.minConfidence.getValue();
    }

    //-----------------------//
    // getSupportedLanguages //
    //-----------------------//
    @Override
    public SortedSet<String> getSupportedLanguages ()
    {
        return new TreeSet<>(List.of("eng"));
    }

    //----------//
    // identify //
    //----------//
    @Override
    public String identify ()
    {
        return "PaddleOCR " + ((serverId != null) ? serverId : "(unavailable)") + " at "
                + constants.serverUrl.getValue();
    }

    //-------------//
    // isAvailable //
    //-------------//
    @Override
    public synchronized boolean isAvailable ()
    {
        if (!checked) {
            checked = true;

            try {
                final HttpRequest request = HttpRequest.newBuilder(uri("/health"))
                        .timeout(Duration.ofSeconds(60)).GET().build(); // Server may be busy
                final HttpResponse<String> response = client.send(
                        request,
                        HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));

                if (response.statusCode() == 200 && response.body().startsWith("ok")) {
                    serverId = response.body().substring(2).trim();
                }
            } catch (Exception ex) {
                logger.warn("PaddleOCR server not reachable at {}: {}", constants.serverUrl
                        .getValue(), ex.toString());
            }
        }

        return serverId != null;
    }

    //-----------//
    // recognize //
    //-----------//
    @Override
    public List<TextLine> recognize (Sheet sheet,
                                     BufferedImage image,
                                     Point topLeft,
                                     String langSpec,
                                     LayoutMode layoutMode,
                                     String label)
    {
        if (!isAvailable()) {
            return null;
        }

        try {
            final HttpResponse<String> response = post("/ocr", image);

            if (response.statusCode() != 200) {
                logger.warn("{} PaddleOCR server error {} {}", label, response.statusCode(),
                        response.body().trim());
                return null;
            }

            final List<TextLine> lines = parse(sheet, response.body(), topLeft);
            logger.debug("{} PaddleOCR lines: {}", label, lines.size());

            return lines;
        } catch (Exception ex) {
            logger.warn("{} PaddleOCR recognition failed {}", label, ex.toString(), ex);
            return null;
        }
    }

    //-----------------//
    // recognizeLyrics //
    //-----------------//
    /**
     * Read an image of the lyrics below a staff with the lyrics reader of the server, keeping
     * only the chars of the given scripts: one word per syllable, with its own score.
     *
     * @param sheet   the related sheet
     * @param image   the image to read
     * @param topLeft image top left corner in sheet
     * @param scripts comma-separated script names (hiragana, katakana, kanji, latin, digits,
     *                punct, hyphen)
     * @param label   label for messages
     * @return the lines read, in sheet coordinates
     * @throws IllegalStateException if the server cannot read it (no fallback to other models)
     */
    public List<TextLine> recognizeLyrics (Sheet sheet,
                                           BufferedImage image,
                                           Point topLeft,
                                           String scripts,
                                           String label)
    {
        final String path = "/ocr?model=lyrics&scripts="
                + URLEncoder.encode(scripts, StandardCharsets.UTF_8);
        final HttpResponse<String> response;

        try {
            response = post(path, image);
        } catch (Exception ex) {
            throw new IllegalStateException(label + " PaddleOCR lyrics request failed: " + ex, ex);
        }

        if (response.statusCode() != 200) {
            throw new IllegalStateException(label + " PaddleOCR lyrics: " + response.body().trim());
        }

        return parse(sheet, response.body(), topLeft);
    }

    //------//
    // post //
    //------//
    private HttpResponse<String> post (String path,
                                       BufferedImage image)
        throws Exception
    {
        final ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        ImageIO.write(image, "png", bytes);

        final HttpRequest request = HttpRequest.newBuilder(uri(path))
                .timeout(Duration.ofSeconds(constants.timeout.getValue()))
                .header("Content-Type", "image/png")
                .POST(HttpRequest.BodyPublishers.ofByteArray(bytes.toByteArray())).build();

        return client.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
    }

    //----------//
    // supports //
    //----------//
    @Override
    public boolean supports (String langSpec)
    {
        return true; // Language is defined by server models
    }

    //-------//
    // parse //
    //-------//
    /**
     * Build TextLine / TextWord / TextChar instances out of server response.
     *
     * @param sheet   the related sheet
     * @param body    the server response, one tab-separated record per line
     * @param topLeft image top left corner, coordinates are translated by it (null: none)
     * @return the lines built
     */
    private List<TextLine> parse (Sheet sheet,
                                  String body,
                                  Point topLeft)
    {
        final List<TextLine> lines = new ArrayList<>();
        TextLine line = null;
        TextWord word = null;
        double score = 0;

        for (String record : body.split("\n")) {
            final String[] f = record.split("\t", -1);

            switch (f[0]) {
            case "L" -> {
                score = Double.parseDouble(f[1]);
                line = new TextLine(sheet);
                lines.add(line);
                word = null;
            }

            case "W" -> {
                if (line == null) {
                    continue;
                }

                final Rectangle box = rectangle(f, 1);
                final Line2D baseline = new Line2D.Double(
                        box.x,
                        box.y + box.height,
                        box.x + box.width,
                        box.y + box.height);
                word = new TextWord(
                        sheet,
                        box,
                        f[5],
                        baseline,
                        (f.length > 6) ? Double.parseDouble(f[6]) : score, // Own score, if any
                        FontInfo.createDefault(box.height),
                        line);
                line.appendWord(word);
            }

            case "C" -> {
                if (word != null) {
                    word.addChar(new TextChar(rectangle(f, 1), f[5]));
                }
            }

            default -> {
            }
            }
        }

        lines.removeIf(l -> l.getWords().isEmpty() || l.getValue().isBlank());

        if (topLeft != null) {
            // Translate topLeft-relative coordinates to origin-relative ones
            for (TextLine l : lines) {
                l.translate(topLeft.x, topLeft.y);
            }
        }

        return lines;
    }

    //-----------//
    // rectangle //
    //-----------//
    private static Rectangle rectangle (String[] f,
                                        int i)
    {
        return new Rectangle(
                Integer.parseInt(f[i]),
                Integer.parseInt(f[i + 1]),
                Integer.parseInt(f[i + 2]),
                Integer.parseInt(f[i + 3]));
    }

    //-----//
    // uri //
    //-----//
    private static URI uri (String path)
    {
        final String base = constants.serverUrl.getValue().trim();

        return URI.create(base.endsWith("/") ? base.substring(0, base.length() - 1) + path
                : base + path);
    }

    //-------------//
    // getInstance //
    //-------------//
    /**
     * Report the singleton.
     *
     * @return the PaddleOCR instance
     */
    public static PaddleOCR getInstance ()
    {
        if (INSTANCE == null) {
            synchronized (PaddleOCR.class) {
                if (INSTANCE == null) {
                    INSTANCE = new PaddleOCR();
                }
            }
        }

        return INSTANCE;
    }

    //~ Inner Classes ------------------------------------------------------------------------------

    //-----------//
    // Constants //
    //-----------//
    private static class Constants
            extends ConstantSet
    {
        private final Constant.String serverUrl = new Constant.String(
                "http://127.0.0.1:8868",
                "Base URL of the local PaddleOCR server");

        private final Constant.Double minConfidence = new Constant.Double(
                "0..1",
                0.60,
                "Minimum confidence for OCR validity");

        private final Constant.Integer timeout = new Constant.Integer(
                "seconds",
                300,
                "Timeout for one PaddleOCR recognition request");
    }
}
