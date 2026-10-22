// Export a searchable index of the analyzed program:
//   functions.csv  : address, name, size, caller count
//   strings.csv    : address, length, referencing functions, string value
//   magic_refs.txt : code and data locations that hold the .mad magic 0x0BADBABE
// Usage (headless):  -process MadMapperDemo.exe -noanalysis -postScript ExportIndex.java <outdir>
//@category MadMapperStudy

import java.io.File;
import java.io.FileWriter;
import java.io.PrintWriter;
import java.util.ArrayList;
import java.util.List;
import java.util.TreeSet;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.DataIterator;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.scalar.Scalar;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;
import ghidra.program.model.symbol.ReferenceManager;

public class ExportIndex extends GhidraScript {

    private static String csv(String s) {
        if (s == null) {
            return "";
        }
        String t = s.replace("\r", "\\r").replace("\n", "\\n").replace("\"", "\"\"");
        return "\"" + t + "\"";
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 1) {
            printerr("usage: ExportIndex.java <outdir>");
            return;
        }
        File outDir = new File(args[0]);
        outDir.mkdirs();
        ReferenceManager refMgr = currentProgram.getReferenceManager();

        // ---- functions.csv
        int fnCount = 0;
        try (PrintWriter w = new PrintWriter(new FileWriter(new File(outDir, "functions.csv")))) {
            w.println("address,name,size,callers");
            FunctionIterator it = currentProgram.getFunctionManager().getFunctions(true);
            while (it.hasNext() && !monitor.isCancelled()) {
                Function f = it.next();
                int callers = 0;
                ReferenceIterator ri = refMgr.getReferencesTo(f.getEntryPoint());
                while (ri.hasNext()) {
                    if (ri.next().getReferenceType().isCall()) {
                        callers++;
                    }
                }
                w.println(f.getEntryPoint() + "," + csv(f.getName()) + "," + f.getBody().getNumAddresses() + "," + callers);
                fnCount++;
            }
        }
        println("functions: " + fnCount);

        // ---- strings.csv
        int strCount = 0;
        try (PrintWriter w = new PrintWriter(new FileWriter(new File(outDir, "strings.csv")))) {
            w.println("address,length,functions,value");
            DataIterator di = currentProgram.getListing().getDefinedData(true);
            while (di.hasNext() && !monitor.isCancelled()) {
                Data d = di.next();
                if (!d.hasStringValue()) {
                    continue;
                }
                Object v = d.getValue();
                if (v == null) {
                    continue;
                }
                String s = v.toString();
                if (s.length() < 4) {
                    continue;
                }
                TreeSet<String> fns = new TreeSet<>();
                ReferenceIterator ri = refMgr.getReferencesTo(d.getAddress());
                while (ri.hasNext()) {
                    Reference r = ri.next();
                    Function f = getFunctionContaining(r.getFromAddress());
                    if (f != null) {
                        fns.add(f.getName() + "@" + f.getEntryPoint());
                    }
                }
                w.println(d.getAddress() + "," + s.length() + "," + csv(String.join(";", fns)) + "," + csv(s));
                strCount++;
            }
        }
        println("strings: " + strCount);

        // ---- magic_refs.txt : immediates and raw bytes for 0x0BADBABE
        List<String> hits = new ArrayList<>();
        InstructionIterator ii = currentProgram.getListing().getInstructions(true);
        long n = 0;
        while (ii.hasNext() && !monitor.isCancelled()) {
            Instruction ins = ii.next();
            n++;
            for (int op = 0; op < ins.getNumOperands(); op++) {
                for (Object o : ins.getOpObjects(op)) {
                    if (o instanceof Scalar) {
                        long val = ((Scalar) o).getUnsignedValue();
                        if (val == 0x0BADBABEL || val == 0xBEBAAD0BL) {
                            Function f = getFunctionContaining(ins.getAddress());
                            hits.add("code " + ins.getAddress() + " " + ins + "  in " + (f == null ? "?" : f.getName() + "@" + f.getEntryPoint()));
                        }
                    }
                }
            }
        }
        println("instructions scanned: " + n);
        Memory mem = currentProgram.getMemory();
        byte[][] patterns = { { 0x0B, (byte) 0xAD, (byte) 0xBA, (byte) 0xBE }, { (byte) 0xBE, (byte) 0xBA, (byte) 0xAD, 0x0B } };
        for (byte[] pat : patterns) {
            Address a = mem.getMinAddress();
            while (a != null && !monitor.isCancelled()) {
                Address found = mem.findBytes(a, pat, null, true, monitor);
                if (found == null) {
                    break;
                }
                Function f = getFunctionContaining(found);
                hits.add("bytes " + found + " " + (pat[0] == 0x0B ? "BE" : "LE") + "  in " + (f == null ? "data" : f.getName() + "@" + f.getEntryPoint()));
                a = found.add(1);
            }
        }
        try (PrintWriter w = new PrintWriter(new FileWriter(new File(outDir, "magic_refs.txt")))) {
            for (String h : hits) {
                w.println(h);
            }
        }
        println("magic refs: " + hits.size());
    }
}
