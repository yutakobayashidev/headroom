--!nonstrict
-- Adapters against recorded vendor responses: the endpoints are undocumented
-- and change shape without notice.

local t = require("./support/t")
local env = require("./support/env")

local function ids(windows)
  local out = {}
  for _, w in windows do
    out[w.id] = w
  end
  return out
end

t.group("claude", function()
  t.test("usage, plan from the token's profile, and the reset grants", function()
    local host, p, ctx = env.provider("claude")
    env.claudeCreds(host, "tok")
    env.serveClaude(host, { tok = "a" })
    local snapshot, err = env.fetch(p, ctx)
    t.eq(err, nil)
    local w = ids(snapshot.windows)
    t.eq(w.session.usedPercent, 38)
    t.eq(w.weekly.periodSeconds, 7 * 86400)
    t.eq(w["weekly_scoped:Fable"].label, "Weekly · Fable")
    t.eq(snapshot.plan, "Ultra")
    -- Started, unpaused grants with resets left, soonest to expire first.
    t.eq(#snapshot.resetCredits, 2)
    t.eq(snapshot.resetCredits[1].label, "One full limit reset (September 2026)")
    t.eq(snapshot.resetCredits[1].expiresAt, 1790373600)
    t.ok(env.headerOf(host.requests[2], "User-Agent"):match("^claude%-cli/%d+%.%d+%.%d+ %(external, cli%)$"), "Claude Code user agent")
  end)

  t.test("identity comes from the token, asked once per token", function()
    local host, p, ctx = env.provider("claude")
    env.serveClaude(host, { one = "a", two = "b" })
    env.claudeCreds(host, "one")
    t.eq(p.accounts.identity(ctx), nil, "unknown before a fetch")
    env.fetch(p, ctx)
    env.fetch(p, ctx)
    t.eq(env.requestsTo(host, "/oauth/profile"), 1)
    t.eq(p.accounts.identity(ctx).id, "acct-a/org-a")
    -- `/login` as someone else: a new token, so whose it is must be asked again.
    env.claudeCreds(host, "two")
    t.eq(p.accounts.identity(ctx), nil)
    env.fetch(p, ctx)
    t.eq(p.accounts.identity(ctx).id, "acct-b/org-a")
  end)

  t.test("the grants come at most hourly, and a failed profile is asked again", function()
    local host, p, ctx = env.provider("claude")
    env.claudeCreds(host, "tok")
    local profileUp = false
    local serve = host.httpHandler
    env.serveClaude(host, { tok = "a" })
    serve = host.httpHandler
    host.httpHandler = function(req)
      if req.url:find("/oauth/profile", 1, true) and not profileUp then
        return { ok = false }
      end
      return serve(req)
    end
    local first = env.fetch(p, ctx)
    t.eq(first.plan, nil, "no profile, no plan")
    profileUp = true
    host.clock += 600
    local second = env.fetch(p, ctx)
    t.eq(second.plan, "Ultra", "profile asked again")
    t.eq(env.requestsTo(host, "cedar_ember=1"), 1, "grants not re-read within the hour")
    t.eq(#second.resetCredits, 2, "the last grants still shown")
  end)
end)

t.group("codex-auth", function()
  t.test("stable accounts, active first, windows and reset credits", function()
    local host, p, ctx = env.provider("codex")
    local rows, err = p.parse(env.decode(host, env.fixture("codex_auth.json")), ctx)
    t.eq(err, nil)
    t.eq(#rows, 2)
    t.eq(rows[1].id, "work")
    t.eq(rows[1].active, true)
    t.eq(rows[1].snapshot.windows[1].usedPercent, 40)
    t.eq(rows[1].snapshot.windows[2].periodSeconds, 604800)
    t.eq(rows[1].snapshot.resetCredits[1].expiresAt, 1790100000)
    t.eq(p.accounts, nil, "no directory account management")
  end)
  t.test("failed refresh is not mistaken for fresh cached usage", function()
    local host, p, ctx = env.provider("codex")
    local data = env.decode(host, env.fixture("codex_auth.json"))
    data.accounts[2].usage.source = "cache"
    data.accounts[2].usage.refresh = { status = "http_error", http_status = 401 }
    local rows = p.parse(data, ctx)
    t.eq(rows[1].snapshot, nil)
    t.eq(rows[1].error.code, "auth")
    t.ok(rows[2].snapshot ~= nil, "other account still works")
  end)
  t.test("malformed data and duplicate identities fail closed", function()
    local host, p, ctx = env.provider("codex")
    for _, data in { {}, { schema_version = 2, accounts = {} } } do
      local rows, err = p.parse(data, ctx)
      t.eq(rows, nil)
      t.eq(err.code, "parse")
    end
    local data = env.decode(host, env.fixture("codex_auth.json"))
    data.accounts[2].account_key = data.accounts[1].account_key
    local rows, err = p.parse(data, ctx)
    t.eq(rows, nil)
    t.eq(err.code, "parse")
  end)
end)

t.group("OpenCode Go", function()
  t.test("maps Console windows and preserves auth errors", function()
    local host, p, ctx = env.provider("opencode-go")
    local snapshot, err = p.parse({ windows = {
      { id = "fiveHour", kind = "session", usedPercent = 1, resetsAt = host.clock + 100, periodSeconds = 18000 },
      { id = "week", kind = "weekly", usedPercent = 25, resetsAt = host.clock + 1000, periodSeconds = 604800 },
      { id = "month", kind = "monthly", usedPercent = 50, resetsAt = host.clock + 10000 },
    } }, ctx)
    t.eq(err, nil)
    t.eq(snapshot.windows[1].usedPercent, 1)
    t.eq(snapshot.windows[3].kind, "other")
    t.eq(snapshot.windows[3].periodSeconds, nil, "calendar month has no assumed fixed period")
    local none, expired = p.parse({ error = "expired" }, ctx)
    t.eq(none, nil)
    t.eq(expired.code, "expired")
    local _, malformed = p.parse({ windows = {} }, ctx)
    t.eq(malformed.code, "parse")
  end)
end)

t.group("antigravity", function()
  t.test("parses the quota summary", function()
    local host, p, ctx = env.provider("antigravity")
    local snapshot, err = p.parse(env.decode(host, env.fixture("antigravity_quota.json")), ctx)
    t.eq(err, nil)
    t.ok(#snapshot.windows > 0, "windows")
  end)
end)

return nil
