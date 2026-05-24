"""
sync_state_manager.py
─────────────────────
Manages persistent local state for Todoist ↔ Notion sync.

ARCHITECTURE (confirmed):
  Local DB = source of truth
  → Compare timestamps → latest wins
  → Update local → push to both systems
  → Store sync timestamp

STATE FILE STRUCTURE (sync_state.json):
{
  "_metadata": {
    "last_sync_time":        "2026-04-23T10:00:00",
    "is_initial_sync_done":  true,
    "sync_count":            42,
    "schema_version":        "2.0"
  },
  "todoist_task_id": {
    "title":                 "Task title",
    "description":           "...",
    "priority":              2,
    "due_date":              "2026-02-23T14:30:00",
    "labels":                ["work"],
    "completed":             false,
    "parent_id":             null,
    "is_subtask":            false,
    "notion_page_id":        "307ceff6-...",
    "todoist_updated_at":    "2026-04-23T09:00:00",
    "notion_last_edited":    "2026-04-23T09:30:00",
    "winning_system":        "notion",
    "last_sync_time":        "2026-04-23T10:00:00"
  }
}
"""

import json
import logging
import shutil
from pathlib import Path
from typing import Dict, Optional, List, Tuple
from datetime import datetime
from models import Task

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "2.0"


class SyncStateManager:
    """
    Manages persistent local state for the sync engine.

    KEY BEHAVIOURS:
    - Stores global metadata (last_sync_time, is_initial_sync_done)
    - Stores per-task state including source timestamps
    - Detects changes using three-way merge
    - Resolves conflicts using LATEST TIMESTAMP WINS
    - Tracks parent-child relationships for subtasks
    """

    METADATA_KEY = "_metadata"

    def __init__(self, state_file: str = "sync_state.json"):
        self.state_file = Path(state_file)
        self.backup_dir = Path("backups")
        self.state: Dict[str, Dict] = {}
        self.backup_dir.mkdir(exist_ok=True)
        self.load_state()

    # ─────────────────────────────────────────────────────────────────────────
    # DATETIME HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _normalize_datetime(dt: Optional[datetime]) -> Optional[str]:
        """Normalize datetime to timezone-naive ISO format for comparison."""
        if dt is None:
            return None
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt.isoformat()

    @staticmethod
    def _normalize_datetime_for_storage(dt) -> Optional[str]:
        """Normalize datetime for storage. Handles objects and strings."""
        if dt is None:
            return None
        if isinstance(dt, str):
            try:
                from dateutil import parser as dtparser
                dt = dtparser.parse(dt)
            except Exception:
                return dt
        if hasattr(dt, 'tzinfo') and dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt.isoformat() if hasattr(dt, 'isoformat') else str(dt)

    @staticmethod
    def _parse_datetime(dt_str: Optional[str]) -> Optional[datetime]:
        """Parse ISO datetime string to naive datetime object."""
        if not dt_str:
            return None
        try:
            from dateutil import parser as dtparser
            dt = dtparser.parse(dt_str)
            if dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)
            return dt
        except Exception:
            return None

    # ─────────────────────────────────────────────────────────────────────────
    # METADATA
    # ─────────────────────────────────────────────────────────────────────────

    def _get_metadata(self) -> Dict:
        return self.state.get(self.METADATA_KEY, {})

    def _set_metadata(self, key: str, value) -> None:
        if self.METADATA_KEY not in self.state:
            self.state[self.METADATA_KEY] = {
                "schema_version":       SCHEMA_VERSION,
                "is_initial_sync_done": False,
                "sync_count":           0,
                "last_sync_time":       None
            }
        self.state[self.METADATA_KEY][key] = value

    def get_last_sync_time(self) -> Optional[datetime]:
        """Get global last sync timestamp."""
        return self._parse_datetime(self._get_metadata().get("last_sync_time"))

    def set_last_sync_time(self, dt: Optional[datetime] = None) -> None:
        """Set global last sync timestamp. Called at end of every successful sync."""
        now = dt or datetime.utcnow()
        self._set_metadata("last_sync_time", now.isoformat())
        logger.debug(f"Global last_sync_time: {now.isoformat()}")

    def is_initial_sync_done(self) -> bool:
        """
        False = do FULL fetch of all tasks (first run).
        True  = do DELTA fetch (only modified since last sync).
        """
        return self._get_metadata().get("is_initial_sync_done", False)

    def mark_initial_sync_done(self) -> None:
        """Mark initial full sync as complete. Enables delta sync."""
        self._set_metadata("is_initial_sync_done", True)
        logger.info("Initial sync marked complete - delta sync now enabled")

    def increment_sync_count(self) -> int:
        """Increment and return total sync counter."""
        count = self._get_metadata().get("sync_count", 0) + 1
        self._set_metadata("sync_count", count)
        return count

    def get_sync_count(self) -> int:
        return self._get_metadata().get("sync_count", 0)

    # ─────────────────────────────────────────────────────────────────────────
    # LOAD / SAVE
    # ─────────────────────────────────────────────────────────────────────────

    def load_state(self) -> None:
        """Load state from disk. Migrates v1.0 format if needed."""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    self.state = json.load(f)

                # Migrate old format (no metadata block)
                if self.METADATA_KEY not in self.state:
                    logger.info("Migrating state file to v2.0...")
                    self._migrate_state()

                task_count = len(self.get_all_task_ids())
                meta       = self._get_metadata()
                logger.info(
                    f"Loaded state: {task_count} tasks | "
                    f"syncs: {meta.get('sync_count', 0)} | "
                    f"initial done: {meta.get('is_initial_sync_done', False)}"
                )
            except Exception as e:
                logger.error(f"Failed to load sync state: {e}")
                self.state = {}
        else:
            logger.info("No sync state file - starting fresh")
            self.state = {}

        # Always ensure metadata block exists
        if self.METADATA_KEY not in self.state:
            self._set_metadata("schema_version", SCHEMA_VERSION)

    def _migrate_state(self) -> None:
        """Migrate v1.0 state to v2.0 format."""
        self.state[self.METADATA_KEY] = {
            "schema_version":       SCHEMA_VERSION,
            "is_initial_sync_done": True,
            "sync_count":           0,
            "last_sync_time":       None
        }
        for task_id, task_data in self.state.items():
            if task_id == self.METADATA_KEY:
                continue
            task_data.setdefault("is_subtask",          bool(task_data.get("parent_id")))
            task_data.setdefault("notion_page_id",       None)
            task_data.setdefault("todoist_updated_at",   None)
            task_data.setdefault("notion_last_edited",   None)
            task_data.setdefault("winning_system",       None)
        logger.info("State migrated to v2.0")

    def save_state(self) -> None:
        """Save state to disk."""
        try:
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, indent=2, default=str)
            logger.debug(f"Saved state: {len(self.get_all_task_ids())} tasks")
        except Exception as e:
            logger.error(f"Failed to save sync state: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # TASK STATE CRUD
    # ─────────────────────────────────────────────────────────────────────────

    def get_all_task_ids(self) -> List[str]:
        """Return all task IDs (excludes metadata key)."""
        return [k for k in self.state.keys() if k != self.METADATA_KEY]

    def get_last_synced(self, todoist_id: str) -> Optional[Dict]:
        """Get last synced state for a task."""
        entry = self.state.get(todoist_id)
        return entry if entry and isinstance(entry, dict) else None

    def update_state(
        self,
        todoist_id: str,
        task: Task,
        notion_page_id: Optional[str] = None,
        todoist_updated_at: Optional[datetime] = None,
        notion_last_edited: Optional[datetime] = None,
        winning_system: Optional[str] = None
    ) -> None:
        """
        Update stored state for a task after successful sync.

        Args:
            todoist_id:         Todoist task ID (primary key)
            task:               Synced task data
            notion_page_id:     Notion page ID
            todoist_updated_at: When Todoist last modified this task
            notion_last_edited: When Notion last modified this task
            winning_system:     Which system won last conflict
        """
        existing = self.state.get(todoist_id, {})

        self.state[todoist_id] = {
            # Core fields
            "title":              task.title,
            "description":        task.description,
            "priority":           task.priority,
            "due_date":           self._normalize_datetime_for_storage(task.due_date),
            "labels":             task.labels,
            "completed":          task.completed,

            # Relationship
            "parent_id":          getattr(task, 'parent_id', None),
            "is_subtask":         bool(getattr(task, 'parent_id', None)),

            # Cross-system references
            "notion_page_id":     notion_page_id or existing.get("notion_page_id"),

            # Source timestamps for conflict resolution
            "todoist_updated_at": self._normalize_datetime_for_storage(todoist_updated_at)
                                  or existing.get("todoist_updated_at"),
            "notion_last_edited": self._normalize_datetime_for_storage(notion_last_edited)
                                  or existing.get("notion_last_edited"),
            "winning_system":     winning_system or existing.get("winning_system"),

            # Sync tracking
            "last_sync_time":     datetime.utcnow().isoformat()
        }

    def update_state_notion_id(self, todoist_id: str, notion_page_id: str) -> None:
        """Update only the Notion page ID for a task."""
        if todoist_id in self.state:
            self.state[todoist_id]["notion_page_id"] = notion_page_id
            logger.debug(f"Updated notion_page_id for {todoist_id}")

    def remove_task(self, todoist_id: str) -> None:
        """Remove a task from state."""
        if todoist_id in self.state:
            del self.state[todoist_id]
            logger.debug(f"Removed task {todoist_id} from state")

    def task_exists(self, todoist_id: str) -> bool:
        """Check if a task exists in local state."""
        return todoist_id in self.state and todoist_id != self.METADATA_KEY

    def get_notion_page_id(self, todoist_id: str) -> Optional[str]:
        """Get stored Notion page ID for a Todoist task."""
        return self.state.get(todoist_id, {}).get("notion_page_id")

    def get_subtask_ids(self) -> List[str]:
        """Get all task IDs that are subtasks."""
        return [
            tid for tid in self.get_all_task_ids()
            if self.state[tid].get("parent_id")
        ]

    def get_parent_task_ids(self) -> List[str]:
        """Get all task IDs that are parents."""
        return [
            tid for tid in self.get_all_task_ids()
            if not self.state[tid].get("parent_id")
        ]

    # ─────────────────────────────────────────────────────────────────────────
    # CONFLICT RESOLUTION - LATEST TIMESTAMP WINS
    # ─────────────────────────────────────────────────────────────────────────

    def resolve_conflict(
        self,
        field: str,
        todoist_value,
        notion_value,
        todoist_updated_at: Optional[datetime],
        notion_last_edited: Optional[datetime],
        todoist_id: str
    ) -> Tuple[str, object]:
        """
        Resolve conflict using LATEST TIMESTAMP WINS strategy.

        Returns:
            Tuple of (winning_system, winning_value)
        """
        if todoist_updated_at and notion_last_edited:
            t_ts = self._parse_datetime(
                self._normalize_datetime_for_storage(todoist_updated_at)
            )
            n_ts = self._parse_datetime(
                self._normalize_datetime_for_storage(notion_last_edited)
            )

            if t_ts and n_ts:
                if n_ts > t_ts:
                    logger.info(
                        f"Conflict [{todoist_id}] {field}: "
                        f"Notion wins (newer: {n_ts} vs {t_ts})"
                    )
                    return "notion", notion_value
                else:
                    logger.info(
                        f"Conflict [{todoist_id}] {field}: "
                        f"Todoist wins (newer: {t_ts} vs {n_ts})"
                    )
                    return "todoist", todoist_value

        # Fallback: Todoist wins
        logger.warning(
            f"Conflict [{todoist_id}] {field}: "
            f"No timestamps - Todoist wins (default)"
        )
        return "todoist", todoist_value

    # ─────────────────────────────────────────────────────────────────────────
    # CHANGE DETECTION - THREE-WAY MERGE
    # ─────────────────────────────────────────────────────────────────────────

    def detect_changes(
        self,
        todoist_task: Task,
        notion_task: Task,
        todoist_id: str,
        todoist_updated_at: Optional[datetime] = None,
        notion_last_edited: Optional[datetime] = None
    ) -> Dict[str, Dict]:
        """
        Detect which fields changed using three-way merge.

        Logic:
          Todoist ≠ Last AND Notion = Last → Todoist changed → push to Notion
          Notion ≠ Last  AND Todoist = Last → Notion changed → push to Todoist
          Both ≠ Last                       → CONFLICT → latest timestamp wins

        Returns:
            {
              'todoist_changed': {field: value},
              'notion_changed':  {field: value},
              'conflicts':       {field: {todoist, notion, winner, winning_value}}
            }
        """
        last_synced = self.get_last_synced(todoist_id)

        changes = {
            'todoist_changed': {},
            'notion_changed':  {},
            'conflicts':       {}
        }

        # ── FIRST SYNC ────────────────────────────────────────────────────────
        if not last_synced:
            logger.debug(f"[{todoist_id}] First sync - Todoist is primary source")
            fields = ['title', 'description', 'priority', 'labels', 'completed']

            for field in fields:
                t_val = getattr(todoist_task, field)
                n_val = getattr(notion_task, field)

                if isinstance(t_val, list):
                    t_val = sorted(t_val or [])
                    n_val = sorted(n_val or [])

                if t_val != n_val:
                    changes['todoist_changed'][field] = getattr(todoist_task, field)

            t_due = self._normalize_datetime(todoist_task.due_date)
            n_due = self._normalize_datetime(notion_task.due_date)
            if t_due != n_due:
                changes['todoist_changed']['due_date'] = todoist_task.due_date

            return changes

        # ── SUBSEQUENT SYNCS - THREE-WAY MERGE ───────────────────────────────
        fields = ['title', 'description', 'priority', 'labels', 'completed']

        for field in fields:
            t_val = getattr(todoist_task, field)
            n_val = getattr(notion_task, field)
            b_val = last_synced.get(field)

            if isinstance(t_val, list):
                t_val = sorted(t_val or [])
                n_val = sorted(n_val or [])
                b_val = sorted(b_val or []) if isinstance(b_val, list) else b_val

            t_changed = (str(t_val) != str(b_val))
            n_changed = (str(n_val) != str(b_val))

            if t_changed and n_changed:
                winner, winning_value = self.resolve_conflict(
                    field, t_val, n_val,
                    todoist_updated_at, notion_last_edited,
                    todoist_id
                )
                changes['conflicts'][field] = {
                    'todoist':       t_val,
                    'notion':        n_val,
                    'last':          b_val,
                    'winner':        winner,
                    'winning_value': winning_value
                }
            elif t_changed:
                logger.debug(f"  [{todoist_id}] {field}: Todoist changed")
                changes['todoist_changed'][field] = getattr(todoist_task, field)
            elif n_changed:
                logger.debug(f"  [{todoist_id}] {field}: Notion changed")
                changes['notion_changed'][field] = n_val

        # ── DUE DATE ─────────────────────────────────────────────────────────
        t_due = self._normalize_datetime(todoist_task.due_date)
        n_due = self._normalize_datetime(notion_task.due_date)
        b_due = last_synced.get('due_date')

        if b_due and 'T' in str(b_due):
            try:
                from dateutil import parser as dtparser
                b_due = self._normalize_datetime(dtparser.parse(b_due))
            except Exception:
                pass

        t_due_changed = (t_due != b_due)
        n_due_changed = (n_due != b_due)

        if t_due_changed and n_due_changed:
            winner, winning_value = self.resolve_conflict(
                'due_date',
                todoist_task.due_date, notion_task.due_date,
                todoist_updated_at, notion_last_edited,
                todoist_id
            )
            changes['conflicts']['due_date'] = {
                'todoist':       todoist_task.due_date,
                'notion':        notion_task.due_date,
                'last':          b_due,
                'winner':        winner,
                'winning_value': winning_value
            }
        elif t_due_changed:
            changes['todoist_changed']['due_date'] = todoist_task.due_date
        elif n_due_changed:
            changes['notion_changed']['due_date'] = notion_task.due_date

        return changes

    # ─────────────────────────────────────────────────────────────────────────
    # BACKUP / RESTORE
    # ─────────────────────────────────────────────────────────────────────────

    def backup_state(self) -> Optional[Path]:
        """Create timestamped backup of state file before every sync."""
        if not self.state_file.exists():
            logger.warning("No state file to backup")
            return None
        try:
            timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = (
                Path("backups") / "pre_sync" /
                f"sync_state_{timestamp}.json"
            )
            backup_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.state_file, backup_file)
            logger.info(f"Pre-sync backup: {backup_file.name}")
            self._cleanup_old_backups(keep=5)
            return backup_file
        except Exception as e:
            logger.error(f"Failed to create backup: {e}")
            return None

    def restore_from_backup(self, backup_file: Optional[Path] = None) -> bool:
        """Restore state from backup file."""
        try:
            if backup_file is None:
                backups = self.list_backups()
                if not backups:
                    logger.error("No backup files found")
                    return False
                backup_file = backups[0]

            if not backup_file.exists():
                logger.error(f"Backup not found: {backup_file}")
                return False

            if self.state_file.exists():
                emergency = (
                    self.state_file.parent /
                    f"sync_state_before_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                )
                shutil.copy2(self.state_file, emergency)
                logger.info(f"Emergency backup: {emergency.name}")

            shutil.copy2(backup_file, self.state_file)
            logger.info(f"Restored from: {backup_file.name}")
            self.load_state()
            return True
        except Exception as e:
            logger.error(f"Restore failed: {e}")
            return False

    def list_backups(self) -> List[Path]:
        """List backup files, newest first."""
        pre_sync_dir = Path("backups") / "pre_sync"
        if not pre_sync_dir.exists():
            return []
        return sorted(
            pre_sync_dir.glob("sync_state_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )

    def _cleanup_old_backups(self, keep: int = 5) -> None:
        """Remove backups beyond retention limit."""
        for old in self.list_backups()[keep:]:
            try:
                old.unlink()
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────────────────
    # SYNC PROGRESS MARKERS
    # ─────────────────────────────────────────────────────────────────────────

    def mark_sync_in_progress(self) -> None:
        """Create in-progress marker."""
        try:
            marker = self.state_file.parent / f"{self.state_file.stem}.inprogress"
            marker.write_text(datetime.utcnow().isoformat())
        except Exception:
            pass

    def clear_sync_in_progress(self) -> None:
        """Remove in-progress marker."""
        try:
            marker = self.state_file.parent / f"{self.state_file.stem}.inprogress"
            if marker.exists():
                marker.unlink()
        except Exception:
            pass

    def check_incomplete_sync(self) -> bool:
        """Check if previous sync was interrupted."""
        marker = self.state_file.parent / f"{self.state_file.stem}.inprogress"
        if marker.exists():
            try:
                start_time = marker.read_text()
                logger.warning(f"Incomplete sync detected! Started: {start_time}")
                return True
            except Exception:
                pass
        return False

    # ─────────────────────────────────────────────────────────────────────────
    # DIAGNOSTICS
    # ─────────────────────────────────────────────────────────────────────────

    def print_summary(self) -> None:
        """Print state summary."""
        meta     = self._get_metadata()
        all_ids  = self.get_all_task_ids()
        parents  = self.get_parent_task_ids()
        subtasks = self.get_subtask_ids()

        logger.info("=" * 60)
        logger.info("SYNC STATE SUMMARY")
        logger.info("=" * 60)
        logger.info(f"  Schema:           {meta.get('schema_version', 'unknown')}")
        logger.info(f"  Total tasks:      {len(all_ids)}")
        logger.info(f"  Parent tasks:     {len(parents)}")
        logger.info(f"  Subtasks:         {len(subtasks)}")
        logger.info(f"  Sync count:       {meta.get('sync_count', 0)}")
        logger.info(f"  Last sync:        {meta.get('last_sync_time', 'Never')}")
        logger.info(f"  Initial done:     {meta.get('is_initial_sync_done', False)}")
        logger.info("=" * 60)
