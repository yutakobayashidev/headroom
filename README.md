# Headroom

A Noctalia usage widget with **codex-auth accounts** and **OpenCode Go sessions**.
Fork of [ayagmar/headroom](https://github.com/ayagmar/headroom), rebased by copying
Headroom 0.3.0 from [community-plugins](https://github.com/noctalia-dev/community-plugins/tree/b9aefd48419862beb576ac9dbb6ff065c5d37c60/headroom).
Upstream's MIT license and attribution are preserved.

## Codex

Install `codex-auth` (JSON schema 1; tested with 0.4.0) and register accounts there.
Headroom runs `codex-auth list --api --json` **once per refresh for all accounts**.
Each account has independent meters, reset times, forecasts and reset credits.
The bar's default account follows codex-auth's selection; choose `bar_accounts = all`
in the widget settings to show multiple accounts. The panel always lists all accounts.
Stable account keys keep cached usage attached to the right account when selection
or account ordering changes. A failed refresh is shown as an error with any last
successful snapshot; cached codex-auth values are never labelled as a fresh fetch.

There is no **Add Codex account**, login, rename, remove, or directory-launch UI.
Headroom does not scan `CODEX_HOME` directories. Manage sign-ins and aliases in
codex-auth. Its JSON output contains usage and account labels, not tokens.

## OpenCode Go

Install Python 3 and sign in through OpenCode 2:

```sh
opencode auth login opencode
```

Headroom reads the active `opencode` OAuth credential in
`${XDG_DATA_HOME:-~/.local/share}/opencode/opencode.db` (or `OPENCODE_DB`).
It requests `GET https://opencode.ai/console/api/go/status` with the access token
and the session's workspace ID, and displays five-hour, weekly and monthly meters.
This follows the Console-session approach used by
[opencode-quota](https://github.com/slkiser/opencode-quota/blob/main/src/lib/opencode-go.ts).
The monthly window has no assumed fixed duration, so no misleading monthly forecast.

The database is opened read-only, including live WAL state. Credentials stay inside
a short-lived Python helper; only normalized usage or a fixed error code returns to
Noctalia. Tokens are never copied, cached, logged or passed in process arguments.
Requests do not follow redirects and are restricted to the official Console.
Headroom does not use browser cookies, legacy Go API keys or Zen balances.

No session shows a sign-in hint. Expired sessions ask for renewal in OpenCode:
**OpenCode owns token refresh**. Headroom does not rotate its refresh token.
HTTP 401/403 is an authentication/access error, not a claim that the subscription
is absent. HTTP 404 or a missing Console `access` is shown as no plan.
Live OAuth success has not been verified on the development machine, which has no
active OpenCode 2 login. Parsing and authentication behavior are fixture-tested.

## Other providers and display

Claude and Antigravity retain upstream's adapters. Claude can still manage its
folder-based accounts. Provider visibility, bar windows/style, remaining/used
percentages, forecasts, notifications and reset-credit reminders work as upstream.
The plugin and its subprocesses respect Noctalia's offline mode.

## Install

The fork uses `yutakobayashidev/headroom`, distinct from the community plugin.
With this checkout in a stable location:

```sh
mkdir -p ~/.local/share/noctalia/plugins
ln -s /path/to/headroom ~/.local/share/noctalia/plugins/headroom-fork
noctalia msg plugins disable ayagmar/headroom
noctalia msg plugins enable yutakobayashidev/headroom
```

Replace the bar widget ID with `yutakobayashidev/headroom:usage` in Noctalia settings.
The plugin requires API 43. Its dependencies must be on Noctalia's PATH:
`codex-auth` for Codex, `python3` for Go, plus the optional upstream helpers
`xdg-open`, `secret-tool`, `claude`, `agy`, `env`, and `rm`.

Refresh with:

```sh
noctalia msg plugin yutakobayashidev/headroom:poller all refresh
```

## Files and processes

- `codex-auth list --api --json` owns Codex API access and its existing usage cache.
- `python3 -c <bundled helper>` reads OpenCode's DB and requests Console Go status.
- Claude reads its `.credentials.json` and can invoke its CLI to renew/login.
- Antigravity reads its existing keyring/token file and can invoke `agy` to renew.
- `xdg-open` opens a vendor dashboard. `env` and `rm` are only for Claude's existing
  directory-based account management.
- Headroom writes usage caches and Claude account metadata under
  `~/.local/state/noctalia/plugins/data/yutakobayashidev/headroom/`. No credentials.

## Development

```sh
LUAU=/path/to/luau bash tests/run.sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py'
noctalia plugins lint .
```

The Luau tests cover the service, account reconciliation and UI data contract;
Python tests use synthetic SQLite credentials and mocked Console responses.
