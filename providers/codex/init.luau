--!nonstrict
-- codex-auth owns account discovery, credentials and API refresh.
-- One invocation retrieves all accounts. No CODEX_HOME directories or login UI.
local provider = require("../../lib/provider.luau")
local model = require("../../lib/model.luau")
local time = require("../../lib/time.luau")
local E = model.ErrorCode

local function usageError(usage)
  local refresh = type(usage) == "table" and usage.refresh
  if type(refresh) ~= "table" or refresh.status ~= "ok" or usage.source ~= "api" then
    local status = type(refresh) == "table" and refresh.http_status
    return model.err(if status == 401 or status == 403 then E.Auth
      elseif status == 429 then E.RateLimited else E.Network, "codex-auth usage refresh failed")
  end
  return nil
end

local function parseAccount(account, ctx)
  local usage = account.usage
  local err = usageError(usage)
  if err then return nil, err end
  local windows = {}
  for _, slot in { "primary", "secondary" } do
    local raw = usage[slot]
    if type(raw) == "table" then
      local percent = tonumber(raw.used_percent)
      local minutes = tonumber(raw.window_minutes)
      if percent == nil or percent ~= percent or math.abs(percent) == math.huge then
        return nil, model.err(E.Parse, "invalid usage percentage")
      end
      local seconds = if minutes and minutes > 0 then minutes * 60 else nil
      local kind = if seconds and seconds <= 43200 then "session"
        elseif seconds and seconds >= 518400 and seconds <= 691200 then "weekly" else "other"
      table.insert(windows, model.window({ id = slot, kind = kind,
        label = if kind == "other" and seconds then ctx.duration(seconds) else ctx.tr(`window.{kind}`),
        usedPercent = percent, resetsAt = time.toUnix(raw.resets_at), periodSeconds = seconds }))
    end
  end
  if #windows == 0 then return nil, model.err(E.Parse, "no usage windows") end
  local credits = {}
  if type(usage.reset_credit) == "table" then
    for _, credit in usage.reset_credit do
      if type(credit) == "table" and credit.status == "available" then
        table.insert(credits, { count = 1, label = credit.title, expiresAt = time.toUnix(credit.expires_at) })
      end
    end
  end
  if #credits == 0 and type(usage.reset_credits) == "number" and usage.reset_credits > 0 then
    table.insert(credits, { count = usage.reset_credits })
  end
  return model.snapshot({ plan = if type(account.plan) == "string" then account.plan else nil,
    windows = windows, resetCredits = credits, fetchedAt = ctx.now() }), nil
end

local function parse(data, ctx)
  if type(data) ~= "table" or data.schema_version ~= 1 or type(data.accounts) ~= "table" then
    return nil, model.err(E.Parse, "unsupported codex-auth JSON")
  end
  local rows, seen = {}, {}
  for _, account in data.accounts do
    if type(account) ~= "table" or type(account.account_key) ~= "string" or account.account_key == "" then
      return nil, model.err(E.Parse, "invalid codex-auth account")
    end
    local key = account.account_key
    if seen[key] then return nil, model.err(E.Parse, "duplicate codex-auth account") end
    seen[key] = true
    local snapshot, err = parseAccount(account, ctx)
    local label = account.alias or account.account_name or account.email
    table.insert(rows, { id = key, label = if type(label) == "string" and label ~= "" then label else `Account {#rows + 1}`,
      active = account.active == true or data.active_account_key == key,
      snapshot = snapshot, error = err })
  end
  -- The bar's default view follows codex-auth's selected account. Keys remain
  -- stable when that selection or the CLI's account numbers change.
  table.sort(rows, function(a, b)
    if a.active ~= b.active then return a.active end
    return a.id < b.id
  end)
  return rows, nil
end

return provider.define({
  id = "codex", name = "Codex",
  brand = { glyph = "brand-openai",
    dashboard = "https://chatgpt.com/settings/usage?tab=overview" },
  isConfigured = function(ctx) return ctx.which("codex-auth") end,
  signInHint = function(ctx) return ctx.tr("providers.codex.hint") end,
  fetchAccounts = function(ctx, done)
    ctx.run({ "codex-auth", "list", "--api", "--json" }, 90000, function(result)
      if result == nil or result.exitCode ~= 0 then
        done(nil, model.err(E.Network, "codex-auth command failed"))
        return
      end
      done(parse(ctx.decodeJson(result.stdout), ctx))
    end)
  end,
  parse = parse,
})
