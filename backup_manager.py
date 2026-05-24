"""
backup_manager.py
─────────────────
Full backup and restore system for Todoist-Notion sync.

Backup Layers:
  1. Pre-sync   : sync_state.json only  → before every sync
  2. Full snapshot: Todoist + Notion + state → every 3 days
  3. Weekly archive: everything          → every Sunday
  4. Manual     : on demand via CLI

Usage:
  python backup_manager.py --backup           # full snapshot now
  python backup_manager.py --list             # list snapshots
  python backup_manager.py --validate         # validate latest
  python backup_manager.py --restore-state    # restore sync state only
  python backup_manager.py --restore-notion   # restore Notion from Todoist
  python backup_manager.py --restore-todoist  # restore Todoist from Notion
  python backup_manager.py --restore-all      # full restore from snapshot
  python backup_manager.py --dry-run          # preview restore
  python backup_manager.py --snapshot ID      # use specific snapshot
"""

import json
import logging
import shutil
import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict

from config import settings
from todoist_api import TodoistClient
from notion_api import NotionClient

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# DATA CLASSES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SnapshotMetadata:
    """Metadata stored alongside each snapshot."""
    snapshot_id: str
    created_at: str
    snapshot_type: str          # 'manual' | 'full' | 'weekly' | 'pre_sync'
    todoist_task_count: int
    todoist_subtask_count: int
    notion_task_count: int
    notion_subtask_count: int
    sync_state_entries: int
    last_sync_time: Optional[str]
    is_valid: bool
    notes: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# BACKUP MANAGER
# ─────────────────────────────────────────────────────────────────────────────

