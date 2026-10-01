import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.TreeMap;
import java.util.concurrent.TimeUnit;
import java.util.stream.Stream;
import javax.tools.Diagnostic;
import javax.tools.DiagnosticCollector;
import javax.tools.JavaCompiler;
import javax.tools.JavaFileObject;
import javax.tools.StandardJavaFileManager;
import javax.tools.ToolProvider;
import jdk.jshell.ExpressionSnippet;
import jdk.jshell.JShell;
import jdk.jshell.Snippet;
import jdk.jshell.SnippetEvent;
import jdk.jshell.SourceCodeAnalysis;
import jdk.jshell.VarSnippet;

/**
 * Checks and prepares all course code before the slides are rendered.
 *
 * For every lecture folder code/NN-name/ it
 *  1. compiles all *.java files (javac --release 25 -Xlint:all) into _build/classes/NN-name,
 *  2. runs every program that has an input file X.in or a "// @run" marker and
 *     writes the console transcript to _build/out/NN-name/X.txt,
 *  3. evaluates every *.jsh file with JShell and writes a jshell-style transcript
 *     to _build/out/NN-name/X.jsh.txt,
 *  4. checks that every file in broken/ really fails to compile and writes the
 *     compiler message to _build/out/NN-name/broken/X.txt,
 * and finally checks that class names are unique across all lectures and writes
 * the source paths into .vscode/settings.json.
 *
 * Markers in Java files: "// @run" (run without input), "// @expect-exception"
 * (a non-zero exit is the point of the example). In .jsh files: "// @expect-error".
 *
 * Usage (in the course folder): java _extensions/se-slides/tools/BuildCode.java [lecture ...]
 *        (default: all lectures)
 * Quarto calls it as pre-render script and passes the files being rendered in
 * QUARTO_PROJECT_INPUT_FILES; only the matching lectures are built then.
 */
public class BuildCode {

    static final Path ROOT = Path.of("").toAbsolutePath();
    static final Path CODE = ROOT.resolve("code");
    static final Path BUILD = ROOT.resolve("_build");
    /** Folder of this tool; set by prerender.ts, defaults to the extension inside the course. */
    static final Path TOOLS = Path.of(System.getenv().getOrDefault("SE_SLIDES_TOOLS",
            ROOT.resolve("_extensions").resolve("se-slides").resolve("tools").toString()));
    static final int RELEASE = 25;
    static final int RUN_TIMEOUT_SECONDS = 20;

    static int errors = 0;
    static int warnings = 0;

    public static void main(String[] args) throws Exception {
        if (Runtime.version().feature() < RELEASE) {
            System.err.println("BuildCode needs JDK " + RELEASE + "+, running on " + Runtime.version()
                    + ". Run _extensions/se-slides/tools/bootstrap.ps1 or set COURSE_JAVA.");
            System.exit(2);
        }
        // Same results on every machine (jshell snippets run inside this JVM)
        Locale.setDefault(Locale.US);
        java.util.TimeZone.setDefault(java.util.TimeZone.getTimeZone("Europe/Berlin"));
        List<String> lectures = selectLectures(args);
        Path tools = compileTools();
        for (String lecture : lectures) {
            buildLecture(lecture, tools);
        }
        checkUniqueClassNames();
        writeVsCodeSettings();
        System.out.printf("BuildCode: %d lecture(s), %d warning(s), %d error(s)%n",
                lectures.size(), warnings, errors);
        if (errors > 0) System.exit(1);
    }

    // ---------------------------------------------------------------- selection

    static List<String> allLectures() throws IOException {
        if (!Files.isDirectory(CODE)) return List.of();
        try (Stream<Path> s = Files.list(CODE)) {
            return s.filter(Files::isDirectory)
                    .map(p -> p.getFileName().toString())
                    .filter(n -> n.matches("\\d\\d[a-z]?-.*"))
                    .sorted().toList();
        }
    }

