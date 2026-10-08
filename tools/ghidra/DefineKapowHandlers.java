// Define and name the Kapow engine's registered command handlers.
//
// Reads a tab-separated table (address-hex, name, <ignored>, comment) and, for
// each row, makes sure a function exists at that address (disassembling first
// if needed), names it, and sets a plate comment listing the Class.command
// registrations that point at it.  Existing user-chosen names are kept.
//
// Run from the Script Manager (it asks for handlers.tsv) or headless with the
// path as the script argument.  Safe to re-run.
//@category Kapow
import java.io.*;
import java.util.*;
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;

public class DefineKapowHandlers extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        File f = args.length > 0 ? new File(args[0]) : askFile("handlers.tsv", "Use");
        int created = 0, named = 0, kept = 0, failed = 0, inside = 0;
        List<String> problems = new ArrayList<>();
        Listing listing = currentProgram.getListing();
        FunctionManager fm = currentProgram.getFunctionManager();
        try (BufferedReader r = new BufferedReader(new FileReader(f))) {
            String line;
            while ((line = r.readLine()) != null) {
                if (monitor.isCancelled()) break;
                String[] c = line.split("\t");
                if (c.length < 2 || c[0].isEmpty()) continue;
                Address a = toAddr(Long.parseLong(c[0], 16));
                String name = c[1];
                String note = c.length > 3 ? c[3] : "";
                Function fn = fm.getFunctionAt(a);
                if (fn == null) {
                    Function outer = fm.getFunctionContaining(a);
                    if (outer != null) {
                        // A handler that starts inside another function's body:
                        // record it, label it, and leave the outer body alone.
                        inside++;
                        problems.add(c[0] + " " + name + " lies inside " + outer.getName());
                        try { createLabel(a, name, true, SourceType.USER_DEFINED); }
                        catch (Exception e) { /* label is a convenience only */ }
                        continue;
                    }
                    if (listing.getInstructionAt(a) == null) {
                        if (listing.getDataContaining(a) != null) clearListing(a);
                        new DisassembleCommand(a, null, true).applyTo(currentProgram, monitor);
                    }
                    if (listing.getInstructionAt(a) == null) {
                        // Something else (usually a mis-typed data run or an
                        // instruction that straddles the address) is in the way.
                        try {
                            clearListing(a.subtract(8), a.add(32));
                            new DisassembleCommand(a, null, true).applyTo(currentProgram, monitor);
                        } catch (Exception e) { /* reported below */ }
                    }
                    if (listing.getInstructionAt(a) == null) {
                        failed++; problems.add(c[0] + " " + name + " does not disassemble");
                        continue;
                    }
                    fn = createFunction(a, null);
                    if (fn == null) {
                        failed++; problems.add(c[0] + " " + name + " createFunction failed");
                        continue;
                    }
                    created++;
                }
                if (fn.getSymbol().getSource() == SourceType.DEFAULT
                        || fn.getName().startsWith("FUN_")) {
                    try {
                        fn.setName(name, SourceType.USER_DEFINED);
                    } catch (ghidra.util.exception.DuplicateNameException e) {
                        fn.setName(name + "_" + c[0], SourceType.USER_DEFINED);
                    }
                    named++;
                } else {
                    kept++;
                }
                if (!note.isEmpty()) {
                    String old = fn.getComment();
                    String tag = (note.startsWith("high:") || note.startsWith("medium:") ? "Kapow name evidence, " : "Kapow handler: ") + note;
                    if (old == null || !old.contains("Kapow handler:")) {
                        fn.setComment(old == null ? tag : old + "\n" + tag);
                    }
                }
            }
        }
        println(String.format(
            "DefineKapowHandlers: created %d, named %d, kept existing name %d, "
            + "inside another function %d, failed %d",
            created, named, kept, inside, failed));
        for (String p : problems) println("  " + p);
    }
}
