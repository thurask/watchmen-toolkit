// Repair the ~2,000 functions Ghidra truncates to a 10-byte stub in KapowMulti.
//
// The MSVC helper __EH_prolog (0x991850 in this build) ends in "push eax; ret",
// which Ghidra's analysis reads as "never returns to the caller".  Every function
// that opens with "mov eax, handler; call __EH_prolog" therefore stops at the call.
// This script names the helper, attaches Ghidra's built-in EH_prolog call-fixup,
// clears the no-return flag, then re-disassembles and re-bodies each caller.
//
// Optional argument: the helper's address (hex).  Safe to re-run.
//@category Kapow
import java.util.*;
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;

public class FixEHProlog extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        Address h = toAddr(args.length > 0 ? Long.parseLong(args[0].replace("0x", ""), 16) : 0x991850L);
        byte[] want = {0x6a, (byte) 0xff, 0x50, 0x64, (byte) 0xa1, 0, 0, 0, 0, 0x50};
        if (!Arrays.equals(getBytes(h, want.length), want)) {
            println("FixEHProlog: " + h + " is not __EH_prolog in this program; nothing done");
            return;
        }
        FunctionManager fm = currentProgram.getFunctionManager();
        Listing listing = currentProgram.getListing();
        Function helper = fm.getFunctionAt(h);
        if (helper == null) helper = createFunction(h, "__EH_prolog");
        if (!helper.getName().equals("__EH_prolog")) helper.setName("__EH_prolog", SourceType.USER_DEFINED);
        helper.setNoReturn(false);
        helper.setCallFixup("EH_prolog");

        Set<Function> touched = new LinkedHashSet<>();
        int disassembled = 0, calls = 0;
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
        int grown = 0, absorbed = 0;
        for (Function f : touched) {
            if (monitor.isCancelled()) break;
            long before = f.getBody().getNumAddresses();
            // Analysis may have started spurious functions in what is really this
            // function's body (the code right after the prologue call); drop those
            // that nothing calls so the body can be rebuilt across them.
            Address after = f.getBody().getMaxAddress().add(1);
            Function squat = fm.getFunctionAt(after);
            if (squat != null && squat.getSymbol().getSource() == SourceType.DEFAULT) {
                boolean called = false;
                for (Reference r : getReferencesTo(after)) {
                    if (r.getReferenceType().isCall() || r.getReferenceType().isData()) { called = true; break; }
                }
                if (!called) { fm.removeFunction(after); absorbed++; }
            }
            CreateFunctionCmd.fixupFunctionBody(currentProgram, f, monitor);
            if (f.getBody().getNumAddresses() > before) grown++;
        }
        println(String.format(
            "FixEHProlog: %d calls, %d fall-throughs disassembled, %d functions re-bodied "
            + "(%d grew, %d spurious starts absorbed)",
            calls, disassembled, touched.size(), grown, absorbed));
    }
}