    static List<String> selectLectures(String[] args) throws IOException {
        List<String> all = allLectures();
        List<String> wanted = new ArrayList<>(List.of(args));
        String inputs = System.getenv("QUARTO_PROJECT_INPUT_FILES");
        boolean renderAll = System.getenv("QUARTO_PROJECT_RENDER_ALL") != null;
        if (wanted.isEmpty() && inputs != null && !renderAll) {
            for (String line : inputs.split("\\R")) {
                String name = Path.of(line.trim()).getFileName().toString().replaceFirst("\\.qmd$", "");
                wanted.add(name);
            }
        }
        if (wanted.isEmpty()) return all;
        // "05-loops" or just "05"
        return all.stream().filter(l -> wanted.stream().anyMatch(w -> l.equals(w) || l.startsWith(w + "-"))).toList();
    }

    // ---------------------------------------------------------------- per lecture

    static void buildLecture(String lecture, Path tools) throws Exception {
        Path src = CODE.resolve(lecture);
        Path classes = BUILD.resolve("classes").resolve(lecture);
        Path out = BUILD.resolve("out").resolve(lecture);
        deleteTree(classes);
        deleteTree(out);
        Files.createDirectories(classes);
        Files.createDirectories(out);

        List<Path> javaFiles = listFiles(src, ".java");
        if (!javaFiles.isEmpty()) {
            boolean ok = compile(javaFiles, classes, lecture, true);
            if (ok) {
                for (Path f : javaFiles) runIfWanted(f, classes, tools, out);
            }
        }
        for (Path jsh : listFiles(src, ".jsh")) runJShell(jsh, out.resolve(jsh.getFileName() + ".txt"));
        Path broken = src.resolve("broken");
        if (Files.isDirectory(broken)) {
            Files.createDirectories(out.resolve("broken"));
            for (Path f : listFiles(broken, ".java")) checkBroken(f, out.resolve("broken"));
        }
    }

    static List<Path> listFiles(Path dir, String ext) throws IOException {
        if (!Files.isDirectory(dir)) return List.of();
        try (Stream<Path> s = Files.list(dir)) {
            return s.filter(p -> p.toString().endsWith(ext)).sorted().toList();
        }
    }

    // ---------------------------------------------------------------- compiling

    static boolean compile(List<Path> files, Path classes, String label, boolean report) throws IOException {
        JavaCompiler javac = ToolProvider.getSystemJavaCompiler();
        DiagnosticCollector<JavaFileObject> diags = new DiagnosticCollector<>();
        try (StandardJavaFileManager fm = javac.getStandardFileManager(diags, Locale.ENGLISH, StandardCharsets.UTF_8)) {
            List<String> options = List.of("--release", String.valueOf(RELEASE), "-Xlint:all",
                    "-encoding", "UTF-8", "-d", classes.toString());
            boolean ok = javac.getTask(null, fm, diags, options, null,
                    fm.getJavaFileObjectsFromPaths(files)).call();
            if (report) {
                for (Diagnostic<? extends JavaFileObject> d : diags.getDiagnostics()) {
                    String where = d.getSource() == null ? label
                            : ROOT.relativize(Path.of(d.getSource().toUri())) + ":" + d.getLineNumber();
                    String kind = d.getKind() == Diagnostic.Kind.ERROR ? "error" : "warning";
                    System.out.println(where + ": " + kind + ": " + d.getMessage(Locale.ENGLISH));
                    if (d.getKind() == Diagnostic.Kind.ERROR) errors++;
                    else if (d.getKind() == Diagnostic.Kind.WARNING || d.getKind() == Diagnostic.Kind.MANDATORY_WARNING) warnings++;
                }
            }
            return ok;
        }
    }

    static Path compileTools() throws IOException {
        Path out = BUILD.resolve("tools");
        Path src = TOOLS.resolve("EchoRunner.java");
        Path cls = out.resolve("EchoRunner.class");
        if (!Files.exists(cls) || Files.getLastModifiedTime(cls).compareTo(Files.getLastModifiedTime(src)) < 0) {
            Files.createDirectories(out);
            if (!compile(List.of(src), out, "tools", true)) throw new IllegalStateException("cannot compile EchoRunner");
        }
        return out;
    }

