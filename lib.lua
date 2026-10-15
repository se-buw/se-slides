--[[
Shared functions of the filter (se-slides.lua) and the shortcodes (shortcodes.lua):
code listings from files, generated program output, and side-by-side layouts.
Loaded with dofile(quarto.utils.resolve_path("lib.lua")).
]]

local M = {}

M.root = quarto.project.directory or "."
M.lenient = os.getenv("COURSE_LENIENT") == "1"
M.repo_url = nil
M.default_split = 58 -- width of the code column in % for output=right

function M.fail(msg)
  if M.lenient then
    quarto.log.warning("[course] " .. msg)
  else
    error("[course] " .. msg)
  end
end

function M.read_file(rel)
  local f = io.open(pandoc.path.join({ M.root, rel }), "rb")
  if not f then return nil end
  local s = f:read("a")
  f:close()
  return (s:gsub("\r\n", "\n"))
end

function M.html_escape(s)
  return (s:gsub("&", "&amp;"):gsub("<", "&lt;"):gsub(">", "&gt;"):gsub('"', "&quot;"))
end

-- Code folder of the current deck: lectures/05-loops.qmd -> code/05-loops
function M.deck_dir()
  local name = pandoc.path.split_extension(pandoc.path.filename(quarto.doc.input_file))
  return "code/" .. name
end

-- "CountTiles.java" -> "code/05-loops/CountTiles.java"; paths starting with code/ stay as they are.
function M.resolve(path)
  path = path:gsub("\\", "/")
  if path:match("^code/") then return path end
  return M.deck_dir() .. "/" .. path
end

