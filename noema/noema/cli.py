"""
Noema CLI — Dead-simple daily commands.

One command workflow: noema start

Usage:
    noema start       Start everything (MT5, dashboard, trading)
    noema stop        Graceful shutdown
    noema status      Quick status check
    noema dashboard   Start dashboard only
    noema logs        Tail live logs
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

# ── Constants ─────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PID_DIR = Path("/tmp")
PID_TRADING = PID_DIR / "noema-trading.pid"
PID_DASHBOARD_API = PID_DIR / "noema-dashboard-api.pid"
PID_DASHBOARD_FRONTEND = PID_DIR / "noema-dashboard-frontend.pid"
PID_MT5 = PID_DIR / "noema-mt5.pid"
LOG_TRADING = PID_DIR / "noema-trading.log"
LOG_DASHBOARD_API = PID_DIR / "noema-dashboard-api.log"
LOG_DASHBOARD_FRONTEND = PID_DIR / "noema-dashboard-frontend.log"

VERSION = "0.1.0"


# ── Helpers ───────────────────────────────────────────────────────


def _icon(emoji: str, msg: str) -> str:
    """Format a line with emoji prefix."""
    return f"{emoji} {msg}"


def _print(emoji: str, msg: str) -> None:
    """Print a status line."""
    print(_icon(emoji, msg))


def _find_env() -> Optional[Path]:
    """Find .env file — check project root first, then cwd."""
    candidates = [
        PROJECT_ROOT / ".env",
        Path.cwd() / ".env",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _load_env() -> dict[str, str]:
    """Load minimal env vars from .env for CLI use (no pydantic needed)."""
    env_path = _find_env()
    if not env_path:
        return {}
    env = {}
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            env[key] = val
    return env


def _read_pid(pid_file: Path) -> Optional[int]:
    """Read a PID file. Returns None if file doesn't exist or PID is stale."""
    if not pid_file.exists():
        return None
    try:
        pid = int(pid_file.read_text().strip())
    except (ValueError, OSError):
        return None
    # Check if process is actually running
    try:
        os.kill(pid, 0)
        return pid
    except (ProcessLookupError, PermissionError):
        return None


def _write_pid(pid_file: Path, pid: int) -> None:
    """Write a PID file."""
    pid_file.write_text(str(pid))


def _clear_pid(pid_file: Path) -> None:
    """Remove a PID file if it exists."""
    pid_file.unlink(missing_ok=True)


def _is_running(pid_file: Path) -> bool:
    """Check if a process from PID file is alive."""
    return _read_pid(pid_file) is not None


def _stop_process(pid_file: Path, label: str, emoji: str = "🛑") -> bool:
    """Gracefully stop a process tracked by PID file.

    SIGTERM → wait 3s → SIGKILL.
    """
    pid = _read_pid(pid_file)
    if pid is None:
        _clear_pid(pid_file)
        return False

    print(f"{emoji} Stopping {label} (PID {pid})...", end=" ", flush=True)
    try:
        os.kill(pid, signal.SIGTERM)
        # Wait for graceful exit
        for _ in range(6):  # 3 seconds
            time.sleep(0.5)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                print("done")
                _clear_pid(pid_file)
                return True
        # Force kill
        os.kill(pid, signal.SIGKILL)
        time.sleep(0.5)
        print("killed")
    except ProcessLookupError:
        print("already stopped")
    except PermissionError:
        print("permission denied")
    _clear_pid(pid_file)
    return True


def _run_background(
    args: list[str],
    pid_file: Path,
    log_file: Path,
    cwd: Optional[Path] = None,
    env: Optional[dict[str, str]] = None,
) -> subprocess.Popen:
    """Launch a background process, capturing output to log file."""
    log_fh = open(log_file, "a")
    proc_env = os.environ.copy()
    if env:
        proc_env.update(env)
    proc = subprocess.Popen(
        args,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        cwd=cwd or PROJECT_ROOT,
        env=proc_env,
        start_new_session=True,
    )
    _write_pid(pid_file, proc.pid)
    return proc


