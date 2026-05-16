# decky-tbot

A [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) plugin for
the Steam Deck that controls the `tbot-watch.service` systemd **user** unit —
the long-running [Timberbot](https://github.com/impuls42/timberbot) agent
connector — from Game Mode, and surfaces the connector ↔ mod link in the QAM.

Sibling project of, and structurally a near-clone of,
[decky-opencode](https://github.com/impuls42/decky-opencode).

![logo](./assets/logo.png)

## What it does

Two status rows + three buttons in the QAM:

```
┌──────────────────────────────────────┐
│ Timberbot connector                  │
│ ● tbot-watch.service · active        │
│ ● mod · 127.0.0.1:8085 · Ready · Idle│
│                                      │
│ [ Start ]  [ Stop ]  [ Restart ]     │
│                                      │
│ [ Show logs (last 20) ]              │
└──────────────────────────────────────┘
```

- **Unit row** — `systemctl --user show tbot-watch.service ...` for live
  status. Green = active, red = inactive/failed, yellow = transitional,
  grey = unknown.
- **Mod row** — `GET http://<host>:<port>/api/ping` against the Timberbot
  mod plus `GET /api/agent/state` (both are gate-exempt, so they answer
  even before the player presses Launch). The pill walks through
  `Disconnected → Connected · Not Ready → Connected · Ready · Idle →
  Connected · Ready · Running` as the player presses Launch in-game and
  the connector dispatches a request. On a bearer-auth mismatch the pill
  greys out to `Connected · auth required` — the plugin never errors
  loudly on auth. When the connector reports `agentStatus` or `lastError`,
  those surface as small sub-lines under the mod row.
- The `tbot watch` connector itself talks to the mod over a WebSocket
  (`/api/ws` on port 8086 by default); the plugin stays HTTP-only and
  only observes the connector via systemd + the HTTP endpoints above.
- **Start / Stop / Restart** — wraps the corresponding `systemctl --user`
  verbs.
- **Logs** — collapsible view of the last 20 `journalctl --user -u
  tbot-watch.service` lines, refetched on each poll while open.

Status is polled every 2 seconds while the panel is mounted.

## Install

### 1. Install the Timberbot CLI

```bash
pipx install timberbot
```

On a Deck, `pipx` drops binaries in `~/.local/bin`, which is not always on
the user-systemd `PATH`. The sample unit below dodges this by using the
absolute path `/home/deck/.local/bin/tbot`.

### 2. Drop in the systemd user unit

The plugin **does not** install the unit file itself — it only drives an
existing unit. Create `~/.config/systemd/user/tbot-watch.service`:

```ini
# ~/.config/systemd/user/tbot-watch.service
[Unit]
Description=Timberbot agent connector
Documentation=https://github.com/impuls42/timberbot

[Service]
# `tbot watch` reads host/port/auth_token from ~/.config/timberbot/config.toml
# or TBOT_* env vars. See `tbot watch --help` for the current flag set
# (--ws-port, --backend, --model, --autonomous-interval, etc.).
ExecStart=/home/deck/.local/bin/tbot watch
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
```

Then reload:

```bash
systemctl --user daemon-reload
```

### 3. Install the plugin

1. Enable developer mode in Decky Loader.
2. Grab `decky-tbot-vX.Y.Z.zip` from the
   [Releases page](https://github.com/impuls42/decky-tbot/releases) (or
   build it yourself — see below).
3. Unzip into `~/homebrew/plugins/` on the Deck so you end up with
   `~/homebrew/plugins/decky-tbot/` containing `dist/index.js`, `main.py`,
   `plugin.json`, etc.
4. Restart Decky Loader from the Quick Access Menu.

The plugin appears in the QAM with the tree icon and the title
**Timberbot Connector**.

## Configuration

The plugin reads the same `[client]` section the connector itself uses:

```toml
# ~/.config/timberbot/config.toml
[client]
host = "127.0.0.1"     # default
port = 8085            # default
auth_token = "..."     # required if the mod enforces bearer auth
```

Environment variables override the file: `TBOT_HOST`, `TBOT_PORT`,
`TBOT_AUTH_TOKEN`. If neither the file nor env are set, the plugin falls
back to `127.0.0.1:8085` with no auth — the same defaults the mod ships
with.

### UID hardcode

`main.py` pins `XDG_RUNTIME_DIR=/run/user/1000` and the matching DBUS
session bus so the Decky process can reach the user manager. UID `1000` is
the default `deck` user. If your install runs under a different UID, edit
`DEFAULT_UID` (or the `_systemd_env` helper) in `main.py`.

## Development

Requires Node.js v16.14+ and `pnpm` v9.

```bash
pnpm install
pnpm run build      # one-shot build into dist/
pnpm run watch      # rebuild on change
```

### Layout

```
.
├── main.py            # Decky Python backend — wraps systemctl --user, journalctl, /api/ping, /api/agent/state
├── src/index.tsx      # QAM panel (unit row + mod row + buttons + logs)
├── plugin.json        # Decky plugin manifest
├── package.json       # Frontend build config
├── rollup.config.js   # @decky/rollup wrapper
└── assets/logo.png    # Plugin logo
```

### Frontend ↔ backend

| Frontend            | Backend (`main.py`)         | Since |
|---------------------|-----------------------------|-------|
| `getUnitStatus()`   | `Plugin.get_unit_status`    | v0    |
| `startUnit()`       | `Plugin.start_unit`         | v0    |
| `stopUnit()`        | `Plugin.stop_unit`          | v0    |
| `restartUnit()`     | `Plugin.restart_unit`       | v0    |
| `getModStatus()`    | `Plugin.get_mod_status`     | v1    |
| `getUnitLogs(n)`    | `Plugin.get_unit_logs`      | v1    |

## Known limitations

- **Polling cadence is fixed at 2 s** while the panel is mounted. The
  Decky QAM does not expose a "panel collapsed but plugin still mounted"
  signal we trust, so the spec's "throttle to 10 s when collapsed" is not
  implemented.
- **Single instance only.** One Deck → one `tbot watch` → one
  `tbot-watch.service`. Multi-instance setups are out of scope.
- **Cross-host control is out of scope.** The plugin assumes the Deck is
  both the game host and the connector host.
- **No config editing from the QAM.** Tweak `~/.config/timberbot/config.toml`
  in Desktop Mode.

## License

[BSD-3-Clause](./LICENSE).