local function split_lines(s)
  local t = {}
  for line in (s:gsub("\n$", "") .. "\n"):gmatch("(.-)\n") do t[#t + 1] = line end
  return t
end

local function is_region_start(line) return line:match("^%s*//%s*region%s+([%w%-_]+)%s*$") end
local function is_region_end(line) return line:match("^%s*//%s*endregion") ~= nil end
-- build markers (// @run, // @args ..., // @expect-exception, // @expect-error) are not shown
-- (also with an explanation after them: "// @expect-error: the last snippet throws")
local markers = { run = true, args = true, ["expect-exception"] = true, ["expect-error"] = true }
local function is_marker(line)
  local name = line:match("^%s*//%s*@([%w%-]+)")
  return name ~= nil and markers[name] == true
end

local function dedent(lines)
  local min = nil
  for _, l in ipairs(lines) do
    if l:match("%S") then
      local n = #l:match("^( *)")
      if not min or n < min then min = n end
    end
  end
  if not min or min == 0 then return lines end
  local out = {}
  for i, l in ipairs(lines) do out[i] = l:sub(min + 1) end
  return out
end

-- Select the lines to show. Returns list of lines and the first line number.
local function select_lines(lines, snip, range, inc)
  if snip then
    local first, last
    for i, l in ipairs(lines) do
      if not first and is_region_start(l) == snip then
        first = i + 1
      elseif first and is_region_end(l) then
        last = i - 1
        break
      end
    end
    if not first or not last then
      M.fail("region '" .. snip .. "' not found (or not closed) in " .. inc)
      return { "// missing region " .. snip }, 1
    end
    local out = {}
    for i = first, last do
      if is_region_start(lines[i]) or is_region_end(lines[i]) then
        M.fail("nested region markers in region '" .. snip .. "' of " .. inc)
      end
      out[#out + 1] = lines[i]
    end
    return out, first
  elseif range then
    local a, b = range:match("^(%d+)%-(%d+)$")
    a, b = tonumber(a), tonumber(b)
    if not a or b > #lines or a > b then
      M.fail("bad lines='" .. range .. "' for " .. inc)
      return lines, 1
    end
    return { table.unpack(lines, a, b) }, a
  else
    for _, l in ipairs(lines) do
      if is_region_start(l) or is_region_end(l) then
        M.fail(inc .. " contains region markers; use snippet= or lines= to include it")
        break
      end
    end
    local a, b = 1, #lines
    while a <= b and (is_marker(lines[a]) or (a > 1 and not lines[a]:match("%S"))) do a = a + 1 end
    while b >= a and (is_marker(lines[b]) or not lines[b]:match("%S")) do b = b - 1 end
    if a == 1 and b == #lines then return lines, 1 end
    return { table.unpack(lines, a, b) }, a
  end
end

local function action_bar(inc, first, last)
  local label = inc:gsub("^code/", "")
  if last then label = label .. ", lines " .. first .. "–" .. last end
  local parts = { '<span class="code-file">' .. M.html_escape(label) .. '</span>' }
  if inc:match("%.jsh$") then
    parts[#parts + 1] = '<span class="code-badge">jshell</span>'
  elseif inc:match("%.java$") then
    parts[#parts + 1] = string.format(
      '<button class="vscode-open" data-file="%s" data-line="%d" title="Open in VS Code (debug with F5)">Open in VS Code</button>',
      M.html_escape(inc), first)
    parts[#parts + 1] = '<button class="vscode-root" title="Set the local path of the course repository">&#9881;</button>'
  end
  if M.repo_url then
    parts[#parts + 1] = string.format('<a class="code-web" href="%s/blob/main/%s#L%d-L%d">web</a>',
      M.html_escape(M.repo_url), M.html_escape(inc), first, last or first)
  end
  return pandoc.RawBlock("html", '<div class="code-actions">' .. table.concat(parts, " ") .. '</div>')
end

--- A listing of (part of) a file.
-- opts: snippet, lines, classes (list), attributes (table, e.g. code-line-numbers)
-- Returns a Div.listing (HTML) or a CodeBlock.
function M.listing(path, opts)
  opts = opts or {}
  local inc = M.resolve(path)
  local text = M.read_file(inc)
  if not text then
    M.fail("cannot read " .. inc)
    return pandoc.CodeBlock("// missing file " .. inc)
  end
  local lines = split_lines(text)
  local shown, first = select_lines(lines, opts.snippet, opts.lines, inc)
  shown = dedent(shown)
  local last = first + #shown - 1
  local classes = pandoc.List(opts.classes or {})
  if #classes == 0 and (inc:match("%.java$") or inc:match("%.jsh$")) then classes:insert("java") end
  if inc:match("%.in$") and #classes == 0 then classes:insert("text") end
  if not classes:includes("numberLines") then classes:insert("numberLines") end
  local attrs = {}
  for k, v in pairs(opts.attributes or {}) do attrs[k] = v end
  attrs["startFrom"] = tostring(first)
  local block = pandoc.CodeBlock(table.concat(shown, "\n"), pandoc.Attr(opts.id or "", classes, attrs))
  if not quarto.doc.is_format("html") then return block end
  local whole = (not opts.snippet and not opts.lines) or (first == 1 and last == #lines)
  return pandoc.Div({ block, action_bar(inc, first, not whole and last or nil) }, { class = "listing" })
end

-- _build/out/... file that holds the generated output of a code file
local function output_path(inc)
  local lec, rest = inc:match("^code/([^/]+)/(.+)$")
  if not lec then return nil end
  if rest:match("%.jsh$") then return "_build/out/" .. lec .. "/" .. rest .. ".txt" end
  return "_build/out/" .. lec .. "/" .. rest:gsub("%.java$", ".txt")
end

--- The generated output of a program, jshell file or broken file, as Div.output-block.
-- opts.actions: add the action bar of the file, at the first line the compiler reports
function M.output(path, opts)
  opts = opts or {}
  local inc = M.resolve(path)
  local file = output_path(inc)
  local text = file and M.read_file(file)
  if not text then
    M.fail("no generated output for " .. inc .. " (expected " .. tostring(file)
      .. "; is there a .in file or // @run marker?)")
    text = "(output missing)"
  end
  local block = pandoc.CodeBlock((text:gsub("\n+$", "")),
    pandoc.Attr("", { "output" }, { ["code-line-numbers"] = "false" }))
  if not (opts.actions and quarto.doc.is_format("html")) then
    return pandoc.Div({ block }, { class = "output-block" })
  end
  -- "UninitializedVariable.java:5: error: ..." -> line 5
  local name = pandoc.path.filename(inc):gsub("%p", "%%%0")
  local line = text:match("^" .. name .. ":(%d+):") or text:match("\n" .. name .. ":(%d+):")
  return pandoc.Div({ block, action_bar(inc, tonumber(line) or 1) }, { class = "output-block listing" })
end

--- Two columns: left blocks, right blocks; split = width of the left column in %.
function M.columns(left, right, split)
  split = split or M.default_split
  return pandoc.Div({
    pandoc.Div(left, pandoc.Attr("", { "column" }, { width = split .. "%" })),
    pandoc.Div(right, pandoc.Attr("", { "column" }, { width = (100 - split) .. "%" })),
  }, { class = "columns" })
end

--- Listing plus its output: mode "right", "below" or "none"/nil.
function M.with_output(listing, path, mode, split)
  if not mode or mode == "none" then return { listing } end
  local out = M.output(path)
  if mode == "right" then return { M.columns({ listing }, { out }, split) } end
  if mode == "below" then return { listing, out } end
  M.fail("output must be right, below or none, not '" .. mode .. "'")
  return { listing }
end

return M
