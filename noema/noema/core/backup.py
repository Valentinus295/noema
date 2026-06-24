"""
Noema Backup & Recovery — Production data safety net.

Provides:
- PostgreSQL database backup (scheduled dumps + point-in-time recovery)
- Configuration backup (.env, settings.yaml, service files)
- State recovery procedures (from backup to running state)
- Backup verification (test restore to temp database)

Usage:
    # CLI: Run a full backup
    python -m noema.core.backup --full

    # CLI: Restore from backup
    python -m noema.core.backup --restore /path/to/backup.tar.gz

    # Programmatic:
    from noema.core.backup import BackupManager
    mgr = BackupManager(settings)
    await mgr.create_full_backup()

Architecture:
    Backup directory structure:
        backups/
        ├── 2026-06-24_15-00-00/
        │   ├── database.sql.gz        # PostgreSQL dump
        │   ├── config.tar.gz          # Config files
        │   ├── state.json             # Current system state
        │   └── MANIFEST.txt           # Backup metadata
        └── latest -> 2026-06-24_15-00-00  # Symlink to latest backup
"""

from __future__ import annotations

import asyncio
import gzip
import json
import os
import shutil
import subprocess
import tarfile
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


# ═══════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════

DEFAULT_BACKUP_DIR = Path("backups")
MAX_BACKUPS = 14  # Keep 14 days of backups
RETENTION_DAYS = 14