    /** Files in broken/ demonstrate compiler errors: they must fail, and the message is recorded. */
    static void checkBroken(Path file, Path out) throws IOException {
        Path tmp = Files.createTempDirectory("broken");
        JavaCompiler javac = ToolProvider.getSystemJavaCompiler();
        DiagnosticCollector<JavaFileObject> diags = new DiagnosticCollector<>();
        boolean ok;
        try (StandardJavaFileManager fm = javac.getStandardFileManager(diags, Locale.ENGLISH, StandardCharsets.UTF_8)) {
            ok = javac.getTask(null, fm, diags, List.of("--release", String.valueOf(RELEASE), "-d", tmp.toString()),
                    null, fm.getJavaFileObjectsFromPaths(List.of(file))).call();
        }
        deleteTree(tmp);
        String rel = ROOT.relativize(file).toString().replace('\\', '/');
        if (ok) {
            System.out.println(rel + ": error: expected a compile error, but the file compiles");
            errors++;
            return;
        }
        StringBuilder sb = new StringBuilder();
        int count = 0;
        for (Diagnostic<? extends JavaFileObject> d : diags.getDiagnostics()) {
            if (d.getKind() != Diagnostic.Kind.ERROR) continue;
            count++;
            sb.append(file.getFileName()).append(':').append(d.getLineNumber()).append(": error: ")
              .append(d.getMessage(Locale.ENGLISH)).append('\n');
            String line = sourceLine(file, (int) d.getLineNumber());
            if (line != null) {
                sb.append(line).append('\n');
                sb.append(" ".repeat((int) Math.max(0, d.getColumnNumber() - 1))).append("^\n");
            }
        }
        sb.append(count).append(count == 1 ? " error\n" : " errors\n");
        Files.writeString(out.resolve(file.getFileName().toString().replaceFirst("\\.java$", ".txt")), sb.toString());
    }

    static String sourceLine(Path file, int n) throws IOException {
        List<String> lines = Files.readAllLines(file);
        return n >= 1 && n <= lines.size() ? lines.get(n - 1) : null;
    }

    // ---------------------------------------------------------------- running

    static void runIfWanted(Path file, Path classes, Path tools, Path out) throws Exception {
        String text = Files.readString(file);
        String name = file.getFileName().toString().replaceFirst("\\.java$", "");
        Path input = file.resolveSibling(name + ".in");
        boolean hasInput = Files.exists(input);
        if (!hasInput && !text.contains("// @run")) return;
        if (!text.contains("static void main")) {
            System.out.println(ROOT.relativize(file) + ": error: marked for running but has no main method");
            errors++;
            return;
        }
        boolean expectException = text.contains("// @expect-exception");
        String java = ProcessHandle.current().info().command().orElse("java");
        List<String> cmd = List.of(java,
                "-Duser.language=en", "-Duser.country=US", "-Duser.timezone=Europe/Berlin",
                "-Dstdout.encoding=UTF-8", "-Dstderr.encoding=UTF-8",
                "-cp", classes + File.pathSeparator + tools, "EchoRunner", name);
        ProcessBuilder pb = new ProcessBuilder(cmd).redirectErrorStream(true);
        pb.redirectInput(hasInput ? ProcessBuilder.Redirect.from(input.toFile())
                : ProcessBuilder.Redirect.from(new File(System.getProperty("os.name").startsWith("Windows") ? "NUL" : "/dev/null")));
        Process p = pb.start();
        byte[] bytes;
        try (var in = p.getInputStream()) {
            bytes = in.readAllBytes();
        }
        if (!p.waitFor(RUN_TIMEOUT_SECONDS, TimeUnit.SECONDS)) {
            p.destroyForcibly();
            System.out.println(ROOT.relativize(file) + ": error: did not finish within " + RUN_TIMEOUT_SECONDS + " s");
            errors++;
            return;
        }
        String transcript = new String(bytes, StandardCharsets.UTF_8).replace("\r\n", "\n");
        Files.writeString(out.resolve(name + ".txt"), transcript);
        int exit = p.exitValue();
        if (exit != 0 && !expectException) {
            System.out.println(ROOT.relativize(file) + ": error: exit code " + exit + "\n" + indent(transcript));
            errors++;
        } else if (exit == 0 && expectException) {
            System.out.println(ROOT.relativize(file) + ": error: marked @expect-exception but finished normally");
            errors++;
        }
    }

