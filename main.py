import asyncio
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import decky

UNIT = "tbot-watch.service"

# Default UID is 1000 (the `deck` user). If your install runs the user manager
# under a different UID, edit `_systemd_env` below to point at /run/user/<uid>.
DEFAULT_UID = 1000

# Default Timberbot mod endpoint when no config.toml [client] section exists.
# Source: timberbot/python/src/timberbot/settings.py.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8085

CONFIG_PATH = Path.home() / ".config" / "timberbot" / "config.toml"

HTTP_TIMEOUT_SEC = 1.5


# Only forward variables systemctl/journalctl actually need. Notably keeps
# TBOT_AUTH_TOKEN and other unrelated session vars out of the child env.
_SYSTEMD_KEEP = frozenset({"PATH", "HOME", "USER", "LANG", "LC_ALL", "TERM"})


def _systemd_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k in _SYSTEMD_KEEP}
    env["XDG_RUNTIME_DIR"] = f"/run/user/{DEFAULT_UID}"
    env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path=/run/user/{DEFAULT_UID}/bus"
    return env


SYSTEMD_ENV = _systemd_env()


async def _run(*args: str) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        env=SYSTEMD_ENV,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode or 0, stdout.decode().strip(), stderr.decode().strip()


async def _systemctl(*args: str) -> tuple[int, str, str]:
    return await _run("systemctl", "--user", *args)


def _parse_client_section(text: str) -> dict[str, Any]:
    try:
        import tomllib  # Python 3.11+

        data = tomllib.loads(text)
        section = data.get("client")
        return section if isinstance(section, dict) else {}
    except ModuleNotFoundError:
        pass

    # Fallback: scan [client] until the next [section] header. Good enough for
    # the flat key=value shape Timberbot writes. We support strings, ints, and
    # booleans, which covers host/port/auth_token/default_format.
    out: dict[str, Any] = {}
    in_section = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_section = line[1:-1].strip() == "client"
            continue
        if not in_section or "=" not in line:
            continue
        k, v = line.split("=", 1)
        key = k.strip()
        val_raw = v.strip()
        if val_raw.startswith('"') and val_raw.endswith('"'):
            out[key] = val_raw[1:-1]
        elif val_raw.startswith("'") and val_raw.endswith("'"):
            out[key] = val_raw[1:-1]
        elif val_raw in ("true", "false"):
            out[key] = val_raw == "true"
        elif re.fullmatch(r"-?\d+", val_raw):
            out[key] = int(val_raw)
        else:
            out[key] = val_raw
    return out


def _resolve_endpoint() -> dict[str, Any]:
    file_cfg: dict[str, Any] = {}
    try:
        file_cfg = _parse_client_section(CONFIG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        pass
    except OSError as e:
        decky.logger.warning(f"could not read {CONFIG_PATH}: {e}")

    host = os.environ.get("TBOT_HOST") or file_cfg.get("host") or DEFAULT_HOST
    port_raw = os.environ.get("TBOT_PORT") or file_cfg.get("port") or DEFAULT_PORT
    try:
        port = int(port_raw)
    except (TypeError, ValueError):
        port = DEFAULT_PORT
    token = os.environ.get("TBOT_AUTH_TOKEN") or file_cfg.get("auth_token") or None
    return {"host": str(host), "port": port, "auth_token": token}


def _http_get(url: str, token: str | None) -> tuple[int, dict[str, Any] | None, str | None]:
    req = urllib.request.Request(url, method="GET")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(body), None
            except json.JSONDecodeError:
                return resp.status, None, "invalid-json"
    except urllib.error.HTTPError as e:
        return e.code, None, f"http {e.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return 0, None, str(e)


class Plugin:
    async def get_unit_status(self) -> dict:
        rc, out, _ = await _systemctl(
            "show", UNIT,
            "--property=LoadState,ActiveState,SubState,Result,UnitFileState",
            "--no-pager",
        )
        props: dict[str, str] = {}
        for line in out.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                props[k] = v
        return {
            "unit": UNIT,
            "load_state": props.get("LoadState", "unknown"),
            "active_state": props.get("ActiveState", "unknown"),
            "sub_state": props.get("SubState", ""),
            "result": props.get("Result", ""),
            "unit_file_state": props.get("UnitFileState", ""),
            "ok": rc == 0,
        }

    async def start_unit(self) -> dict:
        rc, _, err = await _systemctl("start", UNIT)
        return {"ok": rc == 0, "error": err}

    async def stop_unit(self) -> dict:
        rc, _, err = await _systemctl("stop", UNIT)
        return {"ok": rc == 0, "error": err}

    async def restart_unit(self) -> dict:
        rc, _, err = await _systemctl("restart", UNIT)
        return {"ok": rc == 0, "error": err}

    async def get_unit_logs(self, n: int = 20) -> dict:
        n = max(1, min(int(n), 200))
        rc, out, err = await _run(
            "journalctl", "--user", "-u", UNIT,
            "-n", str(n), "--no-pager", "--output=short-iso",
        )
        lines = [l for l in out.splitlines() if l.strip()]
        return {"ok": rc == 0, "lines": lines, "error": err}

    async def get_mod_status(self) -> dict:
        endpoint = _resolve_endpoint()
        host = endpoint["host"]
        port = endpoint["port"]
        token = endpoint["auth_token"]
        base = f"http://{host}:{port}"

        ping_status, ping_body, ping_err = await asyncio.to_thread(
            _http_get, f"{base}/api/ping", None
        )
        ping_ok = ping_status == 200 and isinstance(ping_body, dict)

        agent_state: dict[str, Any] | None = None
        agent_auth_failed = False
        agent_error: str | None = None
        if ping_ok:
            state_status, state_body, state_err = await asyncio.to_thread(
                _http_get, f"{base}/api/agent/state", token
            )
            if state_status == 200 and isinstance(state_body, dict):
                agent_state = state_body
            elif state_status == 401:
                agent_auth_failed = True
            else:
                agent_error = state_err or f"http {state_status}"

        return {
            "ok": ping_ok,
            "endpoint": f"{host}:{port}",
            "ping": ping_body if ping_ok else None,
            "ping_error": None if ping_ok else (ping_err or f"http {ping_status}"),
            "agent_state": agent_state,
            "agent_auth_failed": agent_auth_failed,
            "agent_error": agent_error,
            "has_auth_token": bool(token),
        }

    async def _main(self):
        decky.logger.info(f"decky-tbot plugin loaded; controlling {UNIT}")

    async def _unload(self):
        decky.logger.info("decky-tbot plugin unloading")

    async def _uninstall(self):
        decky.logger.info("decky-tbot plugin uninstalling")
