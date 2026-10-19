// Quarto pre-render hook (set in the course's _quarto.yml):
//   pre-render: _extensions/se-slides/tools/prerender.ts
// Finds a JDK 25 and runs BuildCode.java in the course folder; then writes the Particify questions (below).
// JDK search order: $COURSE_JAVA, the shared tool cache (see bootstrap.ps1), $JAVA_HOME, java on PATH.
const isWin = Deno.build.os === "windows";
const exe = isWin ? "java.exe" : "java";
const toolsDir = new URL(".", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");

function exists(p: string): boolean {
  try {
    Deno.statSync(p);
    return true;
  } catch {
    return false;
  }
}

function toolCache(): string {
  const own = Deno.env.get("SE_SLIDES_HOME");
  if (own) return own;
  if (isWin) return `${Deno.env.get("LOCALAPPDATA")}/se-slides`;
  return `${Deno.env.get("HOME")}/.cache/se-slides`;
}

function findJava(): string {
  const env = Deno.env.get("COURSE_JAVA");
  if (env) return env;
  const cached = `${toolCache()}/jdk/bin/${exe}`;
  if (exists(cached)) return cached;
  const home = Deno.env.get("JAVA_HOME");
  if (home && exists(`${home}/bin/${exe}`)) return `${home}/bin/${exe}`;
  return "java";
}

const java = findJava();
const cmd = new Deno.Command(java, {
  args: [`${toolsDir}BuildCode.java`],
  env: { SE_SLIDES_TOOLS: toolsDir },
  stdout: "inherit",
  stderr: "inherit",
});
const { code } = await cmd.output();
if (code !== 0) {
  console.error(`BuildCode failed (exit ${code}) using ${java}`);
  Deno.exit(code);
}

// Particify: if the course has a particify/ folder, write particify/<deck>.csv from the quiz slides of each
// rendered deck (tools/particify.lua), as UTF-16 LE with BOM like Particify's export. Unchanged files stay untouched.
function findPandoc(): string {
  const p = isWin ? "pandoc.exe" : "pandoc";
  const tools = Deno.execPath().replace(/[\\/][^\\/]+$/, ""); // Quarto's deno: bin/tools/<arch>/deno
  for (const dir of [tools, tools.replace(/[\\/][^\\/]+$/, "")]) {
    if (exists(`${dir}/${p}`)) return `${dir}/${p}`;
  }
  return "pandoc";
}

function utf16(text: string): Uint8Array {
  const bytes = new Uint8Array(2 + 2 * text.length);
  bytes[0] = 0xff;
  bytes[1] = 0xfe;
  for (let i = 0; i < text.length; i++) {
    const c = text.charCodeAt(i);
    bytes[2 + 2 * i] = c & 0xff;
    bytes[3 + 2 * i] = c >> 8;
  }
  return bytes;
}

function sameBytes(file: string, bytes: Uint8Array): boolean {
  try {
    const old = Deno.readFileSync(file);
    return old.length === bytes.length && old.every((b, i) => b === bytes[i]);
  } catch {
    return false;
  }
}

if (exists("particify")) {
  const listed = (Deno.env.get("QUARTO_PROJECT_INPUT_FILES") ?? "").split("\n").filter((f) => f.trim());
  const decks = (listed.length ? listed : [...Deno.readDirSync("lectures")].map((e) => `lectures/${e.name}`))
    .map((f) => f.trim().replace(/\\/g, "/"))
    .filter((f) => /(^|\/)lectures\/\d[^/]*\.qmd$/.test(f))
    .map((f) => f.replace(/^.*?(lectures\/)/, "$1"));
  const pandoc = findPandoc();
  for (const deck of decks) {
    const out = await new Deno.Command(pandoc, {
      args: [deck, "-f", "markdown-smart", "-t", `${toolsDir}particify.lua`],
      stdout: "piped",
      stderr: "inherit",
    }).output();
    if (out.code !== 0) {
      console.error(`Particify questions of ${deck} failed (exit ${out.code}) using ${pandoc}`);
      Deno.exit(out.code);
    }
    const text = new TextDecoder().decode(out.stdout).replace(/\r\n/g, "\n");
    if (!text) continue;
    const file = `particify/${deck.replace(/^lectures\//, "").replace(/\.qmd$/, ".csv")}`;
    const bytes = utf16(text);
    if (!sameBytes(file, bytes)) {
      Deno.writeFileSync(file, bytes);
      console.log(`Particify: ${file}`);
    }
  }
}