    // ---------------------------------------------------------------- jshell

    static void runJShell(Path file, Path outFile) throws IOException {
        String source = Files.readString(file).replace("\r\n", "\n");
        boolean expectError = source.contains("// @expect-error");
        ByteArrayOutputStream programOut = new ByteArrayOutputStream();
        PrintStream ps = new PrintStream(programOut, true, StandardCharsets.UTF_8);
        StringBuilder transcript = new StringBuilder();
        int failures = 0;
        try (JShell js = JShell.builder().out(ps).err(ps).executionEngine("local").build()) {
            SourceCodeAnalysis sca = js.sourceCodeAnalysis();
            // Like interactive jshell: read line by line, evaluate as soon as a snippet is complete.
            List<String> snippets = new ArrayList<>();
            String buffer = "";
            for (String line : source.split("\n", -1)) {
                buffer += line + "\n";
                while (!buffer.isBlank()) {
                    SourceCodeAnalysis.CompletionInfo ci = sca.analyzeCompletion(buffer);
                    if (ci.completeness() == SourceCodeAnalysis.Completeness.EMPTY) {
                        buffer = "";
                    } else if (ci.completeness().isComplete()) {
                        snippets.add(ci.source());
                        buffer = ci.remaining();
                    } else {
                        break; // needs more lines
                    }
                }
            }
            if (!buffer.isBlank()) {
                transcript.append("|  Error: incomplete input at end of file\n");
                failures++;
            }
            for (String snippet : snippets) {
                String trimmed = stripComments(snippet).strip();
                if (trimmed.isEmpty()) continue;
                transcript.append(prompt(trimmed));
                programOut.reset();
                // the local execution engine runs snippets in this JVM, so capture System.out/err
                PrintStream savedOut = System.out;
                PrintStream savedErr = System.err;
                List<SnippetEvent> events;
                System.setOut(ps);
                System.setErr(ps);
                try {
                    events = js.eval(snippet);
                } finally {
                    System.setOut(savedOut);
                    System.setErr(savedErr);
                }
                for (SnippetEvent ev : events) {
                    ps.flush();
                    transcript.append(programOut.toString(StandardCharsets.UTF_8));
                    programOut.reset();
                    if (ev.causeSnippet() != null) continue;
                    Snippet s = ev.snippet();
                    if (ev.status() == Snippet.Status.REJECTED) {
                        failures++;
                        js.diagnostics(s).forEach(d -> transcript.append("|  Error:\n|  ")
                                .append(d.getMessage(Locale.ENGLISH).replace("\n", "\n|  ")).append('\n'));
                    } else if (ev.exception() != null) {
                        failures++;
                        transcript.append("|  Exception ").append(ev.exception().getClass().getName());
                        if (ev.exception().getMessage() != null) transcript.append(": ").append(ev.exception().getMessage());
                        transcript.append('\n');
                    } else if (s instanceof VarSnippet v && ev.value() != null) {
                        transcript.append(v.name()).append(" ==> ").append(ev.value()).append('\n');
                    } else if (s instanceof ExpressionSnippet e && ev.value() != null) {
                        transcript.append(e.name()).append(" ==> ").append(ev.value()).append('\n');
                    } else if (s.kind() == Snippet.Kind.METHOD) {
                        transcript.append("|  created method ").append(((jdk.jshell.MethodSnippet) s).name()).append("()\n");
                    } else if (s.kind() == Snippet.Kind.TYPE_DECL) {
                        transcript.append("|  created ").append(((jdk.jshell.TypeDeclSnippet) s).name()).append('\n');
                    }
                }
            }
        }
        Files.writeString(outFile, transcript.toString());
        String rel = ROOT.relativize(file).toString();
        if (failures > 0 && !expectError) {
            System.out.println(rel + ": error: jshell reported " + failures + " problem(s)\n" + indent(transcript.toString()));
            errors++;
        } else if (failures == 0 && expectError) {
            System.out.println(rel + ": error: marked @expect-error but all snippets succeeded");
            errors++;
        }
    }

