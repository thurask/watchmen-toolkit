// Clear a wrongly inferred "no return" flag and re-body every caller.
//
// Ghidra decided FUN_0047eccc (Kapow's command-registration function) never
// returns, so each per-class registration function stops at its first call to
// it and ~1.5 MB of code is left undisassembled.  This script clears the flag
// on the given functions (default: found automatically), disassembles the fall-through of
// every call to them, and rebuilds the callers' bodies.  Safe to re-run.
// Arguments: none or "auto" = every flagged function that contains a RET;
// otherwise hex addresses.
//@category Kapow
import java.util.*;
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;

public class FixNoReturn extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        List<Address> targets = new ArrayList<>();
        boolean auto = args.length == 0 || args[0].equalsIgnoreCase("auto");
        if (auto) {
            // Every internal function flagged no-return whose own body contains a RET
            // was flagged by inference, not by fact (0x47eccc, 0x5a0dfd, ...).
            for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
                if (!f.hasNoReturn() || f.isExternal() || f.isThunk()) continue;
                InstructionIterator it = currentProgram.getListing().getInstructions(f.getBody(), true);
                while (it.hasNext()) {
                    if (it.next().getMnemonicString().startsWith("RET")) {
                        targets.add(f.getEntryPoint());
                        break;
                    }
                }
            }
            println("FixNoReturn: " + targets.size() + " returning functions carry a no-return flag");
        } else {
            for (String a : args) targets.add(toAddr(Long.parseLong(a.replace("0x", ""), 16)));
        }
        // The "discovered" no-return analyzer is what set the flag; left on, it sets
        // it again during the re-analysis that follows this script.
        try {
            setAnalysisOption(currentProgram, "Non-Returning Functions - Discovered", "false");
        } catch (Exception e) {
            println("FixNoReturn: could not switch off the no-return discovery analyzer: " + e);
        }
        FunctionManager fm = currentProgram.getFunctionManager();
        Listing listing = currentProgram.getListing();
        for (Address h : targets) {
            Function f0 = fm.getFunctionAt(h);
            if (f0 == null) { println("FixNoReturn: no function at " + h); continue; }
            boolean was = f0.hasNoReturn();
            f0.setNoReturn(false);
            Set<Function> touched = new LinkedHashSet<>();
            int calls = 0, disassembled = 0;
            for (Reference ref : getReferencesTo(h)) {
                if (monitor.isCancelled()) break;
                if (!ref.getReferenceType().isCall()) continue;
                calls++;
                Instruction ins = listing.getInstructionAt(ref.getFromAddress());
                if (ins == null) continue;
                if (ins.getFlowOverride() != FlowOverride.NONE) ins.setFlowOverride(FlowOverride.NONE);
                Address next = ins.getMaxAddress().add(1);
                if (listing.getInstructionAt(next) == null) {
                    if (listing.getDataContaining(next) != null) clearListing(next);
                    new DisassembleCommand(next, null, true).applyTo(currentProgram, monitor);
                    disassembled++;
                }
                Function f = fm.getFunctionContaining(ref.getFromAddress());
                if (f != null) touched.add(f);
            }
            int grown = 0;
            for (Function f : touched) {
                if (monitor.isCancelled()) break;
                long before = f.getBody().getNumAddresses();
                CreateFunctionCmd.fixupFunctionBody(currentProgram, f, monitor);
                if (f.getBody().getNumAddresses() > before) grown++;
            }
            println(String.format(
                "FixNoReturn %s: flag was %s, %d calls, %d fall-throughs disassembled, "
                + "%d callers re-bodied (%d grew)", h, was, calls, disassembled, touched.size(), grown));
        }
    }
}
