--[[
Pandoc custom writer: the quiz slides of a deck as a Particify question series (CSV in the format of
Particify's export, as UTF-8 text; prerender.ts writes it as UTF-16).

  pandoc lectures/05-loops.qmd -f markdown -t tools/particify.lua

A quiz slide is a level-2 slide with {{< qr var:quiz >}}; one slide is one question:

  ## Your turn + text                       TEXT, body = first paragraph
  ## Your turn + text + bullet list         CHOICE (poll), options = list
  ## Title + ::: question                   TEXT, body = title
  ## Title + ::: question with bullet list  CHOICE, options = list outside ::: answer

  - [`2`]{.correct}                         correct option (two or more: multiple choice)
  ## Your turn {particify=wordcloud}        also: scale (agreement, 5 steps), rank (options = list)

Read as plain Markdown (no Quarto): shortcodes stay text, so the QR code is found as "{{< qr var:quiz".
COURSE_LENIENT=1: errors become warnings.
]]

local lenient = os.getenv("COURSE_LENIENT") == "1"
local input = "deck"

local function fail(msg)
  msg = "[particify] " .. input .. ": " .. msg
  if lenient then io.stderr:write("WARNING " .. msg .. "\n") else error(msg, 0) end
end

local KINDS = { wordcloud = true, scale = true, rank = true }

local function has_class(el, class)
  return el.classes and el.classes:includes(class)
end

local function is_quiz(blocks)
  return pandoc.utils.stringify(blocks):find("{{<%s*qr%s+var:quiz") ~= nil
end

local function count_correct(node)
  local n = 0
  pandoc.Blocks(node):walk({ Span = function(s) if has_class(s, "correct") then n = n + 1 end end })
  return n
end

-- First bullet list among the blocks, not inside ::: answer (also inside columns)
local function find_list(blocks)
  for _, b in ipairs(blocks) do
    if b.t == "BulletList" then return b end
    if b.t == "Div" and not has_class(b, "answer") then
      local l = find_list(b.content)
      if l then return l end
    end
  end
  return nil
end

local function options_of(list)
  local options, correct = {}, {}
  for _, item in ipairs(list.content) do
    local text = pandoc.utils.stringify(item)
    table.insert(options, text)
    if count_correct(item) > 0 then table.insert(correct, text) end
  end
  return options, correct
end

local function question_of(header, blocks)
  local kind = header.attributes["particify"]
  if kind and not KINDS[kind] then fail("unknown particify=" .. kind .. " on '" .. pandoc.utils.stringify(header) .. "'") end
  local qdiv
  for _, b in ipairs(blocks) do
    if b.t == "Div" and has_class(b, "question") then qdiv = b; break end
  end
  local body, list
  if qdiv then
    body = pandoc.utils.stringify(header)
    list = find_list(qdiv.content)
  else
    for _, b in ipairs(blocks) do
      if b.t == "Para" and not is_quiz({ b }) then body = pandoc.utils.stringify(b); break end
    end
    list = find_list(blocks)
  end
  if not body or body == "" then fail("quiz slide '" .. pandoc.utils.stringify(header) .. "' has no question text"); return nil end
  local q = { body = body, options = {}, correct = {}, listed_correct = 0 }
  if list then
    q.options, q.correct = options_of(list)
    q.listed_correct = #q.correct
  end
  if kind == "wordcloud" then
    q.format, q.options = "WORDCLOUD", { "5" }
  elseif kind == "scale" then
    q.format, q.options = "SCALE", { "AGREEMENT (5)" }
  elseif kind == "rank" then
    q.format = "PRIORITIZATION"
  elseif list then
    q.format = "CHOICE"
  else
    q.format = "TEXT"
  end
  return q
end

-- Quoting as in Particify's export: body always, other fields when they contain blanks or quotes
local function field(value, always)
  if value == "" then return "" end
  if always or value:find('[ \t\n"]') then return '"' .. value:gsub('"', '""') .. '"' end
  return value
end

local function row(q)
  return table.concat({
    q.format, field(q.body, true), "",
    field(table.concat(q.options, "\n")), field(table.concat(q.correct, "\n")),
    #q.correct > 1 and "true" or "false", "true", "0",
  }, "\t")
end

-- Level-2 slides: a heading of level 1 or 2 ends the previous slide
local function slides(doc)
  local result, current = {}, nil
  for _, b in ipairs(doc.blocks) do
    if b.t == "Header" and b.level <= 2 then
      current = (b.level == 2) and { header = b, blocks = pandoc.Blocks({}) } or nil
      if current then table.insert(result, current) end
    elseif current then
      current.blocks:insert(b)
    end
  end
  return result
end

function Writer(doc, opts)
  input = (PANDOC_STATE.input_files[1] or "deck"):gsub("\\", "/")
  local lines = { "format\tbody\tadditionalText\toptions\tcorrectOptions\tmultiple\tabstentionsAllowed\tduration" }
  local seen, listed = {}, 0
  for _, s in ipairs(slides(doc)) do
    if is_quiz(s.blocks) then
      local q = question_of(s.header, s.blocks)
      if q then
        if seen[q.body] then fail("two quiz slides ask '" .. q.body .. "': make the titles unique") end
        seen[q.body] = true
        listed = listed + q.listed_correct
        table.insert(lines, row(q))
      end
    end
  end
  if count_correct(doc.blocks) ~= listed then
    fail("a [...]{.correct} option is outside the option list of a quiz slide")
  end
  if #lines == 1 then return "" end
  return table.concat(lines, "\n") .. "\n"
end
