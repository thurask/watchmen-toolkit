// Decompile functions to shard files in the ghidra_kapow_out layout.
// args: OUTDIR [ADDRLIST_FILE]   (no list = every function)
//@category Kapow
import java.io.*;
import java.util.*;
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;

public class DumpDecomp extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        File out = new File(args[0]);
        new File(out, "decomp").mkdirs();
        List<Function> todo = new ArrayList<>();
        FunctionManager fm = currentProgram.getFunctionManager();
        if (args.length > 1) {
            try (BufferedReader r = new BufferedReader(new FileReader(args[1]))) {
                String l;
                while ((l = r.readLine()) != null) {
                    l = l.trim().split("\t")[0];
                    if (l.isEmpty()) continue;
                    Function f = fm.getFunctionAt(toAddr(Long.parseLong(l.replace("0x", ""), 16)));
                    if (f != null) todo.add(f);
                }
            }
        } else {
            for (Function f : fm.getFunctions(true)) if (!f.isExternal() && !f.isThunk()) todo.add(f);
        }
        DecompInterface d = new DecompInterface();
        d.openProgram(currentProgram);
        PrintWriter idx = new PrintWriter(new FileWriter(new File(out, "index.tsv")));
        idx.println("address\tname\tsize\tn_callers\tn_callees\tpart");
        int part = 0, inPart = 0, n = 0; long bytes = 0;
        PrintWriter w = null;
        for (Function f : todo) {
            if (monitor.isCancelled()) break;
            if (w == null || bytes > 1500000) {
                if (w != null) w.close();
                part++; bytes = 0;
                w = new PrintWriter(new FileWriter(new File(out, String.format("decomp/part_%04d.c", part))));
            }
            StringBuilder callers = new StringBuilder(), callees = new StringBuilder();
            int nc = 0, ne = 0;
            for (Reference ref : getReferencesTo(f.getEntryPoint())) {
                if (ref.getReferenceType().isCall() || ref.getReferenceType().isData()) {
                    if (nc < 40) callers.append(" 0x").append(String.format("%08x", ref.getFromAddress().getOffset()));
                    nc++;
                }
            }
            for (Function c : f.getCalledFunctions(monitor)) {
                if (ne < 60) callees.append(" 0x").append(String.format("%08x", c.getEntryPoint().getOffset()));
                ne++;
            }
            long size = f.getBody().getNumAddresses();
            String code;
            DecompileResults res = d.decompileFunction(f, 120, monitor);
            if (res != null && res.decompileCompleted()) code = res.getDecompiledFunction().getC();
            else code = "/* DECOMPILE FAILED: " + (res == null ? "null" : res.getErrorMessage()) + " */\n";
            StringBuilder s = new StringBuilder();
            s.append("// ============================================================\n");
            s.append(String.format("// FUNC %s @ 0x%08x   size=%d\n", f.getName(), f.getEntryPoint().getOffset(), size));
            s.append("//   callers:").append(callers).append(nc > 40 ? " (+" + (nc - 40) + ")" : "").append("\n");
            s.append("//   callees:").append(callees).append("\n");
            String cm = f.getComment();
            if (cm != null) for (String l : cm.split("\n")) s.append("//   ").append(l).append("\n");
            s.append("// ============================================================\n");
            s.append(code).append("\n\n");
            w.print(s); bytes += s.length();
            idx.println(String.format("0x%08x\t%s\t%d\t%d\t%d\tpart_%04d.c", f.getEntryPoint().getOffset(), f.getName(), size, nc, ne, part));
            if (++n % 1000 == 0) println("decompiled " + n + "/" + todo.size());
        }
        if (w != null) w.close();
        idx.close();
        println("DumpDecomp: " + n + " functions, " + part + " parts -> " + out);
    }
}
