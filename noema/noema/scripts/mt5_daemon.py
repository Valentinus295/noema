"""MetaTrader 5 Headless Daemon Manager.

Manages the full lifecycle of MT5 running under Wine on Linux:
  1. Generates config.ini from template + .env credentials
  2. Starts MT5 headless via xvfb-run (or windowed via wine)
  3. Waits for RPyC bridge to become ready (port 18812)
  4. Stops MT5 gracefully (via wineserver -k)
  5. Provides status checks

Usage:
    python -m noema.scripts.mt5_daemon start              # Headless start
    python -m noema.scripts.mt5_daemon start --visible    # Windowed start
    python -m noema.scripts.mt5_daemon stop               # Graceful stop
    python -m noema.scripts.mt5_daemon status             # Check status
    python -m noema.scripts.mt5_daemon wait               # Wait until ready
    python -m noema.scripts.mt5_daemon restart            # Stop + start

Architecture:
    Noema ──► mt5_daemon.py ──► xvfb-run / wine
                    │
                    ├──► Generates config.ini from template
                    ├──► Starts MT5, tracks PID
                    ├──► Polls RPyC port 18812 until ready
                    └──► Provides status for other components
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

# Load .env before anything else so os.getenv() finds credentials
_DOTENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"
if _DOTENV_PATH.exists():
    with open(_DOTENV_PATH) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val


import argparse
import time
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# ═══════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════

DEFAULT_MT5_PATH = Path.home() / ".wine/drive_c/Program Files/MetaTrader 5/terminal64.exe"
DEFAULT_CONFIG_TEMPLATE = Path(__file__).resolve().parent.parent.parent / "config" / "mt5-config.ini.template"
DEFAULT_CONFIG_OUTPUT = Path.home() / ".noema" / "mt5-config.ini"
DEFAULT_RPYC_HOST = "127.0.0.1"
DEFAULT_RPYC_PORT = 18812
DEFAULT_STARTUP_WAIT = 120  # seconds
PID_FILE = Path.home() / ".noema" / "mt5-daemon.pid"


# ═══════════════════════════════════════════════════════════════
# Config Generation
# ═══════════════════════════════════════════════════════════════

def generate_config(
    login: str,
    password: str,
    server: str,
    template_path: str | Path | None = None,
    output_path: str | Path | None = None,
) -> Path:
    """Generate mt5-config.ini from template + credentials.

    Reads the template file, substitutes placeholders with actual
    credentials, and writes the result to the output path.

    Args:
        login: MT5 account login number
        password: MT5 account password
        server: MT5 broker server name
        template_path: Path to config.ini template
        output_path: Where to write the generated config

    Returns:
        Path to the generated config.ini file

    Raises:
        FileNotFoundError: If the template file doesn't exist
    """
    template = Path(template_path) if template_path else DEFAULT_CONFIG_TEMPLATE
    output = Path(output_path) if output_path else DEFAULT_CONFIG_OUTPUT

    if not template.exists():
        raise FileNotFoundError(
            f"MT5 config template not found: {template}\n"
            f"Expected at: {template}"
        )

    content = template.read_text()
    content = content.replace("{{MT5_LOGIN}}", login)
    content = content.replace("{{MT5_PASSWORD}}", password)
    content = content.replace("{{MT5_SERVER}}", server)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content)
    output.chmod(0o600)  # Lock down — contains password

    logger.info(
        "mt5_config_generated",
        path=str(output),
        server=server,
        login=login,
    )
    return output


def load_credentials_from_env() -> tuple[str, str, str]:
    """Load MT5 credentials from environment variables.

    Returns:
        Tuple of (login, password, server)

    Raises:
        ValueError: If any required credential is missing
    """
    login = os.getenv("Noema_MT5_LOGIN", "")
    password = os.getenv("Noema_MT5_PASSWORD", "")
    server = os.getenv("Noema_MT5_SERVER", "")

    missing = []
    if not login:
        missing.append("Noema_MT5_LOGIN")
    if not password:
        missing.append("Noema_MT5_PASSWORD")
    if not server:
        missing.append("Noema_MT5_SERVER")

    if missing:
        raise ValueError(
            f"Missing MT5 credentials in environment: {', '.join(missing)}\n"
            f"Set them in .env or export them before running the daemon."
        )

    return login, password, server


# ═══════════════════════════════════════════════════════════════
# MT5 Process Management
# ═══════════════════════════════════════════════════════════════

def start_mt5(
    mt5_path: str | Path | None = None,
    config_path: str | Path | None = None,
    headless: bool = True,
) -> subprocess.Popen | None:
    """Start MetaTrader 5 terminal under Wine.

    Args:
        mt5_path: Path to terminal64.exe
        config_path: Path to generated config.ini
        headless: If True, use xvfb-run for headless operation

    Returns:
        subprocess.Popen if successful, None otherwise
    """
    exe = Path(mt5_path) if mt5_path else DEFAULT_MT5_PATH

    if not exe.exists():
        logger.error(
            "mt5_not_found",
            path=str(exe),
            hint="Install MT5 via Wine first (download from your broker's website)",
        )
        return None

    if headless:
        # Check xvfb-run availability
        if not _command_exists("xvfb-run"):
            logger.error(
                "xvfb_not_found",
                fix="sudo apt install xvfb",
            )
            return None
        cmd = ["xvfb-run", "-a", "wine", str(exe), "/portable"]
    else:
        cmd = ["wine", str(exe), "/portable"]

    if config_path:
        config = Path(config_path)
        if config.exists():
            # MT5 requires /config:path format (colon, not space).
            # Under Wine, convert Unix path to Wine Z:\ path.
            win_path = _unix_to_wine_path(str(config))
            cmd.append(f"/config:{win_path}")
        else:
            logger.warning("config_not_found", path=str(config))

    logger.info("starting_mt5", headless=headless, cmd=" ".join(cmd))

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # Detach from parent terminal
        )
        # Write PID file
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(process.pid))
        logger.info("mt5_started", pid=process.pid, headless=headless)
        return process
    except FileNotFoundError:
        logger.error("wine_not_found", fix="sudo apt install wine64 wine32")
        return None
    except Exception as exc:
        logger.error("mt5_start_failed", error=str(exc))
        return None


def stop_mt5(pid: int | None = None, force: bool = False) -> bool:
    """Stop MetaTrader 5 gracefully.

    Args:
        pid: Process ID from PID file (auto-read if None)
        force: If True, force-kill immediately

    Returns:
        True if stopped successfully
    """
    # Try PID file first
    if pid is None and PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
        except (ValueError, FileNotFoundError):
            pass

    stopped = False

    # 1. Terminate specific PID if we have it
    if pid is not None:
        try:
            os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)
            logger.info("mt5_process_signaled", pid=pid, force=force)
            stopped = True
        except ProcessLookupError:
            logger.info("mt5_process_not_found", pid=pid)
        except PermissionError:
            logger.warning("mt5_kill_permission_denied", pid=pid)

    # 2. Kill wineserver as well (cleans up all Wine processes)
    if _command_exists("wineserver"):
        try:
            subprocess.run(
                ["wineserver", "-k"],
                capture_output=True, timeout=10,
            )
            logger.info("wineserver_stopped")
            stopped = True
        except Exception as exc:
            logger.warning("wineserver_stop_failed", error=str(exc))

    # 3. Clean up PID file
    if PID_FILE.exists():
        PID_FILE.unlink()

    return stopped


def is_mt5_running() -> dict[str, Any]:
    """Check if MT5 is running and the RPyC bridge is listening.

    Returns:
        Dict with keys: running, pid, rpyc_listening
    """
    result = {
        "running": False,
        "pid": None,
        "rpyc_listening": False,
    }

    # Check wineserver
    try:
        ps = subprocess.run(
            ["pgrep", "-a", "wineserver"],
            capture_output=True, text=True, timeout=5,
        )
        if ps.returncode == 0:
            result["running"] = True
    except Exception:
        pass

    # Check PID file
    if PID_FILE.exists():
        try:
            result["pid"] = int(PID_FILE.read_text().strip())
        except (ValueError, FileNotFoundError):
            pass

    # Check RPyC port
    result["rpyc_listening"] = _check_port(
        DEFAULT_RPYC_HOST, DEFAULT_RPYC_PORT, timeout=2.0
    )

    return result


def wait_for_mt5_ready(
    host: str | None = None,
    port: int | None = None,
    timeout: float = 120.0,
    poll_interval: float = 2.0,
) -> bool:
    """Wait for MT5 RPyC bridge to become available.

    Polls the RPyC port at regular intervals until the bridge responds.
    Prints progress dots during the wait.

    Args:
        host: RPyC host (default: 127.0.0.1)
        port: RPyC port (default: 18812)
        timeout: Maximum wait time in seconds
        poll_interval: Time between polls in seconds

    Returns:
        True if MT5 became ready, False if timeout expired
    """
    h = host or DEFAULT_RPYC_HOST
    p = port or DEFAULT_RPYC_PORT

    logger.info("waiting_for_mt5", host=h, port=p, timeout=timeout)

    start = time.monotonic()
    dots = 0
    while (time.monotonic() - start) < timeout:
        if _check_port(h, p, timeout=1.0):
            elapsed = time.monotonic() - start
            logger.info(
                "mt5_ready",
                host=h,
                port=p,
                elapsed_seconds=round(elapsed, 1),
            )
            return True

        # Progress indicator
        dots += 1
        if dots % 10 == 0:
            elapsed = time.monotonic() - start
            logger.info(
                "mt5_still_waiting",
                elapsed=int(elapsed),
                remaining=int(timeout - elapsed),
            )
        time.sleep(poll_interval)

    logger.error(
        "mt5_timeout",
        host=h,
        port=p,
        timeout=timeout,
        hint="MT5 did not become ready. Likely: 1) mt5linux EA not installed in MT5 (pip install mt5linux && mt5linux.install), 2) EA not attached to chart, 3) Wine/MT5 not installed",
    )
    return False


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _command_exists(cmd: str) -> bool:
    """Check if a command is available in PATH."""
    import shutil
    return shutil.which(cmd) is not None


def _unix_to_wine_path(unix_path: str) -> str:
    """Convert a Unix path to a Wine-compatible Windows path.

    Wine maps the Unix filesystem root (/) to the Z: drive.
    Example: /home/user/.noema/mt5-config.ini → Z:\\home\\user\\.noema\\mt5-config.ini
    """
    try:
        result = subprocess.run(
            ["winepath", "-w", unix_path],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return "Z:" + unix_path.replace("/", "\\")


def _check_port(host: str, port: int, timeout: float = 1.0) -> bool:
    """Check if a TCP port is accepting connections."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def _build_parser() -> argparse.ArgumentParser:
    """Build argument parser for mt5_daemon CLI."""
    parser = argparse.ArgumentParser(
        description="Noema MT5 Headless Daemon",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m noema.scripts.mt5_daemon start              # Start headless
  python -m noema.scripts.mt5_daemon start --visible    # Start with window
  python -m noema.scripts.mt5_daemon stop               # Stop MT5
  python -m noema.scripts.mt5_daemon status             # Check status
  python -m noema.scripts.mt5_daemon wait               # Wait until ready
  python -m noema.scripts.mt5_daemon restart            # Stop + start
        """,
    )
    sub = parser.add_subparsers(dest="command", help="Command to run")

    # start
    start_p = sub.add_parser("start", help="Start MT5 daemon")
    start_p.add_argument(
        "--visible", action="store_true",
        help="Start with a visible Wine window (default: headless)",
    )
    start_p.add_argument(
        "--mt5-path", type=str,
        help=f"Path to terminal64.exe (default: {DEFAULT_MT5_PATH})",
    )
    start_p.add_argument(
        "--config", type=str,
        help="Path to config.ini (auto-generated if not provided)",
    )
    start_p.add_argument(
        "--wait-timeout", type=float, default=DEFAULT_STARTUP_WAIT,
        help=f"Seconds to wait for MT5 to be ready (default: {DEFAULT_STARTUP_WAIT})",
    )

    # stop
    stop_p = sub.add_parser("stop", help="Stop MT5 daemon")
    stop_p.add_argument(
        "--force", action="store_true",
        help="Force-kill immediately instead of graceful shutdown",
    )

    # status
    sub.add_parser("status", help="Check MT5 daemon status")

    # wait
    wait_p = sub.add_parser("wait", help="Wait for MT5 to be ready")
    wait_p.add_argument(
        "--timeout", type=float, default=DEFAULT_STARTUP_WAIT,
        help=f"Max wait time in seconds (default: {DEFAULT_STARTUP_WAIT})",
    )

    # restart
    sub.add_parser("restart", help="Stop and restart MT5 daemon")

    # generate-config
    sub.add_parser("generate-config", help="Generate config.ini from .env credentials")

    # setup-mt5-ea
    sub.add_parser("setup-mt5-ea", help="Copy mt5linux EA to MT5 Experts directory")

    return parser


def _cmd_start(args: argparse.Namespace) -> int:
    """Start MT5 daemon."""
    # ── Pre-flight: ensure mt5linux EA is installed ─────────────
    from noema.scripts.start_mt5 import setup_mt5linux_ea, _find_mt5linux_ea
    ea_path = _find_mt5linux_ea()
    if ea_path and not ea_path.exists():
        logger.warning(
            "mt5linux_ea_missing",
            path=str(ea_path),
            hint="The mt5linux Expert Advisor is required for the RPyC bridge.",
        )
        if not setup_mt5linux_ea():
            print(f"\n  ⚠️  mt5linux EA not found in MT5 Experts directory")
            print(f"     Expected: {ea_path}")
            print(f"     Without this EA, port {DEFAULT_RPYC_PORT} will NOT open.")
            print(f"     → Install manually: pip install mt5linux")
            print(f"     → Then copy mt5linux.ex5 to {ea_path.parent}")
            print(f"     → Or run: python -m noema.scripts.mt5_daemon setup-mt5-ea\n")
    else:
        logger.info("mt5linux_ea_found", path=str(ea_path) if ea_path else "unknown")

    # Generate config from .env if not provided
    config_path = args.config
    if not config_path:
        try:
            login, password, server = load_credentials_from_env()
            config_path = generate_config(login, password, server)
        except (ValueError, FileNotFoundError) as exc:
            logger.error("config_generation_failed", error=str(exc))
            return 1

    # Start MT5
    process = start_mt5(
        mt5_path=args.mt5_path,
        config_path=config_path,
        headless=not args.visible,
    )

    if process is None:
        return 1

    mode = "headless" if not args.visible else "windowed"
    print(f"\n  ✓ MT5 started ({mode})")
    print(f"    PID: {process.pid}")

    # Wait for ready
    print(f"  → Waiting for MT5 to be ready (timeout: {args.wait_timeout}s)...")
    ready = wait_for_mt5_ready(timeout=args.wait_timeout)

    if ready:
        print(f"  ✓ MT5 ready — RPyC port {DEFAULT_RPYC_PORT} responding")
        print(f"  ✓ MT5 running in background — Noema will auto-connect\n")
        return 0
    else:
        print(f"  ✗ MT5 did not become ready within {args.wait_timeout}s")
        print(f"  → Check: winecfg, MT5 installation, mt5linux server")
        win_path = _unix_to_wine_path(str(config_path))
        print(f"  → Manually: wine '{DEFAULT_MT5_PATH}' /portable '/config:{win_path}'\n")
        return 1


def _cmd_stop(args: argparse.Namespace) -> int:
    """Stop MT5 daemon."""
    print("")
    if stop_mt5(force=args.force):
        print("  ✓ MT5 stopped\n")
        return 0
    else:
        print("  ⚠ MT5 was not running\n")
        return 0


def _cmd_status(args: argparse.Namespace) -> int:
    """Check MT5 daemon status."""
    status = is_mt5_running()

    print("\n  ── MT5 Daemon Status ──")
    print(f"  Wine process:    {'✓ Running' if status['running'] else '✗ Not running'}")
    if status['pid']:
        print(f"  PID:             {status['pid']}")
    print(f"  RPyC bridge:     {'✓ Listening' if status['rpyc_listening'] else '✗ Not listening'}")
    print(f"  Host:Port:       {DEFAULT_RPYC_HOST}:{DEFAULT_RPYC_PORT}")
    print(f"  PID file:        {PID_FILE}")
    print("")

    return 0 if status["rpyc_listening"] else 1


def _cmd_wait(args: argparse.Namespace) -> int:
    """Wait for MT5 to be ready."""
    print(f"\n  → Waiting for MT5 (timeout: {args.timeout}s)...")
    ready = wait_for_mt5_ready(timeout=args.timeout)

    if ready:
        print(f"  ✓ MT5 ready\n")
        return 0
    else:
        print(f"  ✗ MT5 did not become ready\n")
        return 1


def _cmd_restart(args: argparse.Namespace) -> int:
    """Restart MT5 daemon."""
    print("")
    print("  → Stopping MT5...")
    stop_mt5()

    # Brief pause to let wineserver clean up
    time.sleep(3)

    print("  → Starting MT5...")
    try:
        login, password, server = load_credentials_from_env()
        config_path = generate_config(login, password, server)
    except (ValueError, FileNotFoundError) as exc:
        logger.error("config_generation_failed", error=str(exc))
        return 1

    process = start_mt5(config_path=config_path, headless=True)
    if process is None:
        return 1

    print(f"    MT5 PID: {process.pid}")
    print(f"  → Waiting for MT5 to be ready...")

    ready = wait_for_mt5_ready(timeout=DEFAULT_STARTUP_WAIT)
    if ready:
        print(f"  ✓ MT5 restarted and ready\n")
        return 0
    else:
        print(f"  ✗ MT5 did not become ready\n")
        return 1


def _cmd_setup_mt5_ea(args: argparse.Namespace) -> int:
    """Copy the mt5linux Expert Advisor into MT5's Experts directory."""
    from noema.scripts.start_mt5 import setup_mt5linux_ea, _find_mt5linux_ea

    print("")
    ea_dest = _find_mt5linux_ea()
    if ea_dest and ea_dest.exists():
        print(f"  ✅ mt5linux EA already present: {ea_dest}")
        print(f"     MT5 should expose RPyC on port {DEFAULT_RPYC_PORT} when the EA is attached to a chart.\n")
        return 0

    print("  → Locating mt5linux EA in Python package...")
    if setup_mt5linux_ea():
        print(f"  ✅ EA copied to: {ea_dest}")
        print(f"     → Start MT5, then attach the 'mt5linux' expert to any chart.")
        print(f"     → The RPyC bridge will listen on port {DEFAULT_RPYC_PORT}.\n")
        return 0
    else:
        print(f"  ✗ Failed to locate mt5linux.ex5 in the Python package.")
        print(f"     → Ensure mt5linux is installed: pip install mt5linux")
        print(f"     → Or download the EA from: https://github.com/lucas-campagna/mt5linux/releases")
        print(f"     → Copy mt5linux.ex5 to: {ea_dest}\n")
        return 1


def _cmd_generate_config(args: argparse.Namespace) -> int:
    """Generate config.ini from .env credentials."""
    try:
        login, password, server = load_credentials_from_env()
        output = generate_config(login, password, server)
        print(f"\n  ✓ Config generated: {output}")
        print(f"    Server: {server}")
        print(f"    Login:  {login}")
        print(f"    Perms:  600 (owner read/write only)\n")
        return 0
    except (ValueError, FileNotFoundError) as exc:
        print(f"\n  ✗ Failed: {exc}\n")
        return 1


def main() -> int:
    """CLI entry point for mt5_daemon."""
    parser = _build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 1

    handlers = {
        "start": _cmd_start,
        "stop": _cmd_stop,
        "status": _cmd_status,
        "wait": _cmd_wait,
        "restart": _cmd_restart,
        "generate-config": _cmd_generate_config,
        "setup-mt5-ea": _cmd_setup_mt5_ea,
    }

    handler = handlers.get(args.command)
    if handler:
        return handler(args)

    return 1


if __name__ == "__main__":
    sys.exit(main())
