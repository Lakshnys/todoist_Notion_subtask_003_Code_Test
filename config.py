"""
Configuration management for Todoist-Notion sync engine.
Uses Pydantic for validation and type safety.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Optional
import logging


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # ── Todoist ────────────────────────────────────────────────
    todoist_api_token: str
    todoist_project_id: str

    # ── Notion ─────────────────────────────────────────────────
    notion_api_token: str
    notion_database_id: str
    notion_timezone_offset: int = Field(
        default=0,
        description="Notion workspace UTC offset in hours (e.g., 4 for UTC+4)"
    )

    # ── Sync ───────────────────────────────────────────────────
    sync_interval_seconds: int = Field(
        default=900,          # 15 minutes (confirmed)
        description="Sync interval in seconds (default: 900 = 15 minutes)"
    )
    log_level: str = "INFO"
    dry_run: bool = False

    # ── Backup: Pre-sync state backup ──────────────────────────
    backup_pre_sync_enabled: bool = Field(
        default=True,
        description="Backup sync_state.json before every sync"
    )
    backup_pre_sync_keep: int = Field(
        default=5,
        description="Number of pre-sync backups to keep"
    )

    # ── Backup: Full snapshot (every 3 days) ───────────────────
    backup_full_enabled: bool = Field(
        default=True,
        description="Enable scheduled full snapshots"
    )
    backup_full_every_days: int = Field(
        default=3,
        description="Full snapshot every N days (confirmed: 3)"
    )
    backup_full_keep: int = Field(
        default=4,
        description="Number of full snapshots to keep (covers 12 days)"
    )

    # ── Backup: Weekly archive ─────────────────────────────────
    backup_weekly_enabled: bool = Field(
        default=True,
        description="Enable weekly archive snapshots"
    )
    backup_weekly_keep: int = Field(
        default=4,
        description="Number of weekly archives to keep (covers 1 month)"
    )

    # ── Backup: Storage ────────────────────────────────────────
    backup_dir: str = Field(
        default="backups",
        description="Root directory for all backups"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )

    def configure_logging(self) -> None:
        """Configure logging based on settings."""
        logging.basicConfig(
            level=getattr(logging, self.log_level.upper()),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )


# Global settings instance
settings = Settings()