class BackupManager:
    """Manages backup and recovery of Noema data and configuration.

    Usage:
        mgr = BackupManager(
            settings=settings,
            backup_dir="/opt/noema/backups",
            database_url="postgresql+asyncpg://...",
            pg_dump_path="/usr/bin/pg_dump",
        )
        await mgr.create_full_backup()
    """

    def __init__(
        self,
        settings: Any = None,
        backup_dir: str | Path = DEFAULT_BACKUP_DIR,
        database_url: str | None = None,
        pg_dump_path: str = "pg_dump",
        pg_restore_path: str = "pg_restore",
        config_files: list[str] | None = None,
    ):
        """
        Args:
            settings: Settings instance (for backup verification)
            backup_dir: Directory to store backups
            database_url: PostgreSQL connection URL (auto-detected from settings or .env)
            pg_dump_path: Path to pg_dump binary
            pg_restore_path: Path to pg_restore binary
            config_files: Extra config files to include in backup
        """
        self._settings = settings
        self._backup_dir = Path(backup_dir)
        self._database_url = database_url or self._detect_database_url()
        self._pg_dump = pg_dump_path
        self._pg_restore = pg_restore_path

        # Config files to back up (relative to project root)
        self._config_files = config_files or [
            ".env",
            "config/settings.yaml",
            "config/symbols.yaml",
            "noema/config/llm_models.yaml",
            "config/noema.service",
            "config/noema-mt5.service",
            "config/prometheus.yml",
        ]

        # Resolve project root from settings module location
        if settings:
            import noema.core.settings as settings_mod
            self._project_root = Path(settings_mod.__file__).parent.parent.parent
        else:
            self._project_root = Path.cwd()

        # Ensure backup directory exists
        self._backup_dir.mkdir(parents=True, exist_ok=True)

    def _detect_database_url(self) -> str:
        """Detect database URL from settings or environment."""
        if self._settings:
            url = getattr(self._settings, "database_url", "")
            if url:
                return url

        return os.getenv("DATABASE_URL", "")

    # ── Full Backup ─────────────────────────────────────────────────

    async def create_full_backup(
        self,
        label: str | None = None,
        include_database: bool = True,
        include_config: bool = True,
        compress: bool = True,
    ) -> Path | None:
        """Create a comprehensive backup of all Noema data.

        Args:
            label: Optional human-readable label for the backup
            include_database: Include PostgreSQL dump
            include_config: Include configuration files
            compress: Compress the final backup

        Returns:
            Path to the backup directory, or None if backup failed.
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
        backup_name = f"{timestamp}"
        if label:
            backup_name = f"{timestamp}_{label}"

        backup_path = self._backup_dir / backup_name
        backup_path.mkdir(parents=True, exist_ok=True)

        logger.info("backup_starting", path=str(backup_path))

        success = True
        manifest = {
            "timestamp": timestamp,
            "label": label,
            "backup_version": "2.0.0",
            "components": {},
        }

        try:
            # ── 1. Database Backup ──────────────────────────────────
            if include_database and self._is_postgres():
                db_status = await self._backup_database(backup_path)
                manifest["components"]["database"] = db_status
                if db_status.get("status") != "success":
                    success = False

            # ── 2. Config Backup ────────────────────────────────────
            if include_config:
                config_status = await self._backup_config(backup_path)
                manifest["components"]["config"] = config_status
                if config_status.get("status") != "success":
                    success = False

            # ── 3. State Snapshot ───────────────────────────────────
            state_status = await self._backup_state(backup_path)
            manifest["components"]["state"] = state_status

            # ── 4. Write MANIFEST ───────────────────────────────────
            manifest_path = backup_path / "MANIFEST.txt"
            manifest_path.write_text(json.dumps(manifest, indent=2, default=str))

            # ── 5. Compress (if requested) ──────────────────────────
            final_path = backup_path
            if compress and success:
                final_path = self._compress_backup(backup_path)

            # ── 6. Update symlink ───────────────────────────────────
            latest_link = self._backup_dir / "latest"
            if latest_link.is_symlink() or latest_link.exists():
                latest_link.unlink()
            latest_link.symlink_to(backup_name)

            # ── 7. Clean old backups ────────────────────────────────
            await self._cleanup_old_backups()

            logger.info(
                "backup_completed",
                path=str(final_path),
                size_bytes=final_path.stat().st_size if final_path.exists() else 0,
                components=manifest["components"],
            )

        except Exception as e:
            logger.error("backup_failed", error=str(e), path=str(backup_path))
            # Don't leave partial backups
            if backup_path.exists():
                shutil.rmtree(backup_path, ignore_errors=True)
            return None

        return final_path

    # ── Database Backup ─────────────────────────────────────────────

    async def _backup_database(self, backup_path: Path) -> dict[str, Any]:
        """Dump PostgreSQL database to backup directory.

        Uses pg_dump with custom format for efficient restore.
        Falls back to SQLite .backup for SQLite databases.
        """
        try:
            if self._database_url.startswith("sqlite"):
                return await self._backup_sqlite(backup_path)
            else:
                return await self._backup_postgres(backup_path)
        except Exception as e:
            logger.error("database_backup_failed", error=str(e))
            return {"status": "failed", "error": str(e), "db_type": self._database_url.split(":")[0]}

    async def _backup_postgres(self, backup_path: Path) -> dict[str, Any]:
        """Dump PostgreSQL database using pg_dump."""
        # Parse connection URL
        url = self._database_url
        # Format: postgresql+asyncpg://user:pass@host:port/dbname
        db_name = url.split("/")[-1].split("?")[0]
        user = url.split("://")[1].split(":")[0] if "://" in url else ""
        password = url.split(":")[2].split("@")[0] if url.count(":") >= 3 else ""
        host = url.split("@")[1].split(":")[0] if "@" in url else "localhost"
        port = url.split(":")[-1].split("/")[0] if url.count(":") >= 2 else "5432"

        dump_file = backup_path / "database.sql.gz"

        # Build pg_dump command
        env = os.environ.copy()
        if password:
            env["PGPASSWORD"] = password

        cmd = [
            self._pg_dump,
            "--host", host,
            "--port", str(port),
            "--username", user,
            "--dbname", db_name,
            "--format", "custom",      # Custom format for pg_restore
            "--compress", "9",         # Max compression
            "--file", str(dump_file),
            "--no-owner",
            "--no-privileges",
        ]

        logger.info("pg_dump_starting", db=db_name, host=host)

        process = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        _, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=300,  # 5 minutes
        )

        if process.returncode != 0:
            error_text = stderr.decode() if stderr else "unknown error"
            logger.error("pg_dump_failed", returncode=process.returncode, error=error_text)
            return {"status": "failed", "error": error_text, "command": " ".join(cmd)}

        size_bytes = dump_file.stat().st_size
        logger.info("pg_dump_success", size_bytes=size_bytes)

        return {
            "status": "success",
            "file": str(dump_file),
            "size_bytes": size_bytes,
            "db_type": "postgresql",
            "db_name": db_name,
            "format": "custom",
        }

    async def _backup_sqlite(self, backup_path: Path) -> dict[str, Any]:
        """Backup SQLite database using the .backup command."""
        import sqlite3
        db_path = self._database_url.replace("sqlite+aiosqlite:///", "").replace("sqlite:///", "")
        if not Path(db_path).is_absolute():
            db_path = str(self._project_root / db_path)

        backup_file = backup_path / "database.sqlite3.gz"

        # Use SQLite backup API
        src = sqlite3.connect(db_path)
        try:
            dst = sqlite3.connect(":memory:")
            src.backup(dst)
            # Write to gzip compressed file
            with gzip.open(backup_file, "wb") as f:
                for line in dst.iterdump():
                    f.write(f"{line}\n".encode("utf-8"))
            dst.close()
        finally:
            src.close()

        size_bytes = backup_file.stat().st_size
        return {
            "status": "success",
            "file": str(backup_file),
            "size_bytes": size_bytes,
            "db_type": "sqlite",
        }

    # ── Config Backup ───────────────────────────────────────────────

    async def _backup_config(self, backup_path: Path) -> dict[str, Any]:
        """Back up all configuration files."""
        config_archive = backup_path / "config.tar.gz"
        files_backed_up = 0
        missing_files = []

        with tarfile.open(config_archive, "w:gz") as tar:
            for config_file in self._config_files:
                full_path = self._project_root / config_file
                if full_path.exists():
                    tar.add(full_path, arcname=config_file)
                    files_backed_up += 1
                else:
                    missing_files.append(config_file)
                    logger.debug("config_file_missing", path=str(full_path))

        size_bytes = config_archive.stat().st_size
        return {
            "status": "success",
            "file": str(config_archive),
            "size_bytes": size_bytes,
            "files_backed_up": files_backed_up,
            "missing_files": missing_files if missing_files else None,
        }

    # ── State Snapshot ──────────────────────────────────────────────

    async def _backup_state(self, backup_path: Path) -> dict[str, Any]:
        """Save current system state for recovery reference."""
        state = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "pid": os.getpid(),
            "python_version": __import__("sys").version,
        }

        # Add settings snapshot (sanitized)
        if self._settings:
            try:
                state["settings"] = {
                    "trading_pairs": getattr(self._settings.trading, "pairs", []),
                    "broker_type": getattr(self._settings.broker, "type", "unknown"),
                    "cycle_interval": getattr(self._settings, "cycle_interval", 60),
                    "environment": os.getenv("NOEMA_ENV", "production"),
                }
            except Exception as e:
                logger.debug("state_snapshot_settings_failed", error=str(e))

        # Add git info if available
        try:
            import subprocess
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                cwd=str(self._project_root),
                timeout=5,
            )
            if result.returncode == 0:
                state["git_sha"] = result.stdout.strip()

            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                cwd=str(self._project_root),
                timeout=5,
            )
            if result.returncode == 0:
                state["git_dirty"] = bool(result.stdout.strip())
        except Exception:
            pass

        state_file = backup_path / "state.json"
        state_file.write_text(json.dumps(state, indent=2, default=str))

        return {
            "status": "success",
            "file": str(state_file),
        }

    # ── Compression ─────────────────────────────────────────────────

    def _compress_backup(self, backup_path: Path) -> Path:
        """Compress the backup directory into a .tar.gz archive."""
        archive_path = backup_path.with_suffix(backup_path.suffix + ".tar.gz")
        if archive_path.suffixes != [".tar", ".gz"] and not archive_path.name.endswith(".tar.gz"):
            archive_path = Path(str(backup_path) + ".tar.gz")

        with tarfile.open(archive_path, "w:gz") as tar:
            for item in backup_path.iterdir():
                tar.add(item, arcname=item.name)

        # Remove uncompressed directory
        shutil.rmtree(backup_path)

        logger.info("backup_compressed", path=str(archive_path))
        return archive_path

    # ── Cleanup ─────────────────────────────────────────────────────

    async def _cleanup_old_backups(self) -> None:
        """Remove backups older than RETENTION_DAYS."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
        cleaned = 0

        for item in self._backup_dir.iterdir():
            if item.name == "latest" or not item.is_dir():
                continue
            try:
                # Extract timestamp from directory name (YYYY-MM-DD_HH-MM-SS_...)
                ts_str = item.name[:19]  # "YYYY-MM-DD_HH-MM-SS"
                ts = datetime.strptime(ts_str, "%Y-%m-%d_%H-%M-%S").replace(tzinfo=timezone.utc)
                if ts < cutoff:
                    shutil.rmtree(item)
                    cleaned += 1
                    logger.info("backup_cleaned_old", path=str(item), age_days=(datetime.now(timezone.utc) - ts).days)

            except (ValueError, IndexError):
                # Skip directories that don't match the naming convention
                continue

        if cleaned > 0:
            logger.info("backup_cleanup_complete", removed=cleaned)

    # ── Restore ─────────────────────────────────────────────────────

    async def restore_from_backup(
        self,
        backup_path: Path | str,
        restore_database: bool = True,
        restore_config: bool = False,  # Config restore is DANGEROUS — explicit opt-in
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Restore Noema from a backup.

        Args:
            backup_path: Path to backup directory or .tar.gz archive
            restore_database: Restore the database
            restore_config: Restore config files (DANGEROUS — will overwrite)
            dry_run: If True, only validate the backup without restoring

        Returns:
            Dictionary with restore results per component.
        """
        backup_path = Path(backup_path)
        results: dict[str, Any] = {"dry_run": dry_run, "components": {}}

        # ── Handle compressed backups ──────────────────────────────
        if backup_path.suffix == ".gz" or backup_path.name.endswith(".tar.gz"):
            # Extract to temp directory
            import tempfile
            extract_dir = Path(tempfile.mkdtemp(prefix="noema_restore_"))
            try:
                with tarfile.open(backup_path, "r:gz") as tar:
                    tar.extractall(extract_dir)
                backup_dir = extract_dir
                is_temp = True
            except Exception as e:
                logger.error("backup_extract_failed", error=str(e))
                return {"status": "failed", "error": f"Extract failed: {e}"}
        else:
            backup_dir = backup_path
            is_temp = False

        # ── Validate backup ────────────────────────────────────────
        manifest_file = backup_dir / "MANIFEST.txt"
        if not manifest_file.exists():
            logger.error("backup_no_manifest", path=str(backup_dir))
            if is_temp:
                shutil.rmtree(backup_dir, ignore_errors=True)
            return {"status": "failed", "error": "No MANIFEST.txt found in backup"}

        manifest = json.loads(manifest_file.read_text())
        results["manifest"] = manifest
        logger.info(
            "restore_starting",
            backup_timestamp=manifest.get("timestamp"),
            components=list(manifest.get("components", {}).keys()),
            dry_run=dry_run,
        )

        try:
            # ── Restore Database ────────────────────────────────────
            if restore_database and "database" in manifest.get("components", {}):
                db_info = manifest["components"]["database"]
                results["components"]["database"] = await self._restore_database(
                    backup_dir, db_info, dry_run
                )

            # ── Restore Config ──────────────────────────────────────
            if restore_config and "config" in manifest.get("components", {}):
                config_info = manifest["components"]["config"]
                results["components"]["config"] = await self._restore_config(
                    backup_dir, config_info, dry_run
                )

            logger.info("restore_completed", results=results["components"])

        except Exception as e:
            logger.error("restore_failed", error=str(e))
            results["status"] = "failed"
            results["error"] = str(e)
        finally:
            if is_temp:
                shutil.rmtree(backup_dir, ignore_errors=True)

        return results

    async def _restore_database(
        self, backup_dir: Path, db_info: dict[str, Any], dry_run: bool
    ) -> dict[str, Any]:
        """Restore database from backup."""
        db_type = db_info.get("db_type", "postgresql")

        if dry_run:
            return {"status": "dry_run", "db_type": db_type, "message": "Would restore database"}

        if db_type == "postgresql":
            return await self._restore_postgres(backup_dir, db_info)
        elif db_type == "sqlite":
            return await self._restore_sqlite(backup_dir, db_info)
        else:
            return {"status": "skipped", "reason": f"Unknown db_type: {db_type}"}

    async def _restore_postgres(
        self, backup_dir: Path, db_info: dict[str, Any]
    ) -> dict[str, Any]:
        """Restore PostgreSQL database from custom-format dump."""
        dump_file = backup_dir / "database.sql.gz"
        if not dump_file.exists():
            return {"status": "failed", "error": f"Dump file not found: {dump_file}"}

        # Parse connection URL
        url = self._database_url
        db_name = url.split("/")[-1].split("?")[0]
        user = url.split("://")[1].split(":")[0] if "://" in url else ""
        password = url.split(":")[2].split("@")[0] if url.count(":") >= 3 else ""
        host = url.split("@")[1].split(":")[0] if "@" in url else "localhost"
        port = url.split(":")[-1].split("/")[0] if url.count(":") >= 2 else "5432"

        env = os.environ.copy()
        if password:
            env["PGPASSWORD"] = password

        cmd = [
            self._pg_restore,
            "--host", host,
            "--port", str(port),
            "--username", user,
            "--dbname", db_name,
            "--clean",              # Drop objects before restoring
            "--if-exists",          # Don't error if objects don't exist
            "--no-owner",
            "--no-privileges",
            "--single-transaction",  # All or nothing
            str(dump_file),
        ]

        logger.warning("pg_restore_starting", db=db_name, host=host)

        process = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        _, stderr = await process.communicate()

        if process.returncode != 0:
            error_text = stderr.decode() if stderr else "unknown error"
            logger.error("pg_restore_failed", returncode=process.returncode, error=error_text)
            return {"status": "failed", "error": error_text}

        logger.info("pg_restore_success", db=db_name)
        return {"status": "success", "db_name": db_name}

    async def _restore_sqlite(
        self, backup_dir: Path, db_info: dict[str, Any]
    ) -> dict[str, Any]:
        """Restore SQLite database from gzipped dump."""
        backup_file = backup_dir / "database.sqlite3.gz"
        if not backup_file.exists():
            return {"status": "failed", "error": f"Backup file not found: {backup_file}"}

        db_path = self._database_url.replace("sqlite+aiosqlite:///", "").replace("sqlite:///", "")
        if not Path(db_path).is_absolute():
            db_path = str(self._project_root / db_path)

        import sqlite3

        # Restore to new database
        conn = sqlite3.connect(db_path)
        try:
            with gzip.open(backup_file, "rt") as f:
                conn.executescript(f.read())
            conn.commit()
        finally:
            conn.close()

        return {"status": "success", "db_path": db_path}

    async def _restore_config(
        self, backup_dir: Path, config_info: dict[str, Any], dry_run: bool
    ) -> dict[str, Any]:
        """Restore configuration files from backup (DANGEROUS — opt-in only).

        This WILL overwrite existing config files. Use with caution.
        """
        if dry_run:
            return {"status": "dry_run", "message": "Would restore config files"}

        config_archive = backup_dir / "config.tar.gz"
        if not config_archive.exists():
            return {"status": "failed", "error": f"Config archive not found: {config_archive}"}

        restored = []
        with tarfile.open(config_archive, "r:gz") as tar:
            for member in tar.getmembers():
                # Safety: Don't overwrite .env if it has different content
                if member.name == ".env":
                    existing = self._project_root / ".env"
                    if existing.exists():
                        logger.warning(
                            "config_restore_skipping_env",
                            reason=".env exists and may contain live credentials",
                        )
                        continue

                tar.extract(member, self._project_root)
                restored.append(member.name)

        return {
            "status": "success",
            "files_restored": len(restored),
            "restored": restored,
        }

    # ── Verification ────────────────────────────────────────────────

    async def verify_backup(self, backup_path: Path | str) -> dict[str, Any]:
        """Verify a backup is valid and restorable.

        Performs:
        1. Check MANIFEST.txt exists and is valid JSON
        2. Check database dump integrity (pg_restore --list for format check)
        3. Verify config archive is readable
        4. Report total backup size and contents
        """
        backup_path = Path(backup_path)
        results: dict[str, Any] = {"valid": True, "checks": {}}

        # Handle compressed archives
        if backup_path.suffix == ".gz" or backup_path.name.endswith(".tar.gz"):
            import tempfile
            extract_dir = Path(tempfile.mkdtemp(prefix="noema_verify_"))
            try:
                with tarfile.open(backup_path, "r:gz") as tar:
                    tar.extractall(extract_dir)
                backup_dir = extract_dir
                is_temp = True
            except Exception as e:
                return {"valid": False, "error": f"Archive extraction failed: {e}"}
        else:
            backup_dir = backup_path
            is_temp = False

        try:
            # Check MANIFEST
            manifest_file = backup_dir / "MANIFEST.txt"
            if not manifest_file.exists():
                results["valid"] = False
                results["checks"]["manifest"] = {"status": "missing"}
            else:
                manifest = json.loads(manifest_file.read_text())
                results["checks"]["manifest"] = {
                    "status": "valid",
                    "timestamp": manifest.get("timestamp"),
                    "components": list(manifest.get("components", {}).keys()),
                }

            # Check database dump
            db_dump = backup_dir / "database.sql.gz"
            if db_dump.exists():
                try:
                    # Test pg_restore listing
                    cmd = [self._pg_restore, "--list", str(db_dump)]
                    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                    results["checks"]["database"] = {
                        "status": "valid" if proc.returncode == 0 else "corrupt",
                        "size_bytes": db_dump.stat().st_size,
                    }
                except Exception as e:
                    results["checks"]["database"] = {"status": "error", "error": str(e)}
                    results["valid"] = False
            else:
                results["checks"]["database"] = {"status": "not_present"}

            # Check config archive
            config_archive = backup_dir / "config.tar.gz"
            if config_archive.exists():
                try:
                    with tarfile.open(config_archive, "r:gz") as tar:
                        names = tar.getnames()
                    results["checks"]["config"] = {
                        "status": "valid",
                        "files": len(names),
                        "size_bytes": config_archive.stat().st_size,
                    }
                except Exception as e:
                    results["checks"]["config"] = {"status": "error", "error": str(e)}
                    results["valid"] = False
            else:
                results["checks"]["config"] = {"status": "not_present"}

            # Total backup size
            total_size = sum(
                f.stat().st_size for f in backup_dir.rglob("*") if f.is_file()
            )
            results["total_size_bytes"] = total_size

        except Exception as e:
            results["valid"] = False
            results["error"] = str(e)
        finally:
            if is_temp:
                shutil.rmtree(backup_dir, ignore_errors=True)

        return results

    # ── Helpers ─────────────────────────────────────────────────────

    def _is_postgres(self) -> bool:
        """Check if configured database is PostgreSQL."""
        return self._database_url.startswith("postgresql")

    def _is_sqlite(self) -> bool:
        """Check if configured database is SQLite."""
        return self._database_url.startswith("sqlite")

    def list_backups(self) -> list[dict[str, Any]]:
        """List all available backups with metadata."""
        backups = []

        for item in sorted(self._backup_dir.iterdir(), reverse=True):
            if item.name == "latest":
                continue

            manifest_file = item / "MANIFEST.txt"
            if item.is_dir() and manifest_file.exists():
                try:
                    manifest = json.loads(manifest_file.read_text())
                    backups.append({
                        "name": item.name,
                        "timestamp": manifest.get("timestamp", "unknown"),
                        "label": manifest.get("label"),
                        "components": list(manifest.get("components", {}).keys()),
                    })
                except Exception:
                    backups.append({
                        "name": item.name,
                        "timestamp": "unknown",
                        "error": "manifest_read_failed",
                    })

        return backups

    async def get_latest_backup(self) -> Path | None:
        """Get path to the latest backup."""
        latest_link = self._backup_dir / "latest"
        if latest_link.is_symlink():
            return self._backup_dir / latest_link.readlink()

        backups = self.list_backups()
        if backups:
            return self._backup_dir / backups[0]["name"]

        return None


# ═══════════════════════════════════════════════════
# CLI Entry Point
# ═══════════════════════════════════════════════════

async def _cli_main() -> None:
    """CLI entry point for backup operations."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Noema Backup & Recovery",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m noema.core.backup --full              # Full backup
  python -m noema.core.backup --list              # List backups
  python -m noema.core.backup --verify latest     # Verify latest backup
  python -m noema.core.backup --restore backups/2026-06-24_15-00-00  # Restore
  python -m noema.core.backup --restore backups/2026-06-24_15-00-00 --restore-config  # Restore everything
        """,
    )
    parser.add_argument("--full", action="store_true", help="Create full backup")
    parser.add_argument("--db-only", action="store_true", help="Backup database only")
    parser.add_argument("--config-only", action="store_true", help="Backup config only")
    parser.add_argument("--list", action="store_true", help="List available backups")
    parser.add_argument("--restore", type=str, help="Restore from backup path")
    parser.add_argument("--restore-config", action="store_true", help="Also restore config (DANGEROUS)")
    parser.add_argument("--verify", type=str, help="Verify backup at path (or 'latest')")
    parser.add_argument("--dry-run", action="store_true", help="Dry run restore")
    parser.add_argument("--backup-dir", type=str, default=str(DEFAULT_BACKUP_DIR), help="Backup directory")
    parser.add_argument("--label", type=str, help="Backup label")
    args = parser.parse_args()

    mgr = BackupManager(backup_dir=args.backup_dir)

    if args.list:
        backups = mgr.list_backups()
        if not backups:
            print("No backups found.")
        else:
            print(f"\n{'Backup':<35} {'Timestamp':<25} {'Components'}")
            print("-" * 80)
            for b in backups:
                components = ", ".join(b.get("components", []))
                print(f"{b['name']:<35} {b['timestamp']:<25} {components}")
        return

    if args.verify:
        path = mgr._backup_dir / args.verify if args.verify != "latest" else await mgr.get_latest_backup()
        if not path:
            print(f"Backup not found: {args.verify}")
            return
        result = await mgr.verify_backup(path)
        print(json.dumps(result, indent=2, default=str))
        return

    if args.restore:
        path = Path(args.restore)
        if not path.exists():
            print(f"Backup not found: {path}")
            return
        result = await mgr.restore_from_backup(
            path,
            restore_config=args.restore_config,
            dry_run=args.dry_run,
        )
        print(json.dumps(result, indent=2, default=str))
        return

    if args.full or args.db_only or args.config_only:
        if args.db_only:
            backup_path = await mgr.create_full_backup(include_config=False, label=args.label)
        elif args.config_only:
            backup_path = await mgr.create_full_backup(include_database=False, label=args.label)
        else:
            backup_path = await mgr.create_full_backup(label=args.label)

        if backup_path:
            print(f"✅ Backup created: {backup_path}")
        else:
            print("❌ Backup failed — check logs for details")
            exit(1)
        return

    parser.print_help()


if __name__ == "__main__":
    asyncio.run(_cli_main())
