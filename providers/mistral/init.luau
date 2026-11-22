--!nonstrict
-- The short-lived Python helper keeps Vibe credentials out of Luau and caches.
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
  local used = data.usedPercent
  if type(used) ~= "number" or used ~= used or used < 0 or used == math.huge
    or (data.resetsAt ~= nil and type(data.resetsAt) ~= "number") then
    return nil, model.err(E.Parse)
  end
  return model.snapshot({ windows = { model.window({
    id = "monthly", kind = "other", label = ctx.tr("providers.mistral.monthly"),
    usedPercent = used, resetsAt = data.resetsAt,
  }) }, fetchedAt = ctx.now() }), nil
end
return provider.define({
  id = "mistral", name = "Mistral Vibe",
  brand = { glyph = "terminal-2", dashboard = "https://admin.mistral.ai" },
  isConfigured = function(ctx) return ctx.which("python3") end,
  signInHint = function(ctx) return ctx.tr("providers.mistral.hint") end,
  fetch = function(ctx, done)
    local script = ctx.readFile("providers/mistral/fetch.py")
    if script == nil then done(nil, model.err(E.Parse, "Mistral helper missing")); return end
    ctx.run({ "python3", "-c", script }, 30000, function(result)
      if result == nil or result.exitCode ~= 0 then done(nil, model.err(E.Network)); return end
      done(parse(ctx.decodeJson(result.stdout), ctx))
    end)
  end,
  parse = parse,
})
