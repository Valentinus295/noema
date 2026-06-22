"""MT5 startup and connection test scripts for Wine on Linux.

Usage:
    python -m vmpm.scripts.start_mt5          # Start MT5 under Wine
    python -m vmpm.scripts.test_connection    # Test RPyC bridge connection
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

logger = structlog.get_logger(__name__)

# Default MT5 paths under Wine
WINE_MT5_PATH = Path.home() / ".wine/drive_c/Program Files/MetaTrader 5/terminal64.exe"
RPYC_PORT = 18812


def start_mt5(
    mt5_path: str | Path | None = None,
    config_path: str | Path | None = None,
    headless: bool = False,
) -> subprocess.Popen | None:
    """Start MT5 terminal under Wine.

    Args:
        mt5_path: Path to terminal64.exe (default: ~/.wine/.../MetaTrader 5/)
        config_path: Optional config.ini path
        headless: If True, use Xvfb for headless display
    """
    mt5_exe = Path(mt5_path) if mt5_path else WINE_MT5_PATH

    if not mt5_exe.exists():
        logger.error("mt5_not_found", path=str(mt5_exe))
        return None

    cmd = ["wine", str(mt5_exe), "/portable"]

    if config_path:
        cmd.extend(["/config", str(config_path)])

    if headless:
        # Use Xvfb for headless Wine display
        cmd = ["xvfb-run", "-a", "wine", str(mt5_exe), "/portable"]
        if config_path:
            cmd.extend(["/config", str(config_path)])

    logger.info("starting_mt5", cmd=" ".join(cmd))

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        logger.info("mt5_started", pid=process.pid)
        return process
    except FileNotFoundError:
        logger.error("wine_not_found")
        return None
    except Exception as exc:
        logger.error("mt5_start_failed", error=str(exc))
        return None


def test_connection(
    host: str = "127.0.0.1",
    port: int = RPYC_PORT,
    timeout: float = 5.0,
) -> bool:
    """Test RPyC connection to MT5 bridge.

    Returns True if connection is successful.
    """
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)

    try:
        sock.connect((host, port))
        logger.info("rpyc_connection_ok", host=host, port=port)
        return True
    except socket.timeout:
        logger.warning("rpyc_connection_timeout", host=host, port=port)
        return False
    except ConnectionRefusedError:
        logger.warning("rpyc_connection_refused", host=host, port=port)
        return False
    finally:
        sock.close()


def check_mt5_running() -> dict[str, Any]:
    """Check if MT5 is running under Wine."""
    import os

    result = {"running": False, "pid": None, "rpyc_listening": False}

    # Check for wineserver
    try:
        ps = subprocess.run(
            ["pgrep", "-a", "wineserver"],
            capture_output=True, text=True, timeout=5,
        )
        if ps.returncode == 0:
            result["running"] = True
    except Exception:
        pass

    # Check RPyC port
    result["rpyc_listening"] = test_connection(timeout=2.0)

    return result


async def full_connection_test() -> str:
    """Run a full connection test and return status string."""
    lines = ["MT5 Connection Test:", ""]

    # 1. Check Wine
    try:
        wine_ver = subprocess.run(
            ["wine", "--version"], capture_output=True, text=True, timeout=5,
        )
        lines.append(f"  ✅ Wine: {wine_ver.stdout.strip()}")
    except Exception:
        lines.append("  ❌ Wine not found")

    # 2. Check MT5 binary
    if WINE_MT5_PATH.exists():
        lines.append(f"  ✅ MT5 binary: {WINE_MT5_PATH}")
    else:
        lines.append(f"  ❌ MT5 binary not found: {WINE_MT5_PATH}")

    # 3. Check if running
    status = check_mt5_running()
    if status["running"]:
        lines.append("  ✅ MT5 process running")
    else:
        lines.append("  ⚠️  MT5 process not running")

    if status["rpyc_listening"]:
        lines.append(f"  ✅ RPyC bridge listening on port {RPYC_PORT}")
    else:
        lines.append(f"  ❌ RPyC bridge not listening on port {RPYC_PORT}")

    return "\n".join(lines)
