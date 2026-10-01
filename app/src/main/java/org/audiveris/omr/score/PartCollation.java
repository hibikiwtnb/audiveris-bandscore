//------------------------------------------------------------------------------------------------//
//                                                                                                //
//                                    P a r t C o l l a t i o n                                   //
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
package org.audiveris.omr.score;

import org.audiveris.omr.constant.Constant;
import org.audiveris.omr.constant.ConstantSet;
import org.audiveris.omr.sheet.SheetStub;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Objects;
import java.util.Set;

/**
 * Class <code>PartCollation</code> is in charge of collecting and combining parts across
 * systems and pages so that a part always represents the same instrument all along the score.
 * <p>
 * <p>
 * The strategy used to build LogicalPart's out of PartRef's is based on the following assumptions:
 * <ul>
 * <li>For a part of a system to be combined to a part of another system, they must exhibit the
 * same staves physical configuration:
 * <ol>
 * <li>Same count of staves
 * <li>Same count of lines in corresponding staves
 * <li>Same small attribute if any in corresponding staves
 * </ol>
 * <li>Parts cannot be swapped from one system to the other. In other words, we cannot have say
 * partA followed by partB in a system, and partB followed by partA in another system.</li>
 * <li>A part with 2 standard staves, likely to be the piano part if any, is used as a pivot to
 * align collations.</li>
 * <li>Otherwise, since additional parts appear at the top of a system, rather than at the bottom,
 * we process part collation bottom up.</li>
 * <li>When available, we use the part names (or abbreviations) to help the collation algorithm,
 * but this is questionable for lack of OCR reliability on part names and abbreviations.
 * </ul>
 *
 * @author Hervé Bitteur
 */
public class PartCollation
{
    //~ Static fields/initializers -----------------------------------------------------------------

    private static final Constants constants = new Constants();

    private static final Logger logger = LoggerFactory.getLogger(PartCollation.class);

    /** Cost of a system part that cannot be mapped to any hinted logical. */
    private static final double UNMAPPED_COST = 10;

    public static final List<StaffConfig> PIANO_CONFIG = StaffConfig.decodeCsv(
            constants.pianoStaffConfig.getValue());

    //~ Instance fields ----------------------------------------------------------------------------

    /**
     * The sorted list of logical parts, each with its affiliated physical parts.
     */
    private final List<Record> records = new ArrayList<>();

    /**
     * All logical names.
     */
    final Set<String> logicalNames = new LinkedHashSet<>();

    /**
     * Are the score LogicalPart's locked?.
     */
    private boolean logicalsLocked;

    /**
     * Are the LogicalPart's provided by the user parts hint?.
     */
    private boolean hinted;

    //~ Constructors -------------------------------------------------------------------------------

    /**
     * Creates a new <code>PartCollation</code> object.
     *
     * @param sequences the list of sequences of parts
     * @param logicals  the pre-populated list of LogicalPart's, or null if un-locked
     */
    public PartCollation (List<List<PartRef>> sequences,
                          List<LogicalPart> logicals)
    {
        this(sequences, logicals, false);
    }

    /**
     * Creates a new <code>PartCollation</code> object.
     *
     * @param sequences the list of sequences of parts
     * @param logicals  the pre-populated list of LogicalPart's, or null if un-locked
     * @param hinted    true if logicals come from the user parts hint
     */
    public PartCollation (List<List<PartRef>> sequences,
                          List<LogicalPart> logicals,
                          boolean hinted)
    {
        this.hinted = hinted && (logicals != null);

        if (logicals != null) {
            logicalsLocked = !this.hinted;

            // Allocate the records
            for (LogicalPart logical : logicals) {
                final Record record = new Record(logical);
                record.hint = this.hinted;
                records.add(record);

                final String logicalName = logical.getName();
                if (logicalName != null) {
                    logicalNames.add(logicalName);
                }
            }
        }

        collate(sequences);
    }

    //~ Methods ------------------------------------------------------------------------------------

