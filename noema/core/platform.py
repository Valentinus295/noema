"""Platform detection and auto-configuration for Noema.

Detects the operating system and configures broker, paths, and
dependencies automatically. No manual --broker flags needed.

Usage:
    from noema.core.platform import detect_platform, get_broker_class

    platform = detect_platform()
    broker_cls = get_broker_class()

Key facts:
    - Linux (Pop!_OS, Ubuntu, etc.): MT5 runs under Wine → mt5linux bridge
    - Windows: MT5 runs natively → MetaTrader5 Python package
    - macOS: Paper trading only (MT5 doesn't run on macOS)
    - Docker/CI: Auto-detects and falls back to PaperBroker
"""

from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class PlatformInfo:
    """Detected platform configuration."""
    system: str           # "linux", "windows", "darwin"
    machine: str          # "x86_64", "aarch64", etc.
    is_wsl: bool          # Windows Subsystem for Linux
    is_docker: bool       # Running inside Docker container
    is_ci: bool           # CI environment (GitHub Actions, etc.)
    has_wine: bool        # Wine is installed
    has_mt5: bool         # MT5 terminal found
    has_display: bool     # GUI display available (X11/Wayland)
    python_version: str
    recommended_broker: str  # "mt5_linux", "mt5", "paper"


def detect_platform() -> PlatformInfo:
    """Detect the current platform and available capabilities.

    Returns a PlatformInfo dataclass with all detected settings.
    Call this once at startup to auto-configure everything.
    """
    system = platform.system().lower()
    machine = platform.machine().lower()

    # WSL detection
    is_wsl = False
    if system == "linux":
        try:
            with open("/proc/version") as f:
                is_wsl = "microsoft" in f.read().lower() or "wsl" in f.read().lower()
        except Exception:
            pass

    # Docker detection
    is_docker = os.path.exists("/.dockerenv") or "docker" in os.getenv("container", "").lower()

    # CI detection
    is_ci = bool(os.getenv("CI") or os.getenv("GITHUB_ACTIONS"))

    # Wine detection
    has_wine = False
    if system == "linux":
        has_wine = _check_command("wine")

    # MT5 detection
    has_mt5 = _detect_mt5(system, is_wsl)

    # Display detection
    has_display = bool(os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY"))

    # Recommended broker
    if system == "windows" or is_wsl:
        recommended_broker = "mt5"
    elif system == "linux" and has_wine and has_mt5:
        recommended_broker = "mt5_linux"
    elif system == "linux" and has_wine:
        recommended_broker = "mt5_linux"  # MT5 not found yet, but Wine is ready
    else:
        recommended_broker = "paper"

    return PlatformInfo(
        system=system,
        machine=machine,
        is_wsl=is_wsl,
        is_docker=is_docker,
        is_ci=is_ci,
        has_wine=has_wine,
        has_mt5=has_mt5,
        has_display=has_display,
        python_version=platform.python_version(),
        recommended_broker=recommended_broker,
    )


def get_broker_class(platform_info: PlatformInfo | None = None) -> type:
    """Return the appropriate broker class for this platform.

    Automatically selects:
        - MT5LinuxBroker on Linux (Wine + mt5linux)
        - MT5Broker on Windows / WSL
        - PaperBroker on macOS / Docker / CI / anywhere else

    Override with NOEMA_BROKER env var: paper, mt5, mt5_linux
    """
    # Manual override
    override = os.getenv("NOEMA_BROKER", "").lower()
    if override:
        return _broker_from_name(override)

    if platform_info is None:
        platform_info = detect_platform()

    return _broker_from_name(platform_info.recommended_broker)


def _broker_from_name(name: str) -> type:
    """Resolve broker name to class."""
    if name == "mt5_linux":
        from noema.broker.mt5_linux import MT5LinuxBroker
        return MT5LinuxBroker
    elif name == "mt5":
        from noema.broker.mt5 import MT5Broker
        return MT5Broker
    else:
        from noema.broker.paper import PaperBroker
        return PaperBroker


def get_mt5_path(platform_info: PlatformInfo | None = None) -> str | None:
    """Get the path to the MT5 terminal executable, if found.

    Returns None if MT5 is not installed.
    """
    if platform_info is None:
        platform_info = detect_platform()

    if platform_info.system == "windows" or platform_info.is_wsl:
        # Windows: check common install paths
        candidates = [
            Path("C:/Program Files/MetaTrader 5/terminal64.exe"),
            Path("C:/Program Files (x86)/MetaTrader 5/terminal64.exe"),
            Path.home() / "AppData/Roaming/MetaQuotes/Terminal/terminal64.exe",
        ]
    else:
        # Linux: Wine path
        candidates = [
            Path.home() / ".wine/drive_c/Program Files/MetaTrader 5/terminal64.exe",
            Path.home() / ".wine/drive_c/Program Files (x86)/MetaTrader 5/terminal64.exe",
        ]

    for path in candidates:
        if path.exists():
            return str(path)

    return None


def check_prerequisites() -> dict[str, bool]:
    """Check all prerequisites and return status dict.

    Used by setup.sh and the dashboard health check.
    """
    info = detect_platform()

    return {
        "python": True,
        "mt5_installed": info.has_mt5,
        "wine_installed": info.has_wine,
        "display_available": info.has_display,
        "docker_running": _check_docker(),
        "redis_available": _check_port("localhost", 6379),
        "postgres_available": _check_port("localhost", 5432),
        "platform": info.system,
        "recommended_broker": info.recommended_broker,
    }


# ── Internal Helpers ─────────────────────────────────────────────


def _check_command(cmd: str) -> bool:
    """Check if a command is available in PATH."""
    import shutil
    return shutil.which(cmd) is not None


def _detect_mt5(system: str, is_wsl: bool) -> bool:
    """Detect if MT5 is installed."""
    if system == "windows" or is_wsl:
        candidates = [
            Path("C:/Program Files/MetaTrader 5/terminal64.exe"),
            Path("C:/Program Files (x86)/MetaTrader 5/terminal64.exe"),
        ]
    elif system == "linux":
        candidates = [
            Path.home() / ".wine/drive_c/Program Files/MetaTrader 5/terminal64.exe",
            Path.home() / ".wine/drive_c/Program Files (x86)/MetaTrader 5/terminal64.exe",
        ]
    else:
        return False

    return any(p.exists() for p in candidates)


def _check_docker() -> bool:
    """Check if Docker daemon is running."""
    try:
        import subprocess
        result = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False


def _check_port(host: str, port: int, timeout: float = 1.0) -> bool:
    """Check if a TCP port is accepting connections."""
    import socket
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False