    static String prompt(String snippet) {
        String[] lines = snippet.split("\n");
        StringBuilder sb = new StringBuilder("jshell> ").append(lines[0]).append('\n');
        for (int i = 1; i < lines.length; i++) sb.append("   ...> ").append(lines[i]).append('\n');
        return sb.toString();
    }

    /** Removes whole-line // comments (used for markers and explanations in .jsh files). */
    static String stripComments(String snippet) {
        StringBuilder sb = new StringBuilder();
        for (String line : snippet.split("\n")) {
            if (!line.strip().startsWith("//")) sb.append(line).append('\n');
        }
        return sb.toString();
    }

    // ---------------------------------------------------------------- course-wide checks

    /** All examples share one source root in VS Code, so top-level class names must be unique. */
    static void checkUniqueClassNames() throws IOException {
        Path classesRoot = BUILD.resolve("classes");
        if (!Files.isDirectory(classesRoot)) return;
        Map<String, List<String>> seen = new TreeMap<>();
        try (Stream<Path> s = Files.walk(classesRoot)) {
            s.filter(p -> p.toString().endsWith(".class") && !p.getFileName().toString().contains("$"))
             .forEach(p -> {
                 String lecture = classesRoot.relativize(p).getName(0).toString();
                 String cls = classesRoot.resolve(lecture).relativize(p).toString().replace('\\', '/');
                 seen.computeIfAbsent(cls, k -> new ArrayList<>()).add(lecture);
             });
        }
        seen.forEach((cls, lectures) -> {
            if (lectures.size() > 1) {
                System.out.println("error: class " + cls.replaceFirst("\\.class$", "") + " is defined in several lectures: "
                        + lectures + " (class names must be unique across the course)");
                errors++;
            }
        });
    }

    /** Keeps java.project.sourcePaths in .vscode/settings.json in sync with the lecture folders. */
    static void writeVsCodeSettings() throws IOException {
        Path settings = ROOT.resolve(".vscode").resolve("settings.json");
        if (!Files.exists(settings)) return;
        String text = Files.readString(settings);
        StringBuilder paths = new StringBuilder("\"java.project.sourcePaths\": [");
        List<String> all = allLectures();
        for (int i = 0; i < all.size(); i++) {
            paths.append(i == 0 ? "\n    " : ",\n    ").append('"').append("code/").append(all.get(i)).append('"');
        }
        paths.append("\n  ]");
        String updated = text.replaceFirst("(?s)\"java\\.project\\.sourcePaths\"\\s*:\\s*\\[[^\\]]*\\]",
                java.util.regex.Matcher.quoteReplacement(paths.toString()));
        if (!updated.equals(text)) Files.writeString(settings, updated);
    }

    // ---------------------------------------------------------------- helpers

    static String indent(String s) {
        return s.lines().map(l -> "    " + l).reduce("", (a, b) -> a + b + "\n");
    }

    static void deleteTree(Path dir) throws IOException {
        if (!Files.exists(dir)) return;
        try (Stream<Path> s = Files.walk(dir)) {
            for (Path p : s.sorted((a, b) -> b.getNameCount() - a.getNameCount()).toList()) Files.delete(p);
        }
    }
}