    //-----------//
    // addRecord //
    //-----------//
    /**
     * Build a new Record based on provided PartRef and insert it at last position,
     * according to provided direction, in the list of records.
     *
     * @param dir     -1 for up, +1 for down
     * @param partRef the provided candidate partRef
     * @param records (output) the records to be augmented
     */
    private void addRecord (int dir,
                            PartRef partRef,
                            List<Record> records)
    {
        // Create a brand new logical part for this candidate part
        final LogicalPart logical = new LogicalPart(
                0, // This id indicates a just-created logical
                partRef.getStaffCount(),
                partRef.getStaffConfigs());
        logical.setName(partRef.getName());
        logical.setAbbreviation(null);
        logical.setStaffConfigs(partRef.getStaffConfigs());
        logger.debug("Created {} from {}", logical, partRef);

        final Record record = new Record(logical);
        record.partRefs.add(partRef);

        if (logical.getName() != null) {
            logicalNames.add(logical.getName());
        }

        // Insert at proper end of records
        records.add(dir < 0 ? 0 : records.size(), record);
    }

    //---------//
    // biIndex //
    //---------//
    /**
     * Report the index in provided PartRef's sequence of the (first) 2-staff PartRef.
     *
     * @param sequence sequence of partRef's
     * @return index of bi-staff part in sequence, or -1 if not found
     */
    private int biIndex (List<PartRef> sequence)
    {
        for (PartRef partRef : sequence) {
            if (partRef.getStaffCount() == 2) {
                return sequence.indexOf(partRef);
            }
        }

        return -1;
    }

    //---------//
    // collate //
    //---------//
    /**
     * The heart of the part collation algorithm, when we collate parts across several pages.
     *
     * @param sequences a list of sequences of candidate parts (one sequence = one system)
     */
    private void collate (List<List<PartRef>> sequences)
    {
        // Piano-like part record found, if any
        Record biRecord = null;

        // Process each sequence of candidate parts in turn
        // One such sequence = one system
        for (int iSeq = 0; iSeq < sequences.size(); iSeq++) {
            final List<PartRef> sequence = sequences.get(iSeq);
            final int biIndex = biIndex(sequence);

            // Respect manual assignments if any
            final Set<Record> manuals = new LinkedHashSet<>();
            for (PartRef partRef : sequence) {
                if (partRef.isManual()) {
                    final Record record = getRecord(partRef.getLogicalId());
                    if (record != null) {
                        manuals.add(record);
                        record.partRefs.add(partRef);
                    }
                }
            }

            if (hinted) {
                align(sequence, manuals);
                continue;
            }

            if (iSeq == 0) {
                dispatch(sequence, records, +1, manuals);
            } else {
                if ((biRecord != null) && (biIndex != -1)) {
                    // Align on the biRecord
                    biRecord.partRefs.add(sequence.get(biIndex));

                    // Process parts above biRecord
                    dispatch(
                            sequence.subList(0, biIndex),
                            records.subList(0, records.indexOf(biRecord)),
                            -1,
                            manuals);

                    // Process parts below biRecord
                    dispatch(
                            sequence.subList(biIndex + 1, sequence.size()),
                            records.subList(records.indexOf(biRecord) + 1, records.size()),
                            +1,
                            manuals);
                } else {
                    dispatch(sequence, records, -1, manuals);
                }
            }

            if (biRecord == null) {
                biRecord = getBiRecord();
            }
        }

        if (!logicalsLocked) {
            // Assign ids to logical parts
            renumberRecords();
        }

        if (hinted) {
            // Hinted logicals without any affiliated part are kept (dummy parts on export)
            logger.info(
                    "Parts hint: {} logical(s), {} extra",
                    records.stream().filter(r -> r.hint).count(),
                    records.stream().filter(r -> !r.hint).count());
        }
    }

