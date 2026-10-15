--[[
Shortcodes.

  {{< qr https://partici.fi/12345 >}}   QR code plus the link as text
  {{< qr var:quiz >}}                   same, URL taken from _variables.yml
  {{< qr var:quiz size=150 >}}          smaller QR code (pixels, default 220)

  {{< jshell while.jsh >}}              jshell listing and its transcript below
  {{< jshell while.jsh output=right >}} transcript next to the listing (split=50: listing width in %)
  {{< jshell while.jsh output=none >}}  listing only

  {{< error broken/ForScope.java >}}    the compiler message of a file in broken/
  {{< error broken/ForScope.java code=true >}}  the file and its compiler message

  {{< file HelloWeimar >}}              link that opens HelloWeimar.java in VS Code
  {{< file broken/Poster.java >}}       any file of the deck's code folder (code/... also works)
  {{< file fx/Stage label=Stage >}}     other link text
  {{< file code/01-introduction/ >}}    folder (trailing /): link to the repository on the web
]]

local lib = dofile(quarto.utils.resolve_path("lib.lua"))

local function read_variables()
  local text = lib.read_file("_variables.yml")
  if not text then return {} end
  return pandoc.read("---\n" .. text .. "\n---\n", "markdown").meta
end

local function lookup(meta, key)
  local v = meta
  for part in key:gmatch("[^%.]+") do
    if type(v) ~= "table" then return nil end
    v = v[part]
  end
  return v and pandoc.utils.stringify(v) or nil
end

local function kw(kwargs, name)
  local v = kwargs[name]
  if v == nil then return nil end
  v = pandoc.utils.stringify(v)
  return v ~= "" and v or nil
end

local function set_repo_url(meta)
  if meta and meta["repo-url"] then lib.repo_url = pandoc.utils.stringify(meta["repo-url"]):gsub("/$", "") end
end

return {
  qr = function(args, kwargs)
    local url = pandoc.utils.stringify(args[1] or "")
    if url:match("^var:") then
      local key = url:sub(5)
      url = lookup(read_variables(), key)
      if not url then error("[course] qr: variable '" .. key .. "' not found in _variables.yml") end
    end
    if not quarto.doc.is_format("html") then return pandoc.Link(url, url) end
    local esc = url:gsub("&", "&amp;"):gsub('"', "&quot;")
    local size = tonumber(kw(kwargs, "size") or "") or 220
    local label = esc:gsub("^https?://", "")
    return pandoc.RawInline("html",
      '<span class="qr-box"><span class="qr" data-url="' .. esc .. '" data-size="' .. size
      .. '" role="img" aria-label="QR code for ' .. esc .. '"></span>'
      .. '<a class="qr-link" href="' .. esc .. '">' .. label .. '</a></span>')
  end,

  jshell = function(args, kwargs, meta)
    set_repo_url(meta)
    local file = pandoc.utils.stringify(args[1] or "")
    local listing = lib.listing(file, { snippet = kw(kwargs, "snippet"), lines = kw(kwargs, "lines") })
    local mode = kw(kwargs, "output") or "below"
    return pandoc.Blocks(lib.with_output(listing, file, mode, tonumber(kw(kwargs, "split") or "") or 50))
  end,

  error = function(args, kwargs, meta)
    set_repo_url(meta)
    local file = pandoc.utils.stringify(args[1] or "")
    if kw(kwargs, "code") == "true" then
      return pandoc.Blocks(lib.with_output(lib.listing(file, {}), file, "below"))
    end
    return pandoc.Blocks({ lib.output(file) })
  end,

  file = function(args, kwargs, meta)
    set_repo_url(meta)
    local arg = pandoc.utils.stringify(args[1] or "")
    local label = kw(kwargs, "label") or arg
    local folder = arg:match("/$") ~= nil
    local path = arg
    if not folder and not pandoc.path.filename(arg):match("%.") then path = arg .. ".java" end
    local inc = lib.resolve(path)
    local exists
    if folder then
      exists = pcall(pandoc.system.list_directory, pandoc.path.join({ lib.root, inc }))
    else
      exists = lib.read_file(inc) ~= nil
    end
    if not exists then lib.fail("file: " .. inc .. " not found") end
    if not quarto.doc.is_format("html") then return pandoc.Code(label) end
    local code = "<code>" .. lib.html_escape(label) .. "</code>"
    if folder then
      if not lib.repo_url then return pandoc.Code(label) end
      return pandoc.RawInline("html", string.format('<a class="code-link" href="%s/tree/main/%s">%s</a>',
        lib.html_escape(lib.repo_url), lib.html_escape(inc:gsub("/$", "")), code))
    end
    local href = lib.repo_url and (lib.html_escape(lib.repo_url) .. "/blob/main/" .. lib.html_escape(inc)) or "#"
    return pandoc.RawInline("html", string.format(
      '<a class="vscode-open code-link" href="%s" data-file="%s" data-line="1" title="Open in VS Code">%s</a>',
      href, lib.html_escape(inc), code))
  end,
}
