"""MT5 startup and connection test scripts for Wine on Linux.

Usage:
    python -m noema.scripts.start_mt5          # Start MT5 under Wine
    python -m noema.scripts.test_connection    # Test RPyC bridge connection
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
        # MT5 requires /config:path format (colon, not space).
        # Under Wine, convert Unix path to Windows Z:\ path for MT5.
        win_path = _unix_to_wine_path(str(config_path))
        cmd.append(f"/config:{win_path}")

    if headless:
        # Use Xvfb for headless Wine display
        cmd = ["xvfb-run", "-a", "wine", str(mt5_exe), "/portable"]
        if config_path:
            win_path = _unix_to_wine_path(str(config_path))
            cmd.append(f"/config:{win_path}")

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


def _unix_to_wine_path(unix_path: str) -> str:
    """Convert a Unix path to a Wine-compatible Windows path.

    Wine maps the Unix filesystem root (/) to the Z: drive.
    Example: /home/user/.noema/mt5-config.ini → Z:\\home\\user\\.noema\\mt5-config.ini
    """
    # Use winepath if available (most accurate)
    try:
        result = subprocess.run(
            ["winepath", "-w", unix_path],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    # Fallback: manual conversion
    return "Z:" + unix_path.replace("/", "\\")


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

    # 3. Check mt5linux package
    try:
        import mt5linux
        lines.append(f"  ✅ mt5linux: {mt5linux.__version__ if hasattr(mt5linux, '__version__') else 'installed'}")
    except ImportError:
        lines.append("  ❌ mt5linux not installed — run: pip install mt5linux")

    # 4. Check mt5linux EA file in MT5 Experts dir
    ea_path = _find_mt5linux_ea()
    if ea_path and ea_path.exists():
        lines.append(f"  ✅ mt5linux EA: {ea_path}")
    else:
        lines.append("  ❌ mt5linux EA not in MT5 Experts dir")
        lines.append("     → Run: noema setup-mt5-ea  (or copy mt5linux.ex5 manually)")

    # 5. Check if running
    status = check_mt5_running()
    if status["running"]:
        lines.append("  ✅ MT5 process running")
    else:
        lines.append("  ⚠️  MT5 process not running")

    if status["rpyc_listening"]:
        lines.append(f"  ✅ RPyC bridge listening on port {RPYC_PORT}")
    else:
        lines.append(f"  ❌ RPyC bridge not listening on port {RPYC_PORT}")
        lines.append("     → Make sure the mt5linux EA is attached to a chart in MT5")

    return "\n".join(lines)


def _find_mt5linux_ea() -> Path | None:
    """Find the mt5linux Expert Advisor file (.ex5) in the MT5 Experts directory."""
    experts_dir = Path.home() / ".wine/drive_c/Program Files/MetaTrader 5/MQL5/Experts"
    candidates = [
        experts_dir / "mt5linux.ex5",
        experts_dir / "mt5linux" / "mt5linux.ex5",
    ]
    for c in candidates:
        if c.exists():
            return c
    return experts_dir / "mt5linux.ex5"  # return expected path even if missing


def setup_mt5linux_ea() -> bool:
    """Copy the mt5linux Expert Advisor file into MT5's Experts directory.

    The mt5linux Python package includes an .ex5 Expert Advisor that must
    run inside MT5 to expose the RPyC server on port 18812. Without this EA,
    MT5 will start but the bridge port will never open.

    Returns True if the EA was copied successfully or already present.
    """
    experts_dir = Path.home() / ".wine/drive_c/Program Files/MetaTrader 5/MQL5/Experts"
    target = experts_dir / "mt5linux.ex5"

    # Already present?
    if target.exists():
        logger.info("mt5linux_ea_already_present", path=str(target))
        return True

    # Find the EA file in the mt5linux Python package
    ea_source = _locate_mt5linux_ea_in_package()
    if ea_source is None:
        logger.error(
            "mt5linux_ea_not_found_in_package",
            hint=(
                "The mt5linux.ex5 file was not found in the Python package.\n"
                "Download it from: https://github.com/lucas-campagna/mt5linux/releases\n"
                "Then copy it to: " + str(target)
            ),
        )
        return False

    # Ensure Experts directory exists
    experts_dir.mkdir(parents=True, exist_ok=True)

    # Copy the file
    import shutil
    shutil.copy2(ea_source, target)
    logger.info("mt5linux_ea_copied", source=str(ea_source), target=str(target))
    return True


def _locate_mt5linux_ea_in_package() -> Path | None:
    """Locate mt5linux.ex5 within the installed Python package."""
    try:
        import mt5linux
        pkg_dir = Path(mt5linux.__file__).parent
    except ImportError:
        return None

    # Search common locations within the package
    candidates = [
        pkg_dir / "mt5linux.ex5",
        pkg_dir / "server" / "mt5linux.ex5",
        pkg_dir / "expert" / "mt5linux.ex5",
        pkg_dir / "ea" / "mt5linux.ex5",
        pkg_dir / "Experts" / "mt5linux.ex5",
    ]
    for c in candidates:
        if c.exists():
            return c

    # Broader search within the package directory
    for f in pkg_dir.rglob("mt5linux.ex5"):
        return f
    for f in pkg_dir.rglob("*.ex5"):
        return f

    return None