    //-------//
    // align //
    //-------//
    /**
     * Map the parts of a system to the hinted logical parts.
     * <p>
     * Staff count and vertical order are strict constraints, while the part name is only used
     * as a soft cost, since OCR on part names is not reliable.
     * Hinted logicals absent from the system (e.g. hidden empty staves) are simply skipped.
     * A system part that cannot be mapped gets a new (extra) logical, so that no content is lost.
     *
     * @param sequence the system parts, top down
     * @param manuals  records already used by manual assignment
     */
    private void align (List<PartRef> sequence,
                        Set<Record> manuals)
    {
        final List<PartRef> parts = new ArrayList<>();
        for (PartRef partRef : sequence) {
            if (!partRef.isManual()) {
                parts.add(partRef);
            }
        }

        final List<Record> hints = new ArrayList<>();
        for (Record record : records) {
            if (record.hint) {
                hints.add(record);
            }
        }

        // cost[i][j]: best cost to process parts[0..i) with hints[0..j)
        final int m = parts.size();
        final int n = hints.size();
        final double[][] cost = new double[m + 1][n + 1];
        final int[][] move = new int[m + 1][n + 1]; // 1: match, 2: skip hint, 3: skip part

        for (int i = 0; i <= m; i++) {
            for (int j = 0; j <= n; j++) {
                if (i == 0 && j == 0) {
                    continue;
                }

                cost[i][j] = Double.MAX_VALUE;

                if (i > 0 && j > 0) {
                    final Record record = hints.get(j - 1);
                    final PartRef partRef = parts.get(i - 1);

                    if (!manuals.contains(record)
                            && record.logical.getStaffCount() == partRef.getStaffCount()) {
                        final double c = cost[i - 1][j - 1] + nameCost(partRef.getName(), record);

                        if (c < cost[i][j]) {
                            cost[i][j] = c;
                            move[i][j] = 1;
                        }
                    }
                }

                if (j > 0 && cost[i][j - 1] < cost[i][j]) {
                    cost[i][j] = cost[i][j - 1];
                    move[i][j] = 2;
                }

                if (i > 0 && cost[i - 1][j] + UNMAPPED_COST < cost[i][j]) {
                    cost[i][j] = cost[i - 1][j] + UNMAPPED_COST;
                    move[i][j] = 3;
                }
            }
        }

        // Backtrack
        final Record[] mapped = new Record[m];
        for (int i = m, j = n; i > 0 || j > 0;) {
            switch (move[i][j]) {
            case 1 -> mapped[--i] = hints.get(--j);
            case 2 -> j--;
            default -> i--;
            }
        }

        for (int i = 0; i < m; i++) {
            final PartRef partRef = parts.get(i);
            final Record record = mapped[i];

            if (record != null) {
                if (record.partRefs.isEmpty()) {
                    // Adopt the actual staff configuration (line counts, small)
                    record.logical.setStaffConfigs(partRef.getStaffConfigs());
                }

                record.partRefs.add(partRef);
                logger.debug("{} mapped to hinted {}", partRef, record.logical);
            } else {
                logger.info("Part {} does not fit parts hint, extra logical", partRef);
                addExtraRecord(partRef);
            }
        }
    }

    //----------------//
    // addExtraRecord //
    //----------------//
    /**
     * Assign a part that does not fit the parts hint to an extra record.
     *
     * @param partRef the unmapped part
     */
    private void addExtraRecord (PartRef partRef)
    {
        for (Record record : records) {
            if (!record.hint
                    && record.logical.getStaffCount() == partRef.getStaffCount()
                    && Objects.equals(record.logical.getName(), partRef.getName())) {
                record.partRefs.add(partRef);
                return;
            }
        }

        addRecord(+1, partRef, records);
    }

