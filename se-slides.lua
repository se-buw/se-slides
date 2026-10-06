--[[
SE Slides filter. Short reference (details: README.md of the se-slides extension):

Listing from a file (path relative to the deck's code folder code/<deck-file-name>/):
  ```{.java include=CountTiles.java snippet=loop}
  ```
  snippet=name   lines between `// region name` and `// endregion`
  lines=5-9      a line range
  output=right   generated program output next to the code (split=58: code column width in %)
  output=below   generated output below the code
  Line numbers are the file's line numbers. Below the listing: file name, copy,
  "Open in VS Code" and (if repo-url is set) a link to the file on the web.

Generated output alone:
  ```{.output of=CountTiles.java}
  ```

Question slides (code first, output on click 1, answer on click 2; answer also in the speaker notes):
  ::: question
  ```{.java include=ExtraSemicolon.java snippet=loop output=below}
  ```
  ::: answer
  Explanation ...
  :::
  :::
  Options on the question: answer=right (answer in a column next to the rest), split=55.

Images need alt text and an entry in images/credits.yml; a credits slide is appended.
COURSE_LENIENT=1: errors become warnings. COURSE_STRICT=1: fail on `::: todo` blocks.
]]

local lib = dofile(quarto.utils.resolve_path("lib.lua"))
local strict = os.getenv("COURSE_STRICT") == "1"
local used_credits = {}
local credits = nil
local todo_count = 0

local function attr_without(el, names)
  local attrs = {}
  for k, v in pairs(el.attributes) do
    if not names[k] then attrs[k] = v end
  end
  return attrs
end

local LISTING_ATTRS = { include = true, snippet = true, lines = true, output = true, split = true }

function CodeBlock(el)
  local inc = el.attributes["include"]
  if inc then
    local listing = lib.listing(inc, {
      snippet = el.attributes["snippet"],
      lines = el.attributes["lines"],
      classes = el.classes,
      attributes = attr_without(el, LISTING_ATTRS),
      id = el.identifier,
    })
    local blocks = lib.with_output(listing, inc, el.attributes["output"], tonumber(el.attributes["split"] or ""))
    if #blocks == 1 then return blocks[1] end
    return pandoc.Div(blocks)
  end
  if el.classes:includes("output") and el.attributes["of"] then
    return lib.output(el.attributes["of"])
  end
  return nil
end

-- ::: question ... ::: answer ... ::: :::
local function question(el)
  local main, answers = pandoc.Blocks({}), pandoc.Blocks({})
  for _, b in ipairs(el.content) do
    if b.t == "Div" and b.classes:includes("answer") then answers:insert(b) else main:insert(b) end
  end
  -- click 1: every generated output inside the question
  main = pandoc.Div(main):walk({
    Div = function(d)
      if d.classes:includes("output-block") and not d.classes:includes("fragment") then
        d.classes:insert("fragment")
        d.attributes["fragment-index"] = "1"
        return d
      end
    end,
  }).content
  -- click 2: the answer
  local notes = pandoc.Blocks({ pandoc.Para({ pandoc.Strong("Answer:") }) })
  for _, a in ipairs(answers) do
    a.classes:insert("fragment")
    a.attributes["fragment-index"] = "2"
    notes:extend(a.content:clone())
  end
  local body
  if el.attributes["answer"] == "right" then
    body = { lib.columns(main, answers, tonumber(el.attributes["split"] or "") or 55) }
  else
    body = main .. answers
  end
  local result = pandoc.Blocks({ pandoc.Div(body, { class = "question" }) })
  if #answers > 0 then result:insert(pandoc.Div(notes, { class = "notes" })) end
  return result
end

local function load_credits()
  if credits then return credits end
  credits = {}
  local text = lib.read_file("images/credits.yml")
  if not text then return credits end
  local meta = pandoc.read("---\ncredits:\n" .. text:gsub("([^\n]*)", "  %1") .. "\n---\n", "markdown").meta
  for _, c in ipairs(meta.credits or {}) do
    local file = pandoc.utils.stringify(c.file or "")
    credits[file] = {
      source = c.source and pandoc.utils.stringify(c.source) or nil,
      license = c.license and pandoc.utils.stringify(c.license) or nil,
      author = c.author and pandoc.utils.stringify(c.author) or nil,
    }
  end
  return credits
end

-- project-relative path of an image referenced from the current document
local function project_rel(src)
  if src:match("^/") then return src:sub(2) end
  local dir = pandoc.path.directory(pandoc.path.make_relative(quarto.doc.input_file, lib.root))
  local parts = {}
  for seg in pandoc.path.join({ dir, src }):gsub("\\", "/"):gmatch("[^/]+") do
    if seg == ".." and #parts > 0 then table.remove(parts) elseif seg ~= "." then parts[#parts + 1] = seg end
  end
  return table.concat(parts, "/")
end

function Image(el)
  local alt = pandoc.utils.stringify(el.caption)
  if el.attributes["fig-alt"] then alt = el.attributes["fig-alt"] end
  if alt == "" then lib.fail("image without alt text: " .. el.src) end
  if el.src:match("^https?:") then
    lib.fail("external image " .. el.src .. " — download it into images/ and add it to images/credits.yml")
    return nil
  end
  local rel = project_rel(el.src)
  if rel:match("^_build/") then return nil end
  local c = load_credits()[rel]
  if not c or not c.source or not c.license then
    lib.fail("image " .. rel .. " has no source/license entry in images/credits.yml")
  elseif not used_credits[rel] then
    used_credits[rel] = true
    used_credits[#used_credits + 1] = rel
  end
  return nil
end

function Div(el)
  if el.classes:includes("question") and not el.attributes["done"] then return question(el) end
  if el.classes:includes("todo") then
    todo_count = todo_count + 1
    -- strict (release) builds fail on todos even when lenient is set
    if strict then error("[course] unresolved ::: todo block: " .. pandoc.utils.stringify(el):sub(1, 80)) end
  end
  return nil
end

local function credits_slide()
  if #used_credits == 0 then return {} end
  local items = {}
  for _, rel in ipairs(used_credits) do
    local c = credits[rel]
    local text = pandoc.path.filename(rel) .. ": " .. c.source
    if c.author then text = text .. ", " .. c.author end
    text = text .. " (" .. c.license .. ")"
    items[#items + 1] = { pandoc.Plain(pandoc.Inlines(text)) }
  end
  return {
    pandoc.Header(2, "Image credits", { class = "credits" }),
    pandoc.BulletList(items),
  }
end

-- Index page: `::: {#lectures}` becomes a table of all lectures (title, subtitle, PDF), read from the
-- front matter of lectures/[0-9]*.qmd. Long lists continue on further slides; the budget is in
-- table lines per slide (metadata lectures-per-slide, default 12), a row counts one line per 70
-- characters of its subtitle, the first slide has 2 lines less for the text above the table.
local function lecture_entries()
  local dir = (quarto.project and quarto.project.directory) or "."
  local ok, names = pcall(pandoc.system.list_directory, dir .. "/lectures")
  if not ok then return {} end
  local files = {}
  for _, n in ipairs(names) do
    if n:match("^%d.*%.qmd$") then table.insert(files, n) end
  end
  table.sort(files)
  local entries = {}
  for _, n in ipairs(files) do
    local f = io.open(dir .. "/lectures/" .. n, "r")
    local text = f and f:read("a") or ""
    if f then f:close() end
    local yaml = text:match("^%-%-%-\r?\n(.-)\r?\n%-%-%-") or ""
    local meta = pandoc.read("---\n" .. yaml .. "\n---\n", "markdown").meta
    local name = n:gsub("%.qmd$", "")
    table.insert(entries, {
      name = name,
      title = meta.title and pandoc.utils.stringify(meta.title) or name,
      subtitle = meta.subtitle and pandoc.utils.stringify(meta.subtitle) or "",
    })
  end
  return entries
end

local function lecture_table(entries)
  local function cell(inlines) return { pandoc.Plain(inlines) } end
  local rows = {}
  for _, e in ipairs(entries) do
    table.insert(rows, {
      cell({ pandoc.Link(e.title, "lectures/" .. e.name .. ".html") }),
      cell({ pandoc.Str(e.subtitle) }),
      cell({ pandoc.Link("PDF", "pdf/" .. e.name .. ".pdf") }),
    })
  end
  local simple = pandoc.SimpleTable({}, { pandoc.AlignDefault, pandoc.AlignDefault, pandoc.AlignDefault },
    { 0.3, 0.6, 0.1 }, { cell({ pandoc.Str("Lecture") }), cell({ pandoc.Str("Topics") }), cell({ pandoc.Str("PDF") }) },
    rows)
  return pandoc.utils.from_simple_table(simple)
end

local function lecture_slides(doc)
  local at
  for i, b in ipairs(doc.blocks) do
    if b.t == "Div" and b.identifier == "lectures" then at = i break end
  end
  if not at then return end
  local budget = tonumber(doc.meta["lectures-per-slide"] and pandoc.utils.stringify(doc.meta["lectures-per-slide"])) or 12
  local chunks, current, used, limit = {}, {}, 0, budget - 2
  for _, e in ipairs(lecture_entries()) do
    local lines = math.max(1, math.ceil(#e.subtitle / 70))
    if #current > 0 and used + lines > limit then
      table.insert(chunks, current)
      current, used, limit = {}, 0, budget
    end
    table.insert(current, e)
    used = used + lines
  end
  if #current > 0 then table.insert(chunks, current) end
  local blocks = {}
  for i, c in ipairs(chunks) do
    if i > 1 then table.insert(blocks, pandoc.Header(2, "Lectures (continued)")) end
    table.insert(blocks, lecture_table(c))
  end
  doc.blocks:remove(at)
  for i = #blocks, 1, -1 do doc.blocks:insert(at, blocks[i]) end
end

return {
  {
    Meta = function(meta)
      if meta["repo-url"] then lib.repo_url = pandoc.utils.stringify(meta["repo-url"]):gsub("/$", "") end
      return nil
    end,
  },
  { CodeBlock = CodeBlock, Image = Image },
  { Div = Div },
  {
    Pandoc = function(doc)
      if quarto.doc.is_format("html") then
        quarto.doc.add_html_dependency({
          name = "se-slides",
          version = "1.0.0",
          scripts = { "se-slides.js", "qrcode.min.js" },
          stylesheets = { "se-slides.css" },
          resources = { "fonts/Jost.ttf", "fonts/JetBrainsMono.ttf", "brand/logo_se.png", "brand/logo_se.ico" },
        })
        if os.getenv("COURSE_LAYOUT_MARKS") == "1" then
          quarto.doc.include_text("in-header", '<meta name="course-layout-marks" content="1">')
        end
        local vroot = os.getenv("COURSE_VSCODE_ROOT")
        if vroot and vroot ~= "" then
          quarto.doc.include_text("in-header",
            '<meta name="course-vscode-root" content="' .. lib.html_escape(vroot:gsub("\\", "/")) .. '">')
        end
      end
      if todo_count > 0 then
        quarto.log.warning("[course] " .. todo_count .. " todo block(s) in " .. quarto.doc.input_file)
      end
      lecture_slides(doc)
      doc.blocks:extend(credits_slide())
      return doc
    end,
  },
}