def _wait_for_port(port: int, timeout: int = 30, label: str = "") -> bool:
    """Wait until a port is accepting connections."""
    import socket

    msg = f"⏳ Waiting for {label or f'port {port}'}..."
    print(msg, end=" ", flush=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            sock = socket.create_connection(("127.0.0.1", port), timeout=1.0)
            sock.close()
            print("ready")
            return True
        except (ConnectionRefusedError, OSError):
            time.sleep(0.3)
    print("timeout")
    return False


def _wait_for_url(url: str, timeout: int = 30, label: str = "") -> bool:
    """Wait until a URL responds with 2xx."""
    import urllib.request

    msg = f"⏳ Waiting for {label or url}..."
    print(msg, end=" ", flush=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = urllib.request.urlopen(url, timeout=1)
            if 200 <= resp.status < 400:
                print("ready")
                return True
        except Exception:
            time.sleep(0.3)
    print("timeout")
    return False


def _open_browser(url: str) -> None:
    """Open URL in the default browser.

    Tries multiple strategies:
    1. Python's webbrowser module
    2. Common browser commands (xdg-open, open, etc.)
    3. Snap/flatpak browsers
    4. If all fail, prints the URL prominently
    """
    # Strategy 1: Python webbrowser module
    try:
        import webbrowser
        if webbrowser.open(url):
            return
    except Exception:
        pass

    # Strategy 2: Try common browser commands
    browser_commands = [
        ["xdg-open", url],
        ["open", url],
        ["sensible-browser", url],
        ["google-chrome", url],
        ["google-chrome-stable", url],
        ["chromium-browser", url],
        ["chromium", url],
        ["firefox", url],
        ["firefox-esr", url],
        ["brave-browser", url],
        ["microsoft-edge", url],
        ["opera", url],
        ["vivaldi", url],
        # Snap paths
        ["/snap/bin/chromium", url],
        ["/snap/bin/firefox", url],
        ["/snap/bin/brave", url],
        ["/snap/bin/opera", url],
        # Flatpak
        ["/var/lib/flatpak/exports/bin/org.mozilla.firefox", url],
        ["/var/lib/flatpak/exports/bin/com.google.Chrome", url],
        ["/var/lib/flatpak/exports/bin/com.brave.Browser", url],
        # AppImage (check common locations)
        [str(Path.home() / "Applications" / "Firefox.AppImage"), url],
        [str(Path.home() / "Applications" / "Chrome.AppImage"), url],
    ]

    for cmd in browser_commands:
        browser_path = cmd[0]
        # For simple command names, check if they exist in PATH
        if "/" not in browser_path:
            if not _check_binary(browser_path):
                continue
        else:
            if not Path(browser_path).exists():
                continue
        try:
            subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
            return
        except Exception:
            continue

    # Strategy 3: python -m webbrowser as last resort
    try:
        subprocess.run(
            [sys.executable, "-m", "webbrowser", "-t", url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return
    except Exception:
        pass

    # Strategy 4: Display URL prominently — nothing worked
    _print_url_box(url)


def _check_binary(name: str) -> bool:
    """Check if a command is available."""
    try:
        subprocess.run(
            ["which", name], capture_output=True, text=True, timeout=3
        )
        return True
    except Exception:
        return False


def _print_url_box(url: str) -> None:
    """Print URL in a prominent box — fallback when no browser available."""
    url_line = f"  🌐  {url}  "
    width = max(len(url_line) + 2, 50)
    border = "═" * width
    print()
    print(f"  ╔{border}╗")
    print(f"  ║{'Open this URL in your browser:':^{width}}║")
    print(f"  ║{'':^{width}}║")
    print(f"  ║{url_line:^{width}}║")
    print(f"  ║{'':^{width}}║")
    print(f"  ║{'No browser detected — open manually ↑':^{width}}║")
    print(f"  ╚{border}╝")
    print()


def _find_npm_or_npx() -> Optional[str]:
    """Find npm/npx for running the dashboard frontend."""
    for tool in ["npx", "npm"]:
        if _check_binary(tool):
            return tool
    return None


# ── MT5 Helpers ───────────────────────────────────────────────────


def _should_start_mt5(env: dict[str, str]) -> bool:
    """Determine if MT5 should be auto-started."""
    headless = env.get("Noema_MT5_HEADLESS", "true").lower()
    return headless in ("true", "1", "yes")


def _start_mt5() -> bool:
    """Start MT5 headless via the daemon script."""
    print("🍷 Starting MT5 headless...", end=" ", flush=True)
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "noema.scripts.mt5_daemon", "start"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=PROJECT_ROOT,
            start_new_session=True,
        )
        _write_pid(PID_MT5, proc.pid)
        # Wait for the daemon's own startup
        proc.wait(timeout=120)
        if proc.returncode == 0:
            print("started")
            return True
        else:
            print(f"failed (exit code {proc.returncode})")
            return False
    except subprocess.TimeoutExpired:
        print("started (background)")
        return True
    except FileNotFoundError:
        print("failed — mt5_daemon not found")
        return False
    except Exception as exc:
        print(f"failed — {exc}")
        return False


def _stop_mt5() -> bool:
    """Stop MT5 via wineserver or daemon."""
    print("🍷 Stopping MT5...", end=" ", flush=True)

    # Try daemon stop first
    try:
        subprocess.run(
            [sys.executable, "-m", "noema.scripts.mt5_daemon", "stop"],
            capture_output=True,
            cwd=PROJECT_ROOT,
            timeout=15,
        )
    except Exception:
        pass

    # Fallback: wineserver -k
    for wineserver in ["wineserver", "wineserver64", "wineserver32"]:
        try:
            result = subprocess.run(
                [wineserver, "-k"],
                capture_output=True,
                timeout=10,
            )
            if result.returncode == 0:
                print("done")
                _clear_pid(PID_MT5)
                return True
        except Exception:
            continue

    # Fallback: kill tracked process
    pid = _read_pid(PID_MT5)
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            print("done")
        except Exception:
            print("done")
    else:
        print("done")
    _clear_pid(PID_MT5)
    return True


# ── Commands ──────────────────────────────────────────────────────


def cmd_start(args: argparse.Namespace) -> None:
    """Start everything: MT5, dashboard, trading."""
    print(f"🧠 Noema v{VERSION}")

    env = _load_env()

    # 1. Check .env
    env_path = _find_env()
    if not env_path:
        print("❌ No .env file found.")
        print("   Run ./noema-setup first to create your configuration.")
        sys.exit(1)
    _print("📋", "Loading .env...")

    # 2. Check if already running
    if _is_running(PID_TRADING):
        print("⚠️  Noema appears to be already running.")
        try:
            answer = input("   Restart? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        if answer not in ("y", "yes"):
            print("   Leaving current instance running.")
            return
        cmd_stop(args)

    # 3. Check for venv
    venv_python = PROJECT_ROOT / ".venv" / "bin" / "python"
    if venv_python.exists():
        _print("🐍", "Activating venv...")
        python_exe = str(venv_python)
    else:
        python_exe = sys.executable

    # 4. Start MT5 headless
    if _should_start_mt5(env):
        if not _start_mt5():
            print("⚠️  MT5 did not start — continuing without it")
        else:
            _wait_for_port(18812, timeout=int(env.get("Noema_MT5_STARTUP_WAIT", "120")), label="MT5 (port 18812)")

    # 5. Start dashboard API
    _print("📊", "Starting dashboard API...")
    dashboard_dir = PROJECT_ROOT / "dashboard"
    api_script = dashboard_dir / "server" / "api.py"
    if api_script.exists():
        _run_background(
            [python_exe, str(api_script)],
            PID_DASHBOARD_API,
            LOG_DASHBOARD_API,
            cwd=PROJECT_ROOT,
        )
        _wait_for_port(8000, label="API (port 8000)")
    else:
        print("   ⚠️ Dashboard API not found — skipping")

    # 6. Start dashboard frontend
    _print("📊", "Starting dashboard frontend...")
    npm_tool = _find_npm_or_npx()
    if npm_tool and (dashboard_dir / "package.json").exists():
        if npm_tool == "npx":
            frontend_cmd = ["npx", "vite", "--port", "3000", "--host"]
        else:
            frontend_cmd = ["npm", "run", "dev"]
        _run_background(
            frontend_cmd,
            PID_DASHBOARD_FRONTEND,
            LOG_DASHBOARD_FRONTEND,
            cwd=dashboard_dir,
        )
        _wait_for_url("http://localhost:3000", label="frontend (port 3000)")
    else:
        print("   ⚠️ npm not found — skipping dashboard frontend")

    # 7. Open browser (only if frontend is actually running)
    if _is_running(PID_DASHBOARD_FRONTEND):
        _open_browser("http://localhost:3000")
    else:
        _print_url_box("http://localhost:3000")

    # 8. Start trading engine
    _print("📈", "Starting trading engine...")
    _run_background(
        [python_exe, "-m", "noema.main", "--mt5-auto"],
        PID_TRADING,
        LOG_TRADING,
        cwd=PROJECT_ROOT,
    )

    time.sleep(1)
    if _is_running(PID_TRADING):
        _print("✅", "Trading engine started")
    else:
        print("⚠️  Trading engine may have failed to start — check logs: noema logs")

    # 9. Summary
    telegram_token = env.get("TELEGRAM_BOT_TOKEN", "")
    telegram_status = "active" if telegram_token else "not configured"
    print()
    print(f"✅ Noema running | Dashboard: http://localhost:3000 | Telegram: {telegram_status}")
    print()


def cmd_stop(args: argparse.Namespace) -> None:
    """Graceful shutdown: trading → dashboard → MT5."""
    print(f"🧠 Noema v{VERSION}")

    stopped_any = False

    # 1. Stop trading engine
    if _stop_process(PID_TRADING, "trading engine"):
        stopped_any = True

    # 2. Stop dashboard frontend
    if _stop_process(PID_DASHBOARD_FRONTEND, "dashboard frontend", emoji="🛑"):
        stopped_any = True

    # 3. Stop dashboard API
    if _stop_process(PID_DASHBOARD_API, "dashboard API", emoji="🛑"):
        stopped_any = True

    # 4. Stop MT5
    if _is_running(PID_MT5):
        _stop_mt5()
        stopped_any = True

    if not stopped_any:
        print("   No processes found running.")
    else:
        print("✅ Noema stopped. All positions held at broker.")


def cmd_status(args: argparse.Namespace) -> None:
    """Quick status check."""
    print(f"🧠 Noema v{VERSION}")

    trading_running = _is_running(PID_TRADING)
    api_running = _is_running(PID_DASHBOARD_API)
    frontend_running = _is_running(PID_DASHBOARD_FRONTEND)
    mt5_running = _is_running(PID_MT5)

    if trading_running:
        # Try to get uptime from PID file stat
        try:
            pid = _read_pid(PID_TRADING)
            # Get process start time from /proc
            stat_path = Path(f"/proc/{pid}/stat")
            if stat_path.exists():
                boot_time = float(Path("/proc/stat").read_text().splitlines()[0].split()[1])
                proc_start_jiffies = int(stat_path.read_text().split()[21])
                hertz = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
                uptime_seconds = time.time() - (boot_time + proc_start_jiffies / hertz)
                if uptime_seconds < 0:
                    uptime_seconds = 0  # clock skew guard
                hours = int(uptime_seconds // 3600)
                mins = int((uptime_seconds % 3600) // 60)
                uptime_str = f" (uptime: {hours}h {mins}m)"
            else:
                uptime_str = ""
        except Exception:
            uptime_str = ""

        print(f"   Status: 🟢 RUNNING{uptime_str}")
        print(f"   Dashboard: http://localhost:3000")
    else:
        print("   Status: ⚫ NOT RUNNING")

    if api_running:
        print(f"   Dashboard API: 🟢 running (port 8000)")
    if frontend_running:
        print(f"   Dashboard UI:  🟢 running (port 3000)")
    if mt5_running:
        print(f"   MT5:           🟢 running (port 18812)")

    # Try to query dashboard API for positions/P&L if API is running
    if api_running:
        _try_print_positions()

    print()


def _try_print_positions() -> None:
    """Query the dashboard API for positions and guardian status."""
    import urllib.request
    import json

    try:
        # Try positions endpoint
        req = urllib.request.Request("http://127.0.0.1:8000/api/positions", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
            positions = data if isinstance(data, list) else data.get("positions", [])
            if positions:
                for pos in positions:
                    symbol = pos.get("symbol", "???")
                    side = pos.get("direction", pos.get("type", "???"))
                    entry = pos.get("entry_price", 0)
                    pnl = pos.get("pnl", pos.get("profit", 0))
                    pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
                    print(f"   📊 {symbol} {side.upper()} @{entry} | {pnl_str}")
    except Exception:
        pass

    try:
        # Try guardian/health endpoint
        req = urllib.request.Request("http://127.0.0.1:8000/api/health", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
            guardian = data.get("guardian", {})
            if guardian:
                checks = f"{guardian.get('passing', '?')}/{guardian.get('total', '?')}"
                margin = guardian.get("margin_pct", "?")
                print(f"   🛡️ Guardian: {checks} OK | Margin: {margin}%")
    except Exception:
        pass


def cmd_dashboard(args: argparse.Namespace) -> None:
    """Start dashboard only (API + frontend)."""
    print(f"🧠 Noema v{VERSION}")

    # Check if already running
    if _is_running(PID_DASHBOARD_API):
        print("⚠️  Dashboard already running at http://localhost:3000")
        _open_browser("http://localhost:3000")
        return

    venv_python = PROJECT_ROOT / ".venv" / "bin" / "python"
    python_exe = str(venv_python) if venv_python.exists() else sys.executable
    dashboard_dir = PROJECT_ROOT / "dashboard"

    # Start API
    api_script = dashboard_dir / "server" / "api.py"
    if api_script.exists():
        _print("📊", "Starting dashboard API...")
        _run_background(
            [python_exe, str(api_script)],
            PID_DASHBOARD_API,
            LOG_DASHBOARD_API,
            cwd=PROJECT_ROOT,
        )
        _wait_for_port(8000, label="API (port 8000)")
    else:
        print("   ⚠️ Dashboard API not found")

    # Start frontend
    npm_tool = _find_npm_or_npx()
    if npm_tool and (dashboard_dir / "package.json").exists():
        _print("📊", "Starting dashboard frontend...")
        if npm_tool == "npx":
            frontend_cmd = ["npx", "vite", "--port", "3000", "--host"]
        else:
            frontend_cmd = ["npm", "run", "dev"]
        _run_background(
            frontend_cmd,
            PID_DASHBOARD_FRONTEND,
            LOG_DASHBOARD_FRONTEND,
            cwd=dashboard_dir,
        )
        _wait_for_url("http://localhost:3000", label="frontend (port 3000)")
    else:
        print("   ⚠️ npm not found — skipping dashboard frontend")

    # Only open browser if frontend is actually responding
    frontend_ok = _wait_for_url("http://localhost:3000", timeout=5, label="frontend check")
    if frontend_ok:
        _open_browser("http://localhost:3000")
    else:
        _print_url_box("http://localhost:3000")
    print(f"✅ Dashboard running at http://localhost:3000")
    print()


def cmd_setup_mt5_ea(args: argparse.Namespace) -> None:
    """Copy the mt5linux Expert Advisor into MT5's Experts directory.

    This EA is required — it runs inside MT5 and exposes the RPyC bridge
    on port 18812. Without it, Noema cannot communicate with MT5.
    """
    print(f"🧠 Noema v{VERSION}")
    print()
    try:
        result = subprocess.run(
            [sys.executable, "-m", "noema.scripts.mt5_daemon", "setup-mt5-ea"],
            cwd=PROJECT_ROOT,
        )
        sys.exit(result.returncode)
    except Exception as exc:
        print(f"  ✗ Failed: {exc}")
        sys.exit(1)


def cmd_logs(args: argparse.Namespace) -> None:
    """Tail live logs from all Noema components."""
    log_files = []
    for pf in [LOG_TRADING, LOG_DASHBOARD_API, LOG_DASHBOARD_FRONTEND]:
        if pf.exists():
            log_files.append(pf)

    if not log_files:
        print("📜 No log files found. Start Noema first: noema start")
        return

    # Use tail -f to follow all log files
    print(f"📜 Tailing {len(log_files)} log file(s)... (Ctrl+C to stop)")
    print()
    try:
        subprocess.run(["tail", "-f"] + [str(f) for f in log_files])
    except KeyboardInterrupt:
        print()
    except FileNotFoundError:
        # Fallback: just cat the last 50 lines
        for lf in log_files:
            print(f"\n── {lf.name} ──")
            with open(lf) as f:
                lines = f.readlines()
                for line in lines[-50:]:
                    print(line, end="")
        print()


# ── Main ──────────────────────────────────────────────────────────


def main() -> None:
    """Noema CLI entry point."""
    parser = argparse.ArgumentParser(
        description="🧠 Noema — Multi-Agent Quantitative Forex Trading",
    )
    sub = parser.add_subparsers(dest="command", help="Command")

    # start
    p_start = sub.add_parser("start", help="Start everything: MT5, dashboard, trading")
    p_start.set_defaults(func=cmd_start)

    # stop
    p_stop = sub.add_parser("stop", help="Graceful shutdown")
    p_stop.set_defaults(func=cmd_stop)

    # status
    p_status = sub.add_parser("status", help="Quick status check")
    p_status.set_defaults(func=cmd_status)

    # dashboard
    p_dashboard = sub.add_parser("dashboard", help="Start dashboard only")
    p_dashboard.set_defaults(func=cmd_dashboard)

    # setup-mt5-ea
    p_setup_ea = sub.add_parser(
        "setup-mt5-ea",
        help="Install mt5linux Expert Advisor into MT5 (required for broker bridge)",
    )
    p_setup_ea.set_defaults(func=cmd_setup_mt5_ea)

    # logs
    p_logs = sub.add_parser("logs", help="Tail live logs")
    p_logs.set_defaults(func=cmd_logs)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    # Run the command
    args.func(args)


if __name__ == "__main__":
    main()