    //----------//
    // nameCost //
    //----------//
    /**
     * Report how badly an OCR'ed part name fits a hinted record.
     *
     * @param ocrName the part name as read by OCR, perhaps null
     * @param record  the hinted record
     * @return the cost, 0 for a perfect fit
     */
    private static double nameCost (String ocrName,
                                     Record record)
    {
        final PartName ocr = PartName.parse(ocrName);

        if (ocr == null) {
            return 0;
        }

        double best = Double.MAX_VALUE;

        for (String alias : new String[]{record.logical.getName(), record.logical.getAbbreviation()}) {
            final PartName hint = PartName.parse(alias);

            if (hint != null) {
                best = Math.min(best, ocr.costTo(hint));
            }
        }

        return (best == Double.MAX_VALUE) ? 0 : best;
    }

    //-------------------//
    // getHintedLogicals //
    //-------------------//
    /**
     * Build the logical parts defined by the user parts hint, if any.
     * <p>
     * Syntax: parts separated by ';', each part as
     * <code>name[|abbreviation]:staffCount[:lyrics]</code>, top down.
     * Names are optional, e.g. "A.Piano|A.pf:2; Strings I|Str. I:1" or "2;1;1".
     * The optional ":lyrics" flag is used by {@link #getHintedLyricsStaves()},
     * the optional ":drums" flag by {@link #getHintedDrumNames()}.
     *
     * @return the hinted logicals, or null if no (valid) hint
     */
    public static List<LogicalPart> getHintedLogicals ()
    {
        final String str = constants.partsHint.getValue();

        if ((str == null) || str.isBlank()) {
            return null;
        }

        try {
            final List<LogicalPart> logicals = new ArrayList<>();

            for (String token : str.split(";")) {
                token = token.trim();

                if (token.isEmpty()) {
                    continue;
                }

                final HintEntry entry = HintEntry.parse(token);
                final String names = entry.names;
                final int staffCount = entry.staffCount;
                final List<StaffConfig> configs = new ArrayList<>();

                for (int i = 0; i < staffCount; i++) {
                    configs.add(new StaffConfig(5, false));
                }

                final LogicalPart logical = new LogicalPart(
                        logicals.size() + 1,
                        staffCount,
                        configs);

                if (!names.isEmpty()) {
                    final String[] aliases = names.split("\\|");
                    logical.setName(aliases[0].trim());

                    if (aliases.length > 1) {
                        logical.setAbbreviation(aliases[1].trim());
                    }
                }

                logicals.add(logical);
            }

            return logicals.isEmpty() ? null : logicals;
        } catch (Exception ex) {
            logger.warn("Invalid partsHint constant: \"{}\"", str);
            return null;
        }
    }

    //--------------------//
    // getHintedDrumNames //
    //--------------------//
    /**
     * Report the names of the hinted parts flagged ":drums".
     * <p>
     * Which part is the drum set is known by the user (e.g. "Bass:1; Drums|Dr.:1:drums"),
     * while Audiveris recognizes a drum staff only by its percussion clef: many band scores
     * print the drums with a bass clef.
     *
     * @return the (main) names of the flagged parts, perhaps empty
     */
    public static Set<String> getHintedDrumNames ()
    {
        final Set<String> names = new HashSet<>();
        final String str = constants.partsHint.getValue();

        if ((str == null) || str.isBlank()) {
            return names;
        }

        try {
            for (String token : str.split(";")) {
                token = token.trim();

                if (token.isEmpty()) {
                    continue;
                }

                final HintEntry entry = HintEntry.parse(token);

                if (entry.drums && !entry.names.isEmpty()) {
                    names.add(entry.names.split("\\|")[0].trim());
                }
            }

            return names;
        } catch (Exception ex) {
            return new HashSet<>();
        }
    }

