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

-- Screenshots made by tools/FxShots.java (images/<deck>/screenshots/*.png) need no credits.yml entry:
-- the author is lecturer.name (or screenshots.author) and the licence is screenshots.license, both from
-- _variables.yml.
local screenshot_credit = nil
local function load_screenshot_credit()
  if screenshot_credit then return screenshot_credit end
  screenshot_credit = {}
  local text = lib.read_file("_variables.yml")
  if not text then return screenshot_credit end
  local meta = pandoc.read("---\n" .. text .. "\n---\n", "markdown").meta
  local shots = meta.screenshots
  local author = shots and shots.author or (meta.lecturer and meta.lecturer.name)
  screenshot_credit.author = author and pandoc.utils.stringify(author) or nil
  screenshot_credit.license = shots and shots.license and pandoc.utils.stringify(shots.license) or nil
  return screenshot_credit
end
local used_screenshots = false

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
  if rel:match("^images/[^/]+/screenshots/[^/]+%.png$") then
    local sc = load_screenshot_credit()
    if not sc.author or not sc.license then
      lib.fail("screenshot " .. rel .. ": set screenshots.license in _variables.yml (author: lecturer.name)")
    end
    used_screenshots = true
    return nil
  end
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
  if #used_credits == 0 and not used_screenshots then return {} end
  local items = {}
  for _, rel in ipairs(used_credits) do
    local c = credits[rel]
    local text = pandoc.path.filename(rel) .. ": " .. c.source
    if c.author then text = text .. ", " .. c.author end
    text = text .. " (" .. c.license .. ")"
    items[#items + 1] = { pandoc.Plain(pandoc.Inlines(text)) }
  end
  if used_screenshots then
    local sc = load_screenshot_credit()
    items[#items + 1] = { pandoc.Plain(pandoc.Inlines(
      "Screenshots of the course examples: " .. (sc.author or "?") .. " (" .. (sc.license or "?") .. ")")) }
  end
  return {
    pandoc.Header(2, "Image credits", { class = "credits" }),
    pandoc.BulletList(items),
  }
end

-- Lecture recordings: lectures/<deck>.video.json, written by tools/video.ps1. Returns the videos that
-- have a YouTube ID ({ id, slides = { [slide id] = { seconds, length of the visit } } }), or {}.
local function deck_videos(name)
  local text = lib.read_file("lectures/" .. name .. ".video.json")
  if not text then return {} end
  local ok, data = pcall(pandoc.json.decode, text, false)
  if not ok or type(data) ~= "table" then
    lib.fail("lectures/" .. name .. ".video.json is not valid JSON")
    return {}
  end
  local videos = {}
  for _, v in ipairs(data.videos or {}) do
    if type(v.id) == "string" and v.id:match("^[%w_-]+$") and v.id ~= "TODO" then
      table.insert(videos, { id = v.id, slides = v.slides or {} })
    end
  end
  return videos
end

-- for se-slides.js ("▶ Video" link at every slide)
local function embed_videos()
  local name = pandoc.path.split_extension(pandoc.path.filename(quarto.doc.input_file))
  local videos = deck_videos(name)
  if #videos == 0 then return end
  local json = pandoc.json.encode({ videos = videos }):gsub("</", "<\\/")
  quarto.doc.include_text("after-body", '<script type="application/json" id="course-video">' .. json .. "</script>")
end

-- Index page (format se-slides-html): `::: {#lectures}` becomes a table of all lectures (number,
-- title, slide box, subtitle, PDF, videos), read from the front matter of lectures/[0-9]*.qmd.
local function lecture_entries()
  local dir = (quarto.project and quarto.project.directory) or "."
  local ok, names = pcall(pandoc.system.list_directory, dir .. "/lectures")
  if not ok then return {} end
  -- build --release: only the released lectures (COURSE_RELEASE = their names, space-separated)
  local released = nil
  if os.getenv("COURSE_RELEASE") then
    released = {}
    for name in os.getenv("COURSE_RELEASE"):gmatch("%S+") do released[name] = true end
  end
  local files = {}
  for _, n in ipairs(names) do
    if n:match("^%d.*%.qmd$") and (not released or released[n:gsub("%.qmd$", "")]) then
      table.insert(files, n)
    end
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
      number = name:match("^%d+%a*"),
      title = meta.title and pandoc.utils.stringify(meta.title) or name,
      subtitle = meta.subtitle and pandoc.utils.stringify(meta.subtitle) or "",
      videos = deck_videos(name),
    })
  end
  return entries
end

-- Links open in a new tab (not in-deck anchors, not mailto:)
local function new_tab(el)
  local t = el.target or ""
  if t == "" or t:sub(1, 1) == "#" or t:match("^mailto:") then return nil end
  el.attributes.target = "_blank"
  el.attributes.rel = "noopener noreferrer"
  return el
end

-- The deck link opens in the same tab (H in the deck leads back), PDF and videos in a new one.
-- The slide box submits deck.html?slide=n; se-slides.js opens the deck at that slide.
local NEW_TAB = ' target="_blank" rel="noopener noreferrer"'

local function lecture_list(el)
  if el.identifier ~= "lectures" then return nil end
  local entries = lecture_entries()
  local with_video = false -- Video column as soon as any lecture has a recording
  for _, e in ipairs(entries) do
    if #e.videos > 0 then with_video = true end
  end
  local esc = lib.html_escape
  local rows = { '<table class="lectures"><thead><tr><th>No.</th><th>Lecture</th><th>Slide</th><th>Topics</th><th>PDF</th>'
    .. (with_video and "<th>Video</th>" or "") .. "</tr></thead><tbody>" }
  for _, e in ipairs(entries) do
    local deck = "lectures/" .. e.name .. ".html"
    local row = string.format('<tr><td>%s</td><td><a href="%s">%s</a></td><td><form action="%s">'
      .. '<input name="slide" type="number" min="1" aria-label="%s at slide"></form></td>'
      .. '<td>%s</td><td><a href="pdf/%s.pdf"%s>PDF</a></td>',
      esc(e.number or ""), deck, esc(e.title), deck, esc(e.title), esc(e.subtitle), e.name, NEW_TAB)
    if with_video then
      local links = {}
      for i, v in ipairs(e.videos) do
        links[i] = string.format('<a href="https://youtu.be/%s"%s>%s</a>', v.id, NEW_TAB, #e.videos == 1 and "Video" or i)
      end
      row = row .. "<td>" .. table.concat(links, " ") .. "</td>"
    end
    table.insert(rows, row .. "</tr>")
  end
  table.insert(rows, "</tbody></table>")
  return pandoc.RawBlock("html", table.concat(rows, "\n"))
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
  { Div = lecture_list },
  { Link = new_tab },
  {
    Pandoc = function(doc)
      if quarto.doc.is_format("revealjs") then
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
        embed_videos()
      end
      if todo_count > 0 then
        quarto.log.warning("[course] " .. todo_count .. " todo block(s) in " .. quarto.doc.input_file)
      end
      doc.blocks:extend(credits_slide())
      return doc
    end,
  },
}
