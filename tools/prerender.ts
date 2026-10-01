// Quarto pre-render hook (set in the course's _quarto.yml):
//   pre-render: _extensions/se-slides/tools/prerender.ts
// Finds a JDK 25 and runs BuildCode.java in the course folder.
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