class BackupManager:
    """
    Manages full backups and restores for the Todoist-Notion sync system.

    Directory structure:
      backups/
        snapshots/          ← full snapshots (every 3 days + manual)
          20260223_143000/
            metadata.json
            todoist_tasks.json
            notion_tasks.json
            sync_state.json
        weekly/             ← weekly archives (every Sunday)
          20260223_143000/
            ...same structure...
        pre_sync/           ← lightweight state-only backups
          sync_state_20260223_143000.json
    """

    def __init__(self):
        self.backup_root    = Path(settings.backup_dir)
        self.snapshots_dir  = self.backup_root / "snapshots"
        self.weekly_dir     = self.backup_root / "weekly"
        self.pre_sync_dir   = self.backup_root / "pre_sync"
        self.state_file     = Path("sync_state.json")

        # Ensure directories exist
        for d in [self.snapshots_dir, self.weekly_dir, self.pre_sync_dir]:
            d.mkdir(parents=True, exist_ok=True)

        logger.info(f"BackupManager initialized → {self.backup_root}")

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _snapshot_id(self) -> str:
        """Generate timestamped snapshot ID."""
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    def _load_sync_state(self) -> Dict:
        """Load current sync_state.json."""
        if not self.state_file.exists():
            return {}
        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load sync_state.json: {e}")
            return {}

    def _save_json(self, path: Path, data: dict) -> bool:
        """Save data to JSON file."""
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, default=str)
            return True
        except Exception as e:
            logger.error(f"Failed to save {path}: {e}")
            return False

    def _load_json(self, path: Path) -> Optional[Dict]:
        """Load JSON file."""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load {path}: {e}")
            return None

    def _task_to_dict(self, task) -> Dict:
        """Convert a TodoistTask to a serializable dict."""
        return {
            "id":           task.id,
            "content":      task.content,
            "description":  task.description or "",
            "priority":     task.priority,
            "parent_id":    task.parent_id,
            "labels":       task.labels or [],
            "completed":    task.completed,
            "due":          str(task.due_datetime) if task.due_datetime else None,
            "created_at":   str(task.created_at) if task.created_at else None,
        }

    def _notion_task_to_dict(self, task) -> Dict:
        """Convert a NotionTask to a serializable dict."""
        return {
            "id":                 task.id,
            "todoist_task_id":    task.todoist_task_id,
            "title":              task.title,
            "description":        task.description or "",
            "priority":           task.priority,
            "parent_id":          task.parent_id,
            "labels":             task.labels or [],
            "completed":          task.completed,
            "due_date":           str(task.due_date) if task.due_date else None,
            "source":             task.source.value if task.source else None,
            "last_modified_source": task.last_modified_source.value
                                    if task.last_modified_source else None,
            "last_modified_time": str(task.last_modified_time)
                                   if task.last_modified_time else None,
        }

    # ── Pre-Sync Backup (lightweight) ────────────────────────────────────────

    def pre_sync_backup(self) -> Optional[Path]:
        """
        Lightweight backup of sync_state.json only.
        Called automatically before every sync.
        """
        if not settings.backup_pre_sync_enabled:
            return None

        if not self.state_file.exists():
            logger.debug("No sync_state.json to backup")
            return None

        try:
            sid   = self._snapshot_id()
            dest  = self.pre_sync_dir / f"sync_state_{sid}.json"
            shutil.copy2(self.state_file, dest)
            logger.info(f"Pre-sync backup created: {dest.name}")

            # Cleanup old pre-sync backups
            self._cleanup(self.pre_sync_dir, settings.backup_pre_sync_keep)
            return dest

        except Exception as e:
            logger.error(f"Pre-sync backup failed: {e}")
            return None

    # ── Full Snapshot ─────────────────────────────────────────────────────────

    def create_snapshot(
        self,
        snapshot_type: str = "manual",
        target_dir: Optional[Path] = None
    ) -> Optional[Path]:
        """
        Create a full snapshot of Todoist + Notion + sync_state.

        Args:
            snapshot_type: 'manual' | 'full' | 'weekly'
            target_dir:    Override directory (defaults to snapshots_dir)

        Returns:
            Path to snapshot directory, or None on failure
        """
        print(f"\n🔄 Creating {snapshot_type} snapshot...")

        sid       = self._snapshot_id()
        base_dir  = target_dir or self.snapshots_dir
        snap_dir  = base_dir / sid
        snap_dir.mkdir(parents=True, exist_ok=True)

        try:
            # 1. Fetch Todoist tasks
            print("   📥 Fetching Todoist tasks...")
            todoist_client = TodoistClient(settings.todoist_api_token)
            todoist_tasks  = todoist_client.get_all_tasks()

            todoist_parents  = [t for t in todoist_tasks if not t.parent_id]
            todoist_subtasks = [t for t in todoist_tasks if t.parent_id]

            todoist_data = {
                "snapshot_time":   datetime.now().isoformat(),
                "total_tasks":     len(todoist_tasks),
                "parent_count":    len(todoist_parents),
                "subtask_count":   len(todoist_subtasks),
                "tasks":           [self._task_to_dict(t) for t in todoist_tasks]
            }
            self._save_json(snap_dir / "todoist_tasks.json", todoist_data)
            print(f"   ✅ Todoist: {len(todoist_tasks)} tasks "
                  f"({len(todoist_parents)} parents, "
                  f"{len(todoist_subtasks)} subtasks)")

            # 2. Fetch Notion tasks
            print("   📥 Fetching Notion tasks...")
            notion_client = NotionClient(settings.notion_api_token)
            notion_tasks  = notion_client.get_all_tasks()

            notion_parents  = [t for t in notion_tasks if not t.parent_id]
            notion_subtasks = [t for t in notion_tasks if t.parent_id]

            notion_data = {
                "snapshot_time":  datetime.now().isoformat(),
                "total_tasks":    len(notion_tasks),
                "parent_count":   len(notion_parents),
                "subtask_count":  len(notion_subtasks),
                "tasks":          [self._notion_task_to_dict(t) for t in notion_tasks]
            }
            self._save_json(snap_dir / "notion_tasks.json", notion_data)
            print(f"   ✅ Notion: {len(notion_tasks)} tasks "
                  f"({len(notion_parents)} parents, "
                  f"{len(notion_subtasks)} subtasks)")

            # 3. Copy sync_state.json
            sync_state = self._load_sync_state()
            self._save_json(snap_dir / "sync_state.json", sync_state)
            print(f"   ✅ Sync state: {len(sync_state)} entries")

            # 4. Write metadata
            last_sync = sync_state.get("_metadata", {}).get("last_sync_time")
            meta = SnapshotMetadata(
                snapshot_id          = sid,
                created_at           = datetime.now().isoformat(),
                snapshot_type        = snapshot_type,
                todoist_task_count   = len(todoist_parents),
                todoist_subtask_count= len(todoist_subtasks),
                notion_task_count    = len(notion_parents),
                notion_subtask_count = len(notion_subtasks),
                sync_state_entries   = len(sync_state),
                last_sync_time       = last_sync,
                is_valid             = True
            )
            self._save_json(snap_dir / "metadata.json", asdict(meta))

            print(f"\n   ✅ Snapshot saved: {snap_dir.name}")

            # 5. Cleanup old snapshots
            keep = (settings.backup_weekly_keep
                    if snapshot_type == "weekly"
                    else settings.backup_full_keep)
            self._cleanup(base_dir, keep)

            return snap_dir

        except Exception as e:
            logger.error(f"Snapshot failed: {e}")
            # Remove incomplete snapshot
            if snap_dir.exists():
                shutil.rmtree(snap_dir)
            return None

    # ── Scheduled Backup Check ────────────────────────────────────────────────

    def check_scheduled_backups(self) -> None:
        """
        Called during each sync to check if scheduled backups are due.
        - Full snapshot every 3 days
        - Weekly archive every Sunday
        """
        now = datetime.now()

        # Check full snapshot
        if settings.backup_full_enabled:
            if self._is_backup_due(self.snapshots_dir,
                                   settings.backup_full_every_days):
                logger.info("Full snapshot due - creating now...")
                self.create_snapshot(snapshot_type="full")

        # Check weekly archive (Sunday = weekday 6)
        if settings.backup_weekly_enabled and now.weekday() == 6:
            if self._is_backup_due(self.weekly_dir, days=7):
                logger.info("Weekly archive due - creating now...")
                self.create_snapshot(
                    snapshot_type="weekly",
                    target_dir=self.weekly_dir
                )

    def _is_backup_due(self, directory: Path, days: int) -> bool:
        """Check if a backup is due based on last backup time."""
        snapshots = self._list_snapshots(directory)
        if not snapshots:
            return True     # No backups yet → due immediately

        latest    = snapshots[0]
        meta_file = latest / "metadata.json"
        if not meta_file.exists():
            return True

        meta = self._load_json(meta_file)
        if not meta:
            return True

        try:
            last = datetime.fromisoformat(meta["created_at"])
            return (datetime.now() - last) >= timedelta(days=days)
        except Exception:
            return True

    # ── List Snapshots ────────────────────────────────────────────────────────

    def _list_snapshots(self, directory: Path) -> List[Path]:
        """List snapshot directories sorted newest first."""
        if not directory.exists():
            return []
        snapshots = sorted(
            [d for d in directory.iterdir() if d.is_dir()],
            key=lambda d: d.name,
            reverse=True
        )
        return snapshots

    def list_all_snapshots(self) -> None:
        """Print all available snapshots."""
        print("\n" + "=" * 70)
        print("📦 AVAILABLE SNAPSHOTS")
        print("=" * 70)

        for label, directory in [
            ("Full Snapshots",   self.snapshots_dir),
            ("Weekly Archives",  self.weekly_dir),
            ("Pre-Sync Backups", self.pre_sync_dir),
        ]:
            print(f"\n📁 {label}:")
            print("-" * 70)

            if label == "Pre-Sync Backups":
                # List individual files
                files = sorted(
                    self.pre_sync_dir.glob("*.json"),
                    key=lambda f: f.name,
                    reverse=True
                )
                if not files:
                    print("   (none)")
                    continue
                for f in files:
                    size  = f.stat().st_size / 1024
                    mtime = datetime.fromtimestamp(f.stat().st_mtime)
                    print(f"   • {f.name}")
                    print(f"     Created: {mtime.strftime('%Y-%m-%d %H:%M:%S')}  "
                          f"Size: {size:.1f} KB")
                continue

            snapshots = self._list_snapshots(directory)
            if not snapshots:
                print("   (none)")
                continue

            for snap in snapshots:
                meta_file = snap / "metadata.json"
                if not meta_file.exists():
                    print(f"   • {snap.name} (no metadata)")
                    continue

                meta = self._load_json(meta_file)
                if not meta:
                    continue

                valid = "✅" if meta.get("is_valid") else "❌"
                print(f"\n   {valid} {snap.name}")
                print(f"      Type:     {meta.get('snapshot_type', 'unknown')}")
                print(f"      Created:  {meta.get('created_at', 'unknown')}")
                print(f"      Todoist:  {meta.get('todoist_task_count', 0)} parents + "
                      f"{meta.get('todoist_subtask_count', 0)} subtasks")
                print(f"      Notion:   {meta.get('notion_task_count', 0)} parents + "
                      f"{meta.get('notion_subtask_count', 0)} subtasks")
                print(f"      State:    {meta.get('sync_state_entries', 0)} entries")
                print(f"      Last sync:{meta.get('last_sync_time', 'N/A')}")

        print("\n" + "=" * 70)

    # ── Validate ──────────────────────────────────────────────────────────────

    def validate_snapshot(self, snap_dir: Path) -> Tuple[bool, List[str]]:
        """
        Validate a snapshot for integrity.

        Returns:
            (is_valid, list of issues)
        """
        issues = []

        # Check required files
        required = ["metadata.json", "todoist_tasks.json",
                    "notion_tasks.json", "sync_state.json"]
        for fname in required:
            if not (snap_dir / fname).exists():
                issues.append(f"Missing file: {fname}")

        if issues:
            return False, issues

        # Load and validate metadata
        meta = self._load_json(snap_dir / "metadata.json")
        if not meta:
            issues.append("Cannot read metadata.json")
            return False, issues

        # Validate Todoist data
        todoist = self._load_json(snap_dir / "todoist_tasks.json")
        if not todoist:
            issues.append("Cannot read todoist_tasks.json")
        else:
            actual_count = len(todoist.get("tasks", []))
            expected     = meta.get("todoist_task_count", 0) + \
                           meta.get("todoist_subtask_count", 0)
            if actual_count != expected:
                issues.append(
                    f"Todoist task count mismatch: "
                    f"expected {expected}, found {actual_count}"
                )

            # Check subtask parent references
            task_ids = {t["id"] for t in todoist.get("tasks", [])}
            for task in todoist.get("tasks", []):
                if task.get("parent_id") and task["parent_id"] not in task_ids:
                    issues.append(
                        f"Orphaned subtask: {task['id']} "
                        f"parent {task['parent_id']} not found"
                    )

        # Validate Notion data
        notion = self._load_json(snap_dir / "notion_tasks.json")
        if not notion:
            issues.append("Cannot read notion_tasks.json")
        else:
            actual_count = len(notion.get("tasks", []))
            expected     = meta.get("notion_task_count", 0) + \
                           meta.get("notion_subtask_count", 0)
            if actual_count != expected:
                issues.append(
                    f"Notion task count mismatch: "
                    f"expected {expected}, found {actual_count}"
                )

        return len(issues) == 0, issues

    def validate_latest(self) -> None:
        """Validate the most recent snapshot."""
        print("\n" + "=" * 70)
        print("🔍 VALIDATING LATEST SNAPSHOT")
        print("=" * 70)

        snapshots = self._list_snapshots(self.snapshots_dir)
        if not snapshots:
            print("\n❌ No snapshots found to validate.\n")
            return

        latest        = snapshots[0]
        is_valid, issues = self.validate_snapshot(latest)

        print(f"\nSnapshot: {latest.name}")
        if is_valid:
            print("✅ Snapshot is valid!\n")
        else:
            print(f"❌ Snapshot has {len(issues)} issue(s):")
            for issue in issues:
                print(f"   • {issue}")
            print()

    # ── Restore ───────────────────────────────────────────────────────────────

    def _get_snapshot(self, snapshot_id: Optional[str] = None) -> Optional[Path]:
        """Get snapshot directory by ID or return latest."""
        snapshots = self._list_snapshots(self.snapshots_dir)
        if not snapshots:
            # Try weekly archives
            snapshots = self._list_snapshots(self.weekly_dir)

        if not snapshots:
            print("❌ No snapshots found!")
            return None

        if snapshot_id:
            matches = [s for s in snapshots if s.name == snapshot_id]
            if not matches:
                print(f"❌ Snapshot '{snapshot_id}' not found!")
                return None
            return matches[0]

        return snapshots[0]  # Latest

    def _confirm(self, message: str, dry_run: bool) -> bool:
        """Ask user to confirm action."""
        if dry_run:
            print(f"\n[DRY RUN] Would: {message}")
            return False

        print(f"\n⚠️  {message}")
        response = input("Continue? (yes/no): ").strip().lower()
        return response == "yes"

    def restore_state_only(
        self,
        snapshot_id: Optional[str] = None,
        dry_run: bool = False
    ) -> bool:
        """
        Restore sync_state.json from snapshot.
        Safest restore - does not touch Todoist or Notion.
        """
        print("\n" + "=" * 70)
        print("🔄 RESTORE: Sync State Only")
        print("=" * 70)

        snap = self._get_snapshot(snapshot_id)
        if not snap:
            return False

        state_backup = snap / "sync_state.json"
        if not state_backup.exists():
            print(f"❌ No sync_state.json in snapshot {snap.name}")
            return False

        # Show what will be restored
        data   = self._load_json(state_backup)
        count  = len(data) if data else 0
        meta   = self._load_json(snap / "metadata.json")
        creat  = meta.get("created_at", "unknown") if meta else "unknown"

        print(f"\n   Snapshot:  {snap.name}")
        print(f"   Created:   {creat}")
        print(f"   Entries:   {count}")
        print(f"\n   This will ONLY restore sync tracking.")
        print(f"   Todoist and Notion data will NOT be changed.")

        if not self._confirm("Restore sync_state.json?", dry_run):
            if not dry_run:
                print("❌ Cancelled.")
            return False

        # Emergency backup of current state
        if self.state_file.exists():
            emergency = self.state_file.parent / \
                        f"sync_state_BEFORE_RESTORE_{self._snapshot_id()}.json"
            shutil.copy2(self.state_file, emergency)
            print(f"\n   Emergency backup: {emergency.name}")

        shutil.copy2(state_backup, self.state_file)
        print(f"   ✅ sync_state.json restored from {snap.name}")
        return True

    def restore_notion_from_todoist(
        self,
        snapshot_id: Optional[str] = None,
        dry_run: bool = False
    ) -> bool:
        """
        Restore Notion tasks using Todoist snapshot data.
        Use when Notion data is corrupted or accidentally deleted.
        """
        print("\n" + "=" * 70)
        print("🔄 RESTORE: Notion from Todoist snapshot")
        print("=" * 70)

        snap = self._get_snapshot(snapshot_id)
        if not snap:
            return False

        todoist_data = self._load_json(snap / "todoist_tasks.json")
        if not todoist_data:
            print("❌ Cannot read Todoist data from snapshot")
            return False

        tasks = todoist_data.get("tasks", [])
        print(f"\n   Snapshot:  {snap.name}")
        print(f"   Tasks:     {len(tasks)}")
        print(f"\n   ⚠️  This will recreate/update ALL Notion tasks")
        print(f"   from the Todoist snapshot.")

        if not self._confirm(
            f"Restore {len(tasks)} tasks to Notion?", dry_run
        ):
            if not dry_run:
                print("❌ Cancelled.")
            return False

        print(f"\n   🔄 Restoring {len(tasks)} tasks to Notion...")
        notion_client = NotionClient(settings.notion_api_token)
        success = 0
        failed  = 0

        for task_data in tasks:
            try:
                # Try to find existing Notion page
                all_notion = notion_client.get_all_tasks()
                notion_map = {
                    t.todoist_task_id: t
                    for t in all_notion
                    if t.todoist_task_id
                }

                if task_data["id"] in notion_map:
                    # Update existing
                    notion_task = notion_map[task_data["id"]]
                    notion_client.update_task(
                        page_id     = notion_task.id,
                        title       = task_data["content"],
                        description = task_data.get("description", ""),
                        priority    = task_data.get("priority", 1),
                        completed   = task_data.get("completed", False),
                        labels      = task_data.get("labels", [])
                    )
                else:
                    # Create new
                    from models import TaskSource
                    notion_client.create_task(
                        title               = task_data["content"],
                        todoist_task_id     = task_data["id"],
                        description         = task_data.get("description", ""),
                        priority            = task_data.get("priority", 1),
                        completed           = task_data.get("completed", False),
                        labels              = task_data.get("labels", []),
                        parent_todoist_id   = task_data.get("parent_id"),
                        source              = TaskSource.TODOIST
                    )
                success += 1
                print(f"   ✅ {task_data['content'][:50]}")

            except Exception as e:
                failed += 1
                print(f"   ❌ {task_data['content'][:50]}: {e}")

        print(f"\n   Done: {success} restored, {failed} failed")
        return failed == 0

    def restore_todoist_from_notion(
        self,
        snapshot_id: Optional[str] = None,
        dry_run: bool = False
    ) -> bool:
        """
        Restore Todoist tasks using Notion snapshot data.
        Use when Todoist data is corrupted or accidentally deleted.
        """
        print("\n" + "=" * 70)
        print("🔄 RESTORE: Todoist from Notion snapshot")
        print("=" * 70)

        snap = self._get_snapshot(snapshot_id)
        if not snap:
            return False

        notion_data = self._load_json(snap / "notion_tasks.json")
        if not notion_data:
            print("❌ Cannot read Notion data from snapshot")
            return False

        tasks = notion_data.get("tasks", [])
        print(f"\n   Snapshot:  {snap.name}")
        print(f"   Tasks:     {len(tasks)}")
        print(f"\n   ⚠️  This will recreate/update ALL Todoist tasks")
        print(f"   from the Notion snapshot.")

        if not self._confirm(
            f"Restore {len(tasks)} tasks to Todoist?", dry_run
        ):
            if not dry_run:
                print("❌ Cancelled.")
            return False

        print(f"\n   🔄 Restoring {len(tasks)} tasks to Todoist...")
        todoist_client = TodoistClient(settings.todoist_api_token)
        success = 0
        failed  = 0

        # Restore parents first, then subtasks
        parents  = [t for t in tasks if not t.get("parent_id")]
        subtasks = [t for t in tasks if t.get("parent_id")]

        for task_data in parents + subtasks:
            try:
                if task_data.get("todoist_task_id"):
                    # Try to update existing
                    try:
                        todoist_client.update_task(
                            task_id     = task_data["todoist_task_id"],
                            content     = task_data["title"],
                            description = task_data.get("description", ""),
                            priority    = task_data.get("priority", 1),
                            labels      = task_data.get("labels", [])
                        )
                    except Exception:
                        # Task may not exist anymore, create it
                        todoist_client.create_task(
                            content     = task_data["title"],
                            description = task_data.get("description", ""),
                            priority    = task_data.get("priority", 1),
                            labels      = task_data.get("labels", []),
                            parent_id   = task_data.get("parent_id")
                        )
                else:
                    todoist_client.create_task(
                        content     = task_data["title"],
                        description = task_data.get("description", ""),
                        priority    = task_data.get("priority", 1),
                        labels      = task_data.get("labels", []),
                        parent_id   = task_data.get("parent_id")
                    )
                success += 1
                print(f"   ✅ {task_data['title'][:50]}")

            except Exception as e:
                failed += 1
                print(f"   ❌ {task_data['title'][:50]}: {e}")

        print(f"\n   Done: {success} restored, {failed} failed")
        return failed == 0

    def restore_all(
        self,
        snapshot_id: Optional[str] = None,
        dry_run: bool = False
    ) -> bool:
        """
        Full restore: sync_state + Notion + Todoist from snapshot.
        Use for catastrophic failures where both systems need recovery.
        """
        print("\n" + "=" * 70)
        print("🔄 FULL RESTORE: Sync State + Notion + Todoist")
        print("=" * 70)

        snap = self._get_snapshot(snapshot_id)
        if not snap:
            return False

        # Validate snapshot first
        is_valid, issues = self.validate_snapshot(snap)
        if not is_valid:
            print(f"\n❌ Snapshot {snap.name} is invalid:")
            for issue in issues:
                print(f"   • {issue}")
            print("\nAborting restore. Use --validate to check snapshots.")
            return False

        meta  = self._load_json(snap / "metadata.json")
        creat = meta.get("created_at", "unknown") if meta else "unknown"

        todoist_data = self._load_json(snap / "todoist_tasks.json")
        notion_data  = self._load_json(snap / "notion_tasks.json")

        t_count = len(todoist_data.get("tasks", [])) if todoist_data else 0
        n_count = len(notion_data.get("tasks", []))  if notion_data  else 0

        print(f"""
   Snapshot:       {snap.name}
   Created:        {creat}
   Todoist tasks:  {t_count}
   Notion tasks:   {n_count}

   ⚠️  WARNING: This will:
     1. Restore sync_state.json
     2. Update/create ALL Notion tasks
     3. Update/create ALL Todoist tasks

   This is a FULL RESTORE and cannot be undone!
        """)

        if not self._confirm("Proceed with FULL RESTORE?", dry_run):
            if not dry_run:
                print("❌ Cancelled.")
            return False

        # Step 1: Restore state
        print("\n   Step 1/3: Restoring sync state...")
        state_backup = snap / "sync_state.json"
        if self.state_file.exists():
            emergency = self.state_file.parent / \
                        f"sync_state_BEFORE_RESTORE_{self._snapshot_id()}.json"
            shutil.copy2(self.state_file, emergency)
            print(f"   Emergency backup: {emergency.name}")
        shutil.copy2(state_backup, self.state_file)
        print("   ✅ Sync state restored")

        # Step 2: Restore Notion
        print("\n   Step 2/3: Restoring Notion...")
        self.restore_notion_from_todoist(snapshot_id=snap.name, dry_run=dry_run)

        # Step 3: Restore Todoist
        print("\n   Step 3/3: Restoring Todoist...")
        self.restore_todoist_from_notion(snapshot_id=snap.name, dry_run=dry_run)

        print("\n✅ FULL RESTORE COMPLETE!")
        return True

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def _cleanup(self, directory: Path, keep: int) -> None:
        """Remove old snapshots beyond retention limit."""
        if directory == self.pre_sync_dir:
            # Pre-sync: cleanup individual files
            files = sorted(
                directory.glob("*.json"),
                key=lambda f: f.name,
                reverse=True
            )
            for old in files[keep:]:
                try:
                    old.unlink()
                    logger.debug(f"Deleted old pre-sync backup: {old.name}")
                except Exception as e:
                    logger.warning(f"Could not delete {old.name}: {e}")
        else:
            # Full/weekly: cleanup snapshot directories
            snapshots = self._list_snapshots(directory)
            for old in snapshots[keep:]:
                try:
                    shutil.rmtree(old)
                    logger.debug(f"Deleted old snapshot: {old.name}")
                except Exception as e:
                    logger.warning(f"Could not delete {old.name}: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# COMMAND LINE INTERFACE
# ─────────────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="Backup Manager for Todoist-Notion Sync",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python backup_manager.py --backup             # Full snapshot now
  python backup_manager.py --list               # List all snapshots
  python backup_manager.py --validate           # Validate latest snapshot
  python backup_manager.py --restore-state      # Restore sync state only
  python backup_manager.py --restore-notion     # Restore Notion from Todoist
  python backup_manager.py --restore-todoist    # Restore Todoist from Notion
  python backup_manager.py --restore-all        # Full restore
  python backup_manager.py --restore-all --dry-run    # Preview restore
  python backup_manager.py --restore-all --snapshot 20260223_143000
        """
    )

    parser.add_argument('--backup',           action='store_true',
                        help='Create full snapshot now')
    parser.add_argument('--list',             action='store_true',
                        help='List all available snapshots')
    parser.add_argument('--validate',         action='store_true',
                        help='Validate latest snapshot')
    parser.add_argument('--restore-state',    action='store_true',
                        help='Restore sync_state.json only (safest)')
    parser.add_argument('--restore-notion',   action='store_true',
                        help='Restore Notion tasks from Todoist snapshot')
    parser.add_argument('--restore-todoist',  action='store_true',
                        help='Restore Todoist tasks from Notion snapshot')
    parser.add_argument('--restore-all',      action='store_true',
                        help='Full restore (state + Notion + Todoist)')
    parser.add_argument('--dry-run',          action='store_true',
                        help='Preview what would happen without making changes')
    parser.add_argument('--snapshot',         type=str, default=None,
                        help='Specific snapshot ID to use (e.g. 20260223_143000)')
    parser.add_argument('--log-level',
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                        default='INFO',
                        help='Logging level')

    return parser.parse_args()


def main():
    args = parse_args()

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    mgr = BackupManager()

    if args.dry_run:
        print("\n⚠️  DRY RUN MODE - No changes will be made\n")

    # ── Execute command ───────────────────────────────────────────────────────

    if args.backup:
        result = mgr.create_snapshot(snapshot_type="manual")
        sys.exit(0 if result else 1)

    elif args.list:
        mgr.list_all_snapshots()

    elif args.validate:
        mgr.validate_latest()

    elif args.restore_state:
        ok = mgr.restore_state_only(
            snapshot_id = args.snapshot,
            dry_run     = args.dry_run
        )
        sys.exit(0 if ok else 1)

    elif args.restore_notion:
        ok = mgr.restore_notion_from_todoist(
            snapshot_id = args.snapshot,
            dry_run     = args.dry_run
        )
        sys.exit(0 if ok else 1)

    elif args.restore_todoist:
        ok = mgr.restore_todoist_from_notion(
            snapshot_id = args.snapshot,
            dry_run     = args.dry_run
        )
        sys.exit(0 if ok else 1)

    elif args.restore_all:
        ok = mgr.restore_all(
            snapshot_id = args.snapshot,
            dry_run     = args.dry_run
        )
        sys.exit(0 if ok else 1)

    else:
        # No command given → show help + status
        print("\n" + "=" * 70)
        print("📦 BACKUP MANAGER STATUS")
        print("=" * 70)
        print(f"\n  Backup directory:    {mgr.backup_root.absolute()}")
        print(f"  Full snapshots every:{settings.backup_full_every_days} days")
        print(f"  Keep full snapshots: {settings.backup_full_keep}")
        print(f"  Keep weekly:         {settings.backup_weekly_keep}")
        print(f"  Keep pre-sync:       {settings.backup_pre_sync_keep}")

        # Quick counts
        full   = len(mgr._list_snapshots(mgr.snapshots_dir))
        weekly = len(mgr._list_snapshots(mgr.weekly_dir))
        pre    = len(list(mgr.pre_sync_dir.glob("*.json")))

        print(f"\n  Full snapshots:      {full}")
        print(f"  Weekly archives:     {weekly}")
        print(f"  Pre-sync backups:    {pre}")
        print(f"\n  Run with --help for all commands.\n")


if __name__ == "__main__":
    main()
