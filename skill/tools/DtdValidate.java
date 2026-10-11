// Validate a MusicXML file against the official MusicXML 3.1 Partwise DTD.
//
// Usage:  java DtdValidate.java FILE.musicxml [DTD_DIR]
//
// DTD_DIR defaults to the sibling tools/dtd directory.  The PUBLIC
// entity modules (common.mod, note.mod, ...) are resolved from DTD_DIR by file
// name, so no network access is needed.
import javax.xml.parsers.SAXParser;
import javax.xml.parsers.SAXParserFactory;
import org.xml.sax.ErrorHandler;
import org.xml.sax.InputSource;
import org.xml.sax.SAXException;
import org.xml.sax.SAXParseException;
import org.xml.sax.XMLReader;
import java.io.File;
import java.io.FileInputStream;

public class DtdValidate {
    public static void main(String[] args) throws Exception {
        if (args.length < 1) {
            System.err.println("usage: java DtdValidate.java FILE.musicxml [DTD_DIR]");
            System.exit(2);
        }
        final File dtdDir;
        if (args.length > 1) {
            dtdDir = new File(args[1]);
        } else {
            File here = new File(DtdValidate.class.getProtectionDomain()
                    .getCodeSource().getLocation().toURI());
            File dir = new File(here.isDirectory() ? here : here.getParentFile(),
                    "dtd");
            dtdDir = dir;
        }

        SAXParserFactory spf = SAXParserFactory.newInstance();
        spf.setValidating(true);
        spf.setNamespaceAware(false);
        SAXParser sp = spf.newSAXParser();
        XMLReader r = sp.getXMLReader();
        r.setEntityResolver((pub, sys) -> {
            if (sys == null) return null;
            File local = new File(dtdDir, new File(sys).getName());
            return local.exists()
                    ? new InputSource(new FileInputStream(local)) : null;
        });
        final int[] errors = {0};
        r.setErrorHandler(new ErrorHandler() {
            public void warning(SAXParseException e) {}
            public void error(SAXParseException e) {
                errors[0]++;
                System.out.println("ERR line " + e.getLineNumber() + ": "
                        + e.getMessage());
            }
            public void fatalError(SAXParseException e) throws SAXException {
                errors[0]++;
                System.out.println("FATAL line " + e.getLineNumber() + ": "
                        + e.getMessage());
            }
        });
        // Previews carry no DOCTYPE (lxml drops it); add the 3.1 one after the XML declaration.
        // Reported line numbers are then 1 higher than in the file.
        String text = new String(java.nio.file.Files.readAllBytes(new File(args[0]).toPath()),
                java.nio.charset.StandardCharsets.UTF_8);
        if (!text.contains("<!DOCTYPE")) {
            int eol = text.indexOf('\n') + 1;
            text = text.substring(0, eol)
                    + "<!DOCTYPE score-partwise PUBLIC \"-//Recordare//DTD MusicXML 3.1 Partwise//EN\" "
                    + "\"http://www.musicxml.org/dtds/partwise.dtd\">\n" + text.substring(eol);
        }
        r.parse(new InputSource(new java.io.StringReader(text)));
        System.out.println("violations: " + errors[0]);
        if (errors[0] > 0) System.exit(1);
    }
}