    //-----------------------//
    // getHintedLyricsStaves //
    //-----------------------//
    /**
     * Report, for each staff of a complete system (top down, as described by the parts hint),
     * whether lyrics may be found there: only the staves of parts flagged ":lyrics".
     * <p>
     * Which parts carry lyrics is known by the user (e.g. "Vocal|Vo.:1:lyrics; Guitar:2"),
     * while text roles are guessed (TEXTS step) long before parts are collated.
     *
     * @return the per-staff lyrics flags, or null if no hint or no part is flagged for lyrics
     */
    public static List<Boolean> getHintedLyricsStaves ()
    {
        final String str = constants.partsHint.getValue();

        if ((str == null) || str.isBlank()) {
            return null;
        }

        try {
            final List<Boolean> flags = new ArrayList<>();
            boolean any = false;

            for (String token : str.split(";")) {
                token = token.trim();

                if (token.isEmpty()) {
                    continue;
                }

                final HintEntry entry = HintEntry.parse(token);
                any |= entry.lyrics;

                for (int i = 0; i < entry.staffCount; i++) {
                    flags.add(entry.lyrics);
                }
            }

            return any ? flags : null;
        } catch (Exception ex) {
            return null;
        }
    }

    //----------//
    // dispatch //
    //----------//
    /**
     * Dispatch the list of candidate PartRef's (the parts of a system) to the current list
     * of records.
     *
     * @param sequence the (sub-system) candidate parts to dispatch
     * @param records  the [sub-]list of records available
     * @param dir      -1 or +1 for browsing up or down
     * @param manuals  records already used by manual assignment
     */
    private void dispatch (List<PartRef> sequence,
                           List<Record> records,
                           int dir,
                           Set<Record> manuals)
    {
        final int ic1 = (dir > 0) ? 0 : (sequence.size() - 1); // Starting sequence index value
        final int ic2 = (dir > 0) ? sequence.size() : (-1); // Breaking sequence index value
        int recordIndex = (dir > 0) ? (-1) : records.size(); // Current index in defined records

        CandidateLoop:
        for (int ic = ic1; ic != ic2; ic += dir) {
            final PartRef partRef = sequence.get(ic);
            final List<StaffConfig> staffConfigs = partRef.getStaffConfigs();
            logger.debug("\nCandidate {}", partRef.toQualifiedString());

            if (partRef.isManual()) {
                continue; // Candidate part already assigned manually
            }

            // Check against defined records
            recordIndex += dir;

            for (; ((dir > 0) && (recordIndex < records.size())) || ((dir < 0)
                    && (recordIndex >= 0)); recordIndex += dir) {
                final Record record = records.get(recordIndex);

                if (manuals.contains(record)) {
                    continue; // Candidate part must skip this record
                }

                final LogicalPart logical = record.logical;
                logger.debug("  Comparing with {}", logical);

                // Check parts are compatible in terms of staves counts
                if (logical.getStaffCount() != partRef.getStaffCount()) {
                    logger.debug("   Staff count incompatibility");
                    continue;
                }

                // Check parts are compatible in terms of line counts
                // For backward compatibility w/ old OMRs, check is made only if line counts exist
                if (!staffConfigs.isEmpty() //
                        && !logical.getStaffConfigs().isEmpty() //
                        && !Objects.deepEquals(logical.getStaffConfigs(), staffConfigs)) {
                    logger.debug("    Line counts incompatibility");
                    continue;
                }

                // Check candidate name
                final String name = partRef.getName();
                if ((name != null) //
                        && !name.equalsIgnoreCase(logical.getName()) //
                        && !name.equalsIgnoreCase(logical.getAbbreviation())) {
                    logger.debug("    Name incompatibility");
                    continue;
                }

                logger.debug("    Success");
                record.partRefs.add(partRef);

                // Use name of affiliate part to define abbreviation of logical?
                final String resAbbrev = logical.getAbbreviation();
                if (resAbbrev == null) {
                    final String resName = logical.getName();
                    final String affiName = partRef.getName();
                    if ((affiName != null) //
                            && !affiName.equals(resName) //
                            && (resName == null || affiName.length() < logical.getName().length()) //
                            && !logicalNames.contains(affiName)) {
                        logical.setAbbreviation(affiName);
                    }
                }

                continue CandidateLoop;
            }

            logger.debug("  No more records available");

            if (!logicalsLocked) {
                addRecord(dir, partRef, records); // Create a brand new record for this candidate
            } else {
                logger.info("  Cannot map {} to any logical", partRef.toQualifiedString());
            }
        }
    }

