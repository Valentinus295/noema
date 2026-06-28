"""
Noema CLI — Dead-simple daily commands.

Usage:
    noema live        LIVE DEMO trading (real MT5 data, demo account)
    noema start       Start everything (MT5, dashboard, trading)
    noema stop        Graceful shutdown
    noema status      Quick status check
    noema dashboard   Start dashboard only
    noema logs        Tail live logs
    noema demo-check  Verify demo account (no real money allowed)
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

# ── First-run micro-lot enforcement ──
FIRST_RUN_LOT_SIZE = 0.01
FIRST_RUN_FLAG_FILE = Path.home() / ".noema" / ".first-run-complete"


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


# ── Demo Account Verification ───────────────────────────────────────

def _verify_demo_account() -> tuple[bool, str]:
    """Verify that the MT5 broker is connected to a DEMO server.
    
    CRITICAL SAFETY CHECK: Blocks trading on real/live accounts.
    Returns (is_demo, server_name).
    """
    try:
        from mt5linux import MetaTrader5
        mt5 = MetaTrader5(host="127.0.0.1", port=18812)
        if not mt5.initialize():
            return False, "Cannot connect to MT5"
        info = mt5.account_info()
        mt5.shutdown()
        if info is None:
            return False, "Cannot get account info"
        server = info.server.lower()
        is_demo = "demo" in server
        return is_demo, info.server
    except ImportError:
        return False, "mt5linux not installed"
    except Exception as exc:
        return False, f"Error: {exc}"


def _is_first_run() -> bool:
    """Check if this is the first live trading run."""
    return not FIRST_RUN_FLAG_FILE.exists()


def _mark_first_run_complete() -> None:
    """Mark first run as complete (unlocks full lot sizes)."""
    FIRST_RUN_FLAG_FILE.parent.mkdir(parents=True, exist_ok=True)
    FIRST_RUN_FLAG_FILE.write_text("complete")


# ── Commands ──────────────────────────────────────────────────────


def cmd_live(args: argparse.Namespace) -> None:
    """Start LIVE DEMO trading with real market data on a demo account."""
    print(f"🧠 Noema v{VERSION} — LIVE DEMO TRADING")
    print("=" * 60)

    env = _load_env()

    # 0. Check .env
    env_path = _find_env()
    if not env_path:
        print("❌ No .env file found.")
        print("   Run ./noema-setup first to create your configuration.")
        sys.exit(1)
    _print("📋", "Loading .env...")

    # 1. SAFETY: Verify MT5 broker is DEMO account
    print()
    print("🛡️  SAFETY CHECK: Verifying DEMO account...")
    is_demo, server_name = _verify_demo_account()
    if not is_demo:
        print(f"❌ LIVE TRADING BLOCKED!")
        print(f"   Connected to: {server_name}")
        print(f"   This does NOT appear to be a demo server.")
        print(f"   Noema will NEVER trade on a real/live account without explicit approval.")
        sys.exit(1)
    _print("✅", f"Demo account verified: {server_name}")

    # 2. Show account info
    try:
        from mt5linux import MetaTrader5
        mt5_temp = MetaTrader5(host="127.0.0.1", port=18812)
        if mt5_temp.initialize():
            info = mt5_temp.account_info()
            if info:
                print(f"   Login: {info.login}")
                print(f"   Balance: ${float(info.balance):,.2f}")
                print(f"   Equity: ${float(info.equity):,.2f}")
                print(f"   Leverage: 1:{info.leverage}")
                print(f"   Currency: {info.currency}")
            mt5_temp.shutdown()
    except Exception:
        pass

    # 3. First-run safety: micro-lot enforcement
    first_run = _is_first_run()
    if first_run:
        print()
        print("🔰 FIRST RUN DETECTED — Micro-Lot Safety Mode")
        print(f"   Lot size capped at: {FIRST_RUN_LOT_SIZE}")
        print(f"   After a successful session, run 'noema live --unlock' to lift cap.")
        os.environ["Noema_FIRST_RUN"] = "true"
        os.environ["Noema_MAX_LOT_SIZE"] = str(FIRST_RUN_LOT_SIZE)
    elif args.unlock:
        print()
        print("🔓 Unlocking full lot sizes...")
        _mark_first_run_complete()
        print("   First-run restrictions lifted. Full lot sizes enabled.")
        os.environ.pop("Noema_FIRST_RUN", None)
        os.environ["Noema_MAX_LOT_SIZE"] = env.get("Noema_MAX_LOT_SIZE", "1.0")

    # 4. Check if already running
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

    # 5. Check for venv
    venv_python = PROJECT_ROOT / ".venv" / "bin" / "python"
    if venv_python.exists():
        _print("🐍", "Activating venv...")
        python_exe = str(venv_python)
    else:
        python_exe = sys.executable

    # 6. Install mt5linux EA if needed
    _print("🔧", "Checking MT5 Expert Advisor...")
    try:
        subprocess.run(
            [sys.executable, "-m", "noema.scripts.mt5_daemon", "setup-mt5-ea"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            timeout=30,
        )
    except Exception:
        pass

    # 7. Start MT5 headless
    print()
    if _should_start_mt5(env):
        if not _start_mt5():
            print("❌ MT5 did not start — cannot proceed with live trading")
            sys.exit(1)
        startup_wait = int(env.get("Noema_MT5_STARTUP_WAIT", "120"))
        if not _wait_for_port(18812, timeout=startup_wait, label="MT5 (port 18812)"):
            print("❌ MT5 bridge not responding on port 18812")
            print("   Check: wine MT5 running? mt5linux EA installed?")
            sys.exit(1)
    else:
        if not _wait_for_port(18812, timeout=5, label="MT5 (port 18812)"):
            print("❌ MT5 bridge not detected on port 18812")
            print("   Set Noema_MT5_HEADLESS=true in .env for auto-start")
            print("   Or start manually: python -m noema.scripts.mt5_daemon start")
            sys.exit(1)

    # 8. Start dashboard API
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

    # 9. Start dashboard frontend
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

    # 10. Open browser
    if _is_running(PID_DASHBOARD_FRONTEND):
        _open_browser("http://localhost:3000")
    else:
        _print_url_box("http://localhost:3000")

    # 11. Start trading engine in LIVE mode
    print()
    _print("📈", "Starting LIVE TRADING engine...")
    trading_args = [python_exe, "-m", "noema.main", "--mode", "live", "--mt5-auto"]
    if first_run:
        trading_args.append("--first-run")
    _run_background(
        trading_args,
        PID_TRADING,
        LOG_TRADING,
        cwd=PROJECT_ROOT,
    )

    time.sleep(2)
    if _is_running(PID_TRADING):
        _print("✅", "LIVE TRADING engine started")
    else:
        print("⚠️  Trading engine may have failed — check logs: noema logs")

    # 12. Summary
    telegram_token = env.get("TELEGRAM_BOT_TOKEN", "")
    telegram_status = "active" if telegram_token else "not configured"
    guardian_switches = "ALL 17 active" if not first_run else "ALL 17 active (micro-lot mode)"
    print()
    print("=" * 60)
    print(f"🔴 LIVE DEMO TRADING — No Real Money")
    print(f"   Dashboard: http://localhost:3000")
    print(f"   Logs:      noema logs")
    print(f"   Status:    noema status")
    print(f"   Telegram:  {telegram_status}")
    print(f"   Guardian:  {guardian_switches}")
    print(f"   Lot size:  {FIRST_RUN_LOT_SIZE if first_run else env.get('Noema_MAX_LOT_SIZE', '1.0')}")
    if first_run:
        print(f"   ⚠️  First run — micro-lot safety cap active")
        print(f"   👉 After successful run: noema live --unlock")
    print("=" * 60)
    print()


def cmd_demo_check(args: argparse.Namespace) -> None:
    """Verify the MT5 connection is to a DEMO account (NO real money)."""
    print(f"🧠 Noema v{VERSION} — Demo Account Verification")
    print("=" * 60)

    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2.0)
    port_open = sock.connect_ex(("127.0.0.1", 18812)) == 0
    sock.close()

    if not port_open:
        print("❌ MT5 bridge not detected on port 18812")
        print("   Start MT5 first: python -m noema.scripts.mt5_daemon start")
        sys.exit(1)

    print("✅ MT5 bridge detected on port 18812")

    is_demo, server_name = _verify_demo_account()
    if is_demo:
        print(f"✅ DEMO ACCOUNT: {server_name}")
        print("   Safe for live trading — no real money at risk.")
        try:
            from mt5linux import MetaTrader5
            mt5 = MetaTrader5(host="127.0.0.1", port=18812)
            if mt5.initialize():
                info = mt5.account_info()
                if info:
                    print(f"   Login:    {info.login}")
                    print(f"   Balance:  ${float(info.balance):,.2f}")
                    print(f"   Equity:   ${float(info.equity):,.2f}")
                    print(f"   Leverage: 1:{info.leverage}")
                    print(f"   Currency: {info.currency}")
                positions = mt5.positions_get()
                if positions:
                    print(f"   Open positions: {len(positions)}")
                    for p in positions[:5]:
                        side = "LONG" if p.type == 0 else "SHORT"
                        print(f"     #{p.ticket} {p.symbol} {side} {p.volume} lot @ {p.price_open}")
                else:
                    print(f"   Open positions: 0")
                mt5.shutdown()
        except Exception as exc:
            print(f"   ⚠️ Could not get details: {exc}")
    else:
        print(f"❌ NOT A DEMO ACCOUNT: {server_name}")
        print("   ⚠️  This appears to be a LIVE/REAL account!")
        print("   Noema will BLOCK trading on this account.")
        print("   Configure a demo server in .env:")
        print("     Noema_MT5_SERVER=FxPesa-Demo")
        sys.exit(1)

    print()
    print("Ready for live demo trading: noema live")


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
        try:
            pid = _read_pid(PID_TRADING)
            stat_path = Path(f"/proc/{pid}/stat")
            if stat_path.exists():
                boot_time = float(Path("/proc/stat").read_text().splitlines()[0].split()[1])
                proc_start_jiffies = int(stat_path.read_text().split()[21])
                hertz = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
                uptime_seconds = time.time() - (boot_time + proc_start_jiffies / hertz)
                if uptime_seconds < 0:
                    uptime_seconds = 0
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

    if api_running:
        _try_print_positions()
    print()


def _try_print_positions() -> None:
    """Query the dashboard API for positions and guardian status."""
    import urllib.request
    import json
    try:
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
    if _is_running(PID_DASHBOARD_API):
        print("⚠️  Dashboard already running at http://localhost:3000")
        _open_browser("http://localhost:3000")
        return

    venv_python = PROJECT_ROOT / ".venv" / "bin" / "python"
    python_exe = str(venv_python) if venv_python.exists() else sys.executable
    dashboard_dir = PROJECT_ROOT / "dashboard"

    api_script = dashboard_dir / "server" / "api.py"
    if api_script.exists():
        _print("📊", "Starting dashboard API...")
        _run_background([python_exe, str(api_script)], PID_DASHBOARD_API, LOG_DASHBOARD_API, cwd=PROJECT_ROOT)
        _wait_for_port(8000, label="API (port 8000)")
    else:
        print("   ⚠️ Dashboard API not found")

    npm_tool = _find_npm_or_npx()
    if npm_tool and (dashboard_dir / "package.json").exists():
        _print("📊", "Starting dashboard frontend...")
        if npm_tool == "npx":
            frontend_cmd = ["npx", "vite", "--port", "3000", "--host"]
        else:
            frontend_cmd = ["npm", "run", "dev"]
        _run_background(frontend_cmd, PID_DASHBOARD_FRONTEND, LOG_DASHBOARD_FRONTEND, cwd=dashboard_dir)
        _wait_for_url("http://localhost:3000", label="frontend (port 3000)")
    else:
        print("   ⚠️ npm not found — skipping dashboard frontend")

    frontend_ok = _wait_for_url("http://localhost:3000", timeout=5, label="frontend check")
    if frontend_ok:
        _open_browser("http://localhost:3000")
    else:
        _print_url_box("http://localhost:3000")
    print(f"✅ Dashboard running at http://localhost:3000")
    print()


def cmd_setup_mt5_ea(args: argparse.Namespace) -> None:
    """Copy the mt5linux Expert Advisor into MT5's Experts directory."""
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
    print(f"📜 Tailing {len(log_files)} log file(s)... (Ctrl+C to stop)")
    print()
    try:
        subprocess.run(["tail", "-f"] + [str(f) for f in log_files])
    except KeyboardInterrupt:
        print()
    except FileNotFoundError:
        for lf in log_files:
            print(f"\n── {lf.name} ──")
            with open(lf) as f:
                lines = f.readlines()
                for line in lines[-50:]:
                    print(line, end="")
        print()


