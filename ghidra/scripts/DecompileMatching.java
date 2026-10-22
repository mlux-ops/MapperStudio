// Decompile every function whose name matches a regex (or whose entry address is listed)
// and write one .c file per function into <outdir>.
// Usage (headless): -process MadMapperDemo.exe -noanalysis
//                   -postScript DecompileMatching.java <outdir> <regex-or-addrlist> [maxFunctions]
// <regex-or-addrlist> is either a Java regex matched against the function name, or a
// comma-separated list of hex entry addresses (e.g. 140a1b2c0,140a1c000).
//@category MadMapperStudy

import java.io.File;
import java.io.FileWriter;
import java.io.PrintWriter;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;

public class DecompileMatching extends GhidraScript {

    private static String safeName(String s) {
        String t = s.replaceAll("[^A-Za-z0-9_.-]", "_");
        return t.length() > 80 ? t.substring(0, 80) : t;
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 2) {
            printerr("usage: DecompileMatching.java <outdir> <regex-or-addrlist> [maxFunctions]");
            return;
        }
        File outDir = new File(args[0]);
        outDir.mkdirs();
        // Headless splits script args on commas, so the selector uses '+' as separator and
        // an optional trailing "max=N" argument limits regex matches.
        int max = 200;
        StringBuilder sel = new StringBuilder();
        for (int i = 1; i < args.length; i++) {
            if (args[i].startsWith("max=")) {
                max = Integer.parseInt(args[i].substring(4));
            } else {
                if (sel.length() > 0) {
                    sel.append('+');
                }
                sel.append(args[i]);
            }
        }
        String selector = sel.toString();

        List<Function> targets = new ArrayList<>();
        if (selector.matches("[0-9a-fA-F]+([+,][0-9a-fA-F]+)*")) {
            for (String hex : selector.split("[+,]")) {
                Address a = toAddr(Long.parseLong(hex, 16));
                Function f = getFunctionAt(a);
                if (f == null) {
                    f = getFunctionContaining(a);
                }
                if (f != null) {
                    targets.add(f);
                } else {
                    printerr("no function at " + hex);
                }
            }
        } else {
            Pattern p = Pattern.compile(selector);
            FunctionIterator it = currentProgram.getFunctionManager().getFunctions(true);
            while (it.hasNext()) {
                Function f = it.next();
                if (p.matcher(f.getName()).find()) {
                    targets.add(f);
                    if (targets.size() >= max) {
                        break;
                    }
                }
            }
        }
        println("targets: " + targets.size());

        DecompInterface decomp = new DecompInterface();
        decomp.toggleCCode(true);
        decomp.toggleSyntaxTree(true);
        decomp.setSimplificationStyle("decompile");
        if (!decomp.openProgram(currentProgram)) {
            printerr("decompiler failed to open program: " + decomp.getLastMessage());
            return;
        }
        try (PrintWriter index = new PrintWriter(new FileWriter(new File(outDir, "_index.txt"), true))) {
            for (Function f : targets) {
                if (monitor.isCancelled()) {
                    break;
                }
                DecompileResults res = decomp.decompileFunction(f, 180, monitor);
                String fileName = f.getEntryPoint() + "_" + safeName(f.getName()) + ".c";
                File out = new File(outDir, fileName);
                try (PrintWriter w = new PrintWriter(new FileWriter(out))) {
                    w.println("// " + f.getName() + " @ " + f.getEntryPoint() + "  size=" + f.getBody().getNumAddresses());
                    w.println("// signature: " + f.getSignature(true));
                    if (res != null && res.decompileCompleted() && res.getDecompiledFunction() != null) {
                        w.println(res.getDecompiledFunction().getC());
                    } else {
                        w.println("// DECOMPILE FAILED: " + (res == null ? "null" : res.getErrorMessage()));
                    }
                }
                index.println(f.getEntryPoint() + " " + f.getName() + " -> " + fileName);
                println("wrote " + fileName);
            }
        } finally {
            decomp.dispose();
        }
    }
}