    //-------------//
    // dumpRecords //
    //-------------//
    /**
     * Dump content of collated records.
     */
    public void dumpRecords ()
    {
        StringBuilder sb = new StringBuilder();

        for (Record record : records) {
            sb.append("\n").append(record.logical);

            for (PartRef partRef : record.partRefs) {
                final SystemRef system = partRef.getSystem();
                final int rank = 1 + system.getParts().indexOf(partRef);
                final PageRef page = system.getPage();
                final SheetStub stub = page.getStub();

                sb.append("\n   ") //
                        .append(partRef) //
                        .append(" rank:").append(rank) //
                        .append(" in ").append(stub) //
                        .append(", Page#").append(page.getId()) //
                        .append(", System#").append(system.getId());
            }
        }

        logger.info("PartCollation records:{}", sb);
    }

    //-------------//
    // getBiRecord //
    //-------------//
    /**
     * Report the (first) record, if any, among the current sequence of records, which could
     * be the piano part.
     *
     * @return the 2-staff piano record found or null
     */
    private Record getBiRecord ()
    {
        for (Record record : records) {
            final List<StaffConfig> configs = record.logical.getStaffConfigs();

            if (Objects.deepEquals(configs, PIANO_CONFIG)) {
                return record;
            }
        }

        return null;
    }

    //-----------//
    // getRecord //
    //-----------//
    /**
     * Report the Record for the provided logical ID.
     *
     * @param logicalId the provided logical id
     * @return the Record found or null
     */
    private Record getRecord (int logicalId)
    {
        for (Record record : records) {
            if (record.logical.getId() == logicalId) {
                return record;
            }
        }

        logger.warn("Cannot find logical for id {}", logicalId);
        return null;
    }

    //------------//
    // getRecords //
    //------------//
    /**
     * Report the collation records.
     *
     * @return the collation records
     */
    public List<Record> getRecords ()
    {
        return records;
    }

    //-----------------//
    // renumberRecords //
    //-----------------//
    /**
     * Renumber the records.
     */
    private void renumberRecords ()
    {
        for (int i = 0; i < records.size(); i++) {
            final Record record = records.get(i);
            final int id = i + 1;
            record.logical.setId(id);
            logger.debug("Final {}", record.logical);
        }
    }

    //~ Inner Classes ------------------------------------------------------------------------------

    //-----------//
    // Constants //
    //-----------//
    private static class Constants
            extends ConstantSet
    {
        private final Constant.String pianoStaffConfig = new Constant.String(
                "5,5",
                "Typical staff configuration for the piano part");

        private final Constant.String partsHint = new Constant.String(
                "",
                "Parts of the score, top down, as \"name[|abbrev]:staffCount[:lyrics|:drums]\""
                        + " separated by ';' (e.g. \"Vocal:1:lyrics; Piano:2; Drums|Dr.:1:drums\")."
                        + " ':lyrics' restricts lyrics to the flagged parts,"
                        + " ':drums' exports the flagged part as drum set. Empty means no hint.");
    }

    //-----------//
    // HintEntry //
    //-----------//
    /**
     * One part of the parts hint: "name[|abbrev]:staffCount[:lyrics][:drums]".
     */
    private static class HintEntry
    {
        final String names;

        final int staffCount;

        final boolean lyrics;

        final boolean drums;

        HintEntry (String names,
                   int staffCount,
                   boolean lyrics,
                   boolean drums)
        {
            this.names = names;
            this.staffCount = staffCount;
            this.lyrics = lyrics;
            this.drums = drums;
        }