# ── Main ──────────────────────────────────────────────────────────


def cmd_update(args: argparse.Namespace) -> None:
    """Pull latest changes and update all dependencies."""
    print(f"🧠 Noema v{VERSION} — Update")
    print()

    # 1. Git pull
    _print("📦", "Pulling latest changes...")
    result = subprocess.run(
        ["git", "pull", "--rebase", "--autostash"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"   ⚠️  git pull failed: {result.stderr.strip()}")
        print("   Resolve conflicts manually, then run noema update again.")
        sys.exit(1)
    else:
        output = result.stdout.strip()
        if "Already up to date" in output or "Already up-to-date" in output:
            _print("✅", "Already up to date.")
        else:
            _print("✅", "Updated to latest.")
            for line in output.splitlines()[-3:]:
                print(f"   {line}")
    print()

    # 2. Python dependencies
    venv_python = PROJECT_ROOT / ".venv" / "bin" / "python"
    uv_bin = PROJECT_ROOT / ".venv" / "bin" / "uv"

    if uv_bin.exists():
        _print("🐍", "Updating Python dependencies (uv sync)...")
        r = subprocess.run(
            [str(uv_bin), "sync"],
            cwd=PROJECT_ROOT,
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            _print("✅", "Python dependencies updated.")
        else:
            print(f"   ⚠️  uv sync failed: {r.stderr.strip()}")
    elif venv_python.exists():
        _print("🐍", "Updating Python dependencies (pip)...")
        r = subprocess.run(
            [str(venv_python), "-m", "pip", "install", "-e", ".", "--quiet"],
            cwd=PROJECT_ROOT,
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            _print("✅", "Python dependencies updated.")
        else:
            print(f"   ⚠️  pip install failed: {r.stderr.strip()}")
    else:
        _print("⏭️", "No venv found — skipping Python deps.")
    print()

    # 3. Dashboard npm dependencies
    dashboard_dir = PROJECT_ROOT / "dashboard"
    if (dashboard_dir / "package.json").exists():
        npm_tool = _find_npm_or_npx()
        if npm_tool:
            _print("📊", "Updating dashboard dependencies...")
            if npm_tool == "npm":
                r = subprocess.run(
                    ["npm", "install"],
                    cwd=dashboard_dir, capture_output=True, text=True,
                )
            else:
                r = subprocess.run(
                    ["npx", "npm", "install"],
                    cwd=dashboard_dir, capture_output=True, text=True,
                )
            if r.returncode == 0:
                _print("✅", "Dashboard dependencies updated.")
            else:
                print(f"   ⚠️  npm install failed: {r.stderr.strip()}")
        else:
            _print("⏭️", "npm not found — skipping dashboard deps.")
    print()

    # 4. Rust crates
    rust_dir = PROJECT_ROOT / "rust"
    if (rust_dir / "Cargo.toml").exists():
        cargo_bin = Path.home() / ".cargo" / "bin" / "cargo"
        if not cargo_bin.exists():
            cargo_bin = _which("cargo")
        if cargo_bin:
            _print("🦀", "Updating Rust crates...")
            r = subprocess.run(
                [str(cargo_bin), "update"],
                cwd=rust_dir, capture_output=True, text=True,
            )
            if r.returncode == 0:
                _print("✅", "Rust dependencies updated.")
            else:
                print(f"   ⚠️  cargo update failed: {r.stderr.strip()}")
        else:
            _print("⏭️", "cargo not found — skipping Rust deps.")
    print()

    # 5. Docker services
    compose_file = PROJECT_ROOT / "docker-compose.yml"
    if compose_file.exists() and _which("docker"):
        _print("🐳", "Pulling latest Docker images...")
        r = subprocess.run(
            ["docker", "compose", "pull", "--quiet"],
            cwd=PROJECT_ROOT, capture_output=True, text=True,
        )
        if r.returncode == 0:
            _print("✅", "Docker images updated.")
        else:
            print(f"   ⚠️  docker pull skipped: {r.stderr.strip()}")
    print()

    _print("✅", "Update complete! Run 'noema start' to launch.")
    print()


def _which(name: str) -> Optional[str]:
    """Find executable in PATH."""
    for d in os.environ.get("PATH", "").split(os.pathsep):
        p = os.path.join(d, name)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def main() -> None:
    """Noema CLI entry point."""
    parser = argparse.ArgumentParser(
        description="🧠 Noema — Multi-Agent Quantitative Forex Trading",
    )
    sub = parser.add_subparsers(dest="command", help="Command")

    # live — THE primary command for live demo trading
    p_live = sub.add_parser(
        "live",
        help="Start LIVE DEMO trading (real MT5 data, demo account, NO real money)",
    )
    p_live.add_argument(
        "--unlock", action="store_true",
        help="Unlock full lot sizes after successful first run",
    )
    p_live.set_defaults(func=cmd_live)

    # demo-check — verify demo account before trading
    p_demo = sub.add_parser(
        "demo-check",
        help="Verify MT5 connection is a DEMO account (safety check)",
    )
    p_demo.set_defaults(func=cmd_demo_check)

    # start
    p_start = sub.add_parser("start", help="Start everything: MT5, dashboard, trading")
    p_start.set_defaults(func=cmd_start)

    # update
    p_update = sub.add_parser("update", help="Pull latest and update all dependencies")
    p_update.set_defaults(func=cmd_update)

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
