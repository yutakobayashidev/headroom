--!nonstrict
-- The helper reads OpenCode 2's SQLite OAuth session and requests Go meters.
-- Only normalized usage/error leaves the helper; no token enters Luau or state.
local provider = require("../../lib/provider.luau")
local model = require("../../lib/model.luau")
local E = model.ErrorCode
local function parse(data, ctx)
  if type(data) ~= "table" then return nil, model.err(E.Parse) end
  if data.error then
    for _, code in E do
      if code == data.error then return nil, model.err(code) end
    end
    return nil, model.err(E.Parse)
  end
  if type(data.windows) ~= "table" or #data.windows ~= 3 then return nil, model.err(E.Parse) end
  local windows = {}
  for _, raw in data.windows do
    if type(raw) ~= "table" or type(raw.usedPercent) ~= "number" or type(raw.resetsAt) ~= "number" then
      return nil, model.err(E.Parse)
    end
    table.insert(windows, model.window({ id = raw.id, kind = if raw.kind == "monthly" then "other" else raw.kind,
      label = ctx.tr(if raw.kind == "monthly" then "providers.opencode-go.monthly" else `window.{raw.kind}`),
      usedPercent = raw.usedPercent, resetsAt = raw.resetsAt, periodSeconds = raw.periodSeconds }))
  end
  return model.snapshot({ plan = "Go", windows = windows, fetchedAt = ctx.now() }), nil
end
return provider.define({
  id = "opencode-go", name = "OpenCode Go",
  brand = { glyph = "terminal-2", dashboard = "https://opencode.ai/console" },
  isConfigured = function(ctx) return ctx.which("python3") end,
  signInHint = function(ctx) return ctx.tr("providers.opencode-go.hint") end,
  fetch = function(ctx, done)
    local script = ctx.readFile("providers/opencode-go/fetch.py")
    if script == nil then done(nil, model.err(E.Parse, "Go helper missing")); return end
    ctx.run({ "python3", "-c", script }, 30000, function(result)
      if result == nil or result.exitCode ~= 0 then done(nil, model.err(E.Network)); return end
      done(parse(ctx.decodeJson(result.stdout), ctx))
    end)
  end,
  parse = parse,
})