        static HintEntry parse (String token)
        {
            final String[] fields = token.split(":");
            boolean lyrics = false;
            boolean drums = false;
            int last = fields.length - 1;

            // Trailing flags, after the staff count
            while ((last > 0) && !fields[last].trim().matches("\\d+")) {
                final String flag = fields[last].trim();

                if (flag.equalsIgnoreCase("lyrics")) {
                    lyrics = true;
                } else if (flag.equalsIgnoreCase("drums")) {
                    drums = true;
                } else {
                    throw new IllegalArgumentException("Unknown partsHint flag: " + flag);
                }

                last--;
            }

            final int staffCount = Integer.parseInt(fields[last].trim());
            final String names = String.join(":", java.util.Arrays.copyOfRange(fields, 0, last))
                    .trim();

            if (drums && names.isEmpty()) {
                throw new IllegalArgumentException("partsHint ':drums' needs a part name");
            }

            return new HintEntry(names, staffCount, lyrics, drums);
        }
    }

    //----------//
    // PartName //
    //----------//
    /**
     * A part name split into its family (e.g. "strings") and its numeral (e.g. 2 for "II"),
     * tolerant to typical OCR confusions on roman numerals (l, |, 1 for I; u, n, H for II).
     */
    static class PartName
    {
        /** Letters of the name, without numeral, lower case. Perhaps empty. */
        final String family;

        /** Numeral value, or null if none or unreadable. */
        final Integer numeral;

        PartName (String family,
                  Integer numeral)
        {
            this.family = family;
            this.numeral = numeral;
        }

        static PartName parse (String name)
        {
            if ((name == null) || name.isBlank()) {
                return null;
            }

            final String[] tokens = name.toLowerCase().trim().split("[\\s.]+");
            int end = tokens.length;
            final StringBuilder strokes = new StringBuilder();

            while (end > 0 && tokens[end - 1].matches("[il|!1unhv0-9'\u2018\u2019]+")) {
                strokes.insert(0, tokens[--end]);
            }

            final StringBuilder family = new StringBuilder();
            for (int i = 0; i < end; i++) {
                family.append(tokens[i].replaceAll("[^a-z]", ""));
            }

            return new PartName(family.toString(), numeralOf(strokes.toString()));
        }

        private static Integer numeralOf (String strokes)
        {
            if (strokes.isEmpty()) {
                return null;
            }

            final String digits = strokes.replaceAll("[^2-9]", "");
            if (!digits.isEmpty()) {
                return Integer.valueOf(digits.substring(0, 1));
            }

            final String roman = strokes.replaceAll("[l|!1]", "i").replaceAll("[unh]", "ii")
                    .replaceAll("[^iv]", "");

            return switch (roman) {
            case "i" -> 1;
            case "ii" -> 2;
            case "iii" -> 3;
            case "iv" -> 4;
            case "v" -> 5;
            case "vi" -> 6;
            default -> null;
            };
        }

        double costTo (PartName that)
        {
            double cost = 0;

            if (!family.isEmpty() && !that.family.isEmpty()) {
                if (!family.startsWith(that.family) && !that.family.startsWith(family)) {
                    final boolean samePrefix = family.length() >= 2 && that.family.length() >= 2
                            && family.substring(0, 2).equals(that.family.substring(0, 2));
                    cost += samePrefix ? 0.5 : 2;
                }
            }

            if (numeral != null && that.numeral != null) {
                if (!numeral.equals(that.numeral)) {
                    cost += 1.5;
                }
            } else if (numeral != null || that.numeral != null) {
                cost += 0.25;
            }

            return cost;
        }
    }

    //--------//
    // Record //
    //--------//
    /**
     * Records a LogicalPart with its affiliated (physical) PartRef's.
     */
    public static class Record
    {
        /** Recording logical part. */
        final LogicalPart logical;

        /** Affiliated candidate parts. */
        final List<PartRef> partRefs = new ArrayList<>();

        /** True if logical comes from user parts hint. */
        boolean hint;

        public Record (LogicalPart logical)
        {
            this.logical = logical;
        }

        @Override
        public String toString ()
        {
            return new StringBuilder(getClass().getSimpleName()).append('{') //
                    .append(logical) //
                    .append(" affs:").append(partRefs.size())//
                    .append('}').toString();
        }
    }
}
