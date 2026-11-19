# Contributing

Providers under `providers/` normalize vendor data into `lib/model.luau`.
Only `service.luau` fetches; the bar and panel consume its report.

Ordinary providers implement `fetch(ctx, done)`. A provider whose accounts are
managed externally implements `fetchAccounts(ctx, done)` instead, returning rows
with stable `id`, `label`, `active`, `snapshot` and/or `error`. The service schedules
one batch, reconciles accounts by identity, and maintains separate snapshots and
notifications. Such providers must not declare folder-based `accounts`.

Codex uses codex-auth's JSON interface. OpenCode Go's Python helper keeps SQLite
credentials out of Luau and returns only normalized usage. Do not add browser
cookie extraction or a second token refresher. Never log raw process output or
upstream response bodies.

Register new providers in `providers/registry.luau`, declare optional executables
in `plugin.toml`, add provider visibility settings/translations, and test both the
success and failure behavior. See README for commands and runtime requirements.
