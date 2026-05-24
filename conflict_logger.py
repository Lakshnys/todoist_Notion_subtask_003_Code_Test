"""
conflict_logger.py
──────────────────
Logs sync conflicts to file for visibility and review.

WHAT IS A CONFLICT?
  Both Todoist AND Notion changed the same field
  since the last sync. The latest timestamp wins,
  but the conflict is logged for review.

LOG FILE: conflicts.log (in project folder)
FORMAT:   JSON Lines (one JSON object per line)

USAGE:
  from conflict_logger import ConflictLogger

  logger = ConflictLogger()
  logger.log_conflict(
      todoist_id    = "abc123",
      task_title    = "My Task",
      field         = "title",
      todoist_value = "Old Title",
      notion_value  = "New Title",
      winner        = "notion",
      winning_value = "New Title",
      todoist_ts    = datetime(...),
      notion_ts     = datetime(...)
  )

  # Print summary of recent conflicts
  logger.print_summary(days=7)
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)


class ConflictLogger:
    """
    Logs sync conflicts to a JSON Lines file.

    Each conflict record contains:
      - timestamp:      When the conflict was detected
      - todoist_id:     Todoist task ID
      - task_title:     Task title for readability
      - field:          Which field conflicted (title, priority, etc.)
      - todoist_value:  What Todoist had
      - notion_value:   What Notion had
      - winner:         Which system won ('todoist' or 'notion')
      - winning_value:  The value that was kept
      - todoist_ts:     When Todoist last modified the task
      - notion_ts:      When Notion last modified the task
      - sync_count:     Which sync run detected this
    """

    def __init__(
        self,
        log_file: str = "conflicts.log",
        max_size_mb: float = 5.0
    ):
        """
        Initialize conflict logger.

        Args:
            log_file:    Path to conflict log file
            max_size_mb: Max log file size before rotation (default 5MB)
        """
        self.log_file   = Path(log_file)
        self.max_size   = max_size_mb * 1024 * 1024  # Convert to bytes
        self._sync_count = 0

        logger.debug(f"ConflictLogger initialized: {self.log_file}")

    # ─────────────────────────────────────────────────────────────────────────
    # LOG CONFLICT
    # ─────────────────────────────────────────────────────────────────────────

    def log_conflict(
        self,
        todoist_id:    str,
        task_title:    str,
        field:         str,
        todoist_value: object,
        notion_value:  object,
        winner:        str,
        winning_value: object,
        todoist_ts:    Optional[datetime] = None,
        notion_ts:     Optional[datetime] = None,
        sync_count:    int = 0
    ) -> None:
        """
        Log a single conflict to file.

        Args:
            todoist_id:    Todoist task ID
            task_title:    Human-readable task title
            field:         Field name that conflicted
            todoist_value: Current Todoist value
            notion_value:  Current Notion value
            winner:        'todoist' or 'notion'
            winning_value: The value that was applied
            todoist_ts:    Todoist last modified timestamp
            notion_ts:     Notion last modified timestamp
            sync_count:    Current sync run number
        """
        record = {
            "timestamp":     datetime.utcnow().isoformat(),
            "todoist_id":    todoist_id,
            "task_title":    task_title,
            "field":         field,
            "todoist_value": self._safe_str(todoist_value),
            "notion_value":  self._safe_str(notion_value),
            "winner":        winner,
            "winning_value": self._safe_str(winning_value),
            "todoist_ts":    todoist_ts.isoformat() if todoist_ts else None,
            "notion_ts":     notion_ts.isoformat()  if notion_ts  else None,
            "sync_count":    sync_count or self._sync_count
        }

        try:
            # Rotate if too large
            self._rotate_if_needed()

            # Append to log file
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(record) + '\n')

            logger.info(
                f"Conflict logged: [{todoist_id}] '{task_title}' "
                f"field='{field}' winner={winner}"
            )

        except Exception as e:
            logger.error(f"Failed to write conflict log: {e}")

    def set_sync_count(self, count: int) -> None:
        """Set current sync count for context in log records."""
        self._sync_count = count

    # ─────────────────────────────────────────────────────────────────────────
    # READ CONFLICTS
    # ─────────────────────────────────────────────────────────────────────────

    def read_conflicts(
        self,
        days: Optional[int] = None,
        field: Optional[str] = None,
        todoist_id: Optional[str] = None,
        winner: Optional[str] = None
    ) -> List[Dict]:
        """
        Read conflict records from log file with optional filters.

        Args:
            days:       Only return conflicts from last N days
            field:      Filter by field name
            todoist_id: Filter by specific task ID
            winner:     Filter by winning system ('todoist' or 'notion')

        Returns:
            List of conflict records (newest first)
        """
        if not self.log_file.exists():
            return []

        records = []
        cutoff  = None

        if days:
            cutoff = datetime.utcnow() - timedelta(days=days)

        try:
            with open(self.log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)

                        # Apply filters
                        if cutoff:
                            ts = datetime.fromisoformat(record["timestamp"])
                            if ts < cutoff:
                                continue

                        if field and record.get("field") != field:
                            continue

                        if todoist_id and record.get("todoist_id") != todoist_id:
                            continue

                        if winner and record.get("winner") != winner:
                            continue

                        records.append(record)

                    except (json.JSONDecodeError, KeyError):
                        continue

        except Exception as e:
            logger.error(f"Failed to read conflict log: {e}")

        # Return newest first
        return sorted(
            records,
            key=lambda r: r.get("timestamp", ""),
            reverse=True
        )

    def get_conflict_count(self, days: Optional[int] = 7) -> int:
        """Get total number of conflicts in last N days."""
        return len(self.read_conflicts(days=days))

    # ─────────────────────────────────────────────────────────────────────────
    # PRINT SUMMARY
    # ─────────────────────────────────────────────────────────────────────────

    def print_summary(self, days: int = 7) -> None:
        """
        Print a human-readable summary of recent conflicts.

        Args:
            days: Number of days to look back (default 7)
        """
        records = self.read_conflicts(days=days)

        print(f"\n{'=' * 70}")
        print(f"⚡ CONFLICT LOG SUMMARY (last {days} days)")
        print(f"{'=' * 70}")

        if not records:
            print(f"\n  ✅ No conflicts in the last {days} days!")
            print(f"\n{'=' * 70}\n")
            return

        # Stats
        todoist_wins = sum(1 for r in records if r.get("winner") == "todoist")
        notion_wins  = sum(1 for r in records if r.get("winner") == "notion")

        # By field
        field_counts: Dict[str, int] = {}
        for r in records:
            f = r.get("field", "unknown")
            field_counts[f] = field_counts.get(f, 0) + 1

        # By task
        task_counts: Dict[str, int] = {}
        for r in records:
            tid = f"{r.get('todoist_id')} ({r.get('task_title', '')[:30]})"
            task_counts[tid] = task_counts.get(tid, 0) + 1

        print(f"""
  Total conflicts:   {len(records)}
  Todoist won:       {todoist_wins}
  Notion won:        {notion_wins}

  By field:""")
        for field, count in sorted(
            field_counts.items(), key=lambda x: x[1], reverse=True
        ):
            bar = "█" * min(count, 20)
            print(f"    {field:<20} {bar} {count}")

        print(f"\n  Most conflicted tasks:")
        for task, count in sorted(
            task_counts.items(), key=lambda x: x[1], reverse=True
        )[:5]:
            print(f"    • {task}: {count} conflict(s)")

        print(f"\n  Recent conflicts (last 5):")
        for r in records[:5]:
            ts    = r.get("timestamp", "")[:16].replace("T", " ")
            field = r.get("field", "?")
            title = r.get("task_title", "?")[:35]
            win   = r.get("winner", "?")
            t_val = str(r.get("todoist_value", "?"))[:20]
            n_val = str(r.get("notion_value",  "?"))[:20]

            print(f"\n    [{ts}] '{title}'")
            print(f"      Field:   {field}")
            print(f"      Todoist: {t_val}")
            print(f"      Notion:  {n_val}")
            print(f"      Winner:  {win.upper()} ✅")

        print(f"\n  Log file: {self.log_file.absolute()}")
        print(f"{'=' * 70}\n")

    def print_full_log(self, days: int = 30) -> None:
        """Print all conflict records for the last N days."""
        records = self.read_conflicts(days=days)

        print(f"\n{'=' * 70}")
        print(f"⚡ FULL CONFLICT LOG (last {days} days)")
        print(f"{'=' * 70}\n")

        if not records:
            print("  No conflicts found.\n")
            return

        for i, r in enumerate(records, 1):
            ts    = r.get("timestamp", "")[:19].replace("T", " ")
            print(f"  [{i}] {ts}")
            print(f"       Task:    [{r.get('todoist_id')}] "
                  f"{r.get('task_title', '')[:50]}")
            print(f"       Field:   {r.get('field')}")
            print(f"       Todoist: {r.get('todoist_value')} "
                  f"(at {r.get('todoist_ts', 'N/A')[:16]})")
            print(f"       Notion:  {r.get('notion_value')} "
                  f"(at {r.get('notion_ts', 'N/A')[:16]})")
            print(f"       Winner:  {r.get('winner', '?').upper()} → "
                  f"'{r.get('winning_value')}'")
            print(f"       Sync #:  {r.get('sync_count', '?')}")
            print()

        print(f"{'=' * 70}\n")

    # ─────────────────────────────────────────────────────────────────────────
    # FILE MANAGEMENT
    # ─────────────────────────────────────────────────────────────────────────

    def _rotate_if_needed(self) -> None:
        """Rotate log file if it exceeds max size."""
        if not self.log_file.exists():
            return

        if self.log_file.stat().st_size > self.max_size:
            # Rename current to .1, drop older rotations
            rotated = self.log_file.with_suffix(".log.1")
            if rotated.exists():
                rotated.unlink()
            self.log_file.rename(rotated)
            logger.info(
                f"Conflict log rotated: {self.log_file.name} → "
                f"{rotated.name}"
            )

    def clear_log(self, confirm: bool = False) -> None:
        """
        Clear all conflict logs.
        Requires confirm=True to prevent accidental deletion.
        """
        if not confirm:
            print("⚠️  Pass confirm=True to clear the log")
            return
        if self.log_file.exists():
            self.log_file.unlink()
            logger.info("Conflict log cleared")
            print("✅ Conflict log cleared")

    def get_log_size(self) -> str:
        """Get human-readable log file size."""
        if not self.log_file.exists():
            return "0 KB"
        size = self.log_file.stat().st_size
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size / (1024 * 1024):.1f} MB"

    @staticmethod
    def _safe_str(value: object) -> str:
        """Convert value to safe string for JSON storage."""
        if value is None:
            return "None"
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)[:200]  # Cap at 200 chars


# ─────────────────────────────────────────────────────────────────────────────
# CLI USAGE
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import argparse

    parser = argparse.ArgumentParser(
        description="View and manage the sync conflict log"
    )
    parser.add_argument(
        "--summary", "-s",
        action="store_true",
        help="Show conflict summary (default)"
    )
    parser.add_argument(
        "--full", "-f",
        action="store_true",
        help="Show full conflict log"
    )
    parser.add_argument(
        "--days", "-d",
        type=int,
        default=7,
        help="Number of days to look back (default: 7)"
    )
    parser.add_argument(
        "--field",
        type=str,
        help="Filter by field name (e.g. title, priority)"
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear the conflict log"
    )

    args = parser.parse_args()
    cl   = ConflictLogger()

    print(f"\n  Log file: {cl.log_file.absolute()}")
    print(f"  Log size: {cl.get_log_size()}")
    print(f"  Conflicts (last {args.days} days): "
          f"{cl.get_conflict_count(args.days)}")

    if args.clear:
        confirm = input("\n⚠️  Clear all conflict logs? (yes/no): ")
        if confirm.lower() == "yes":
            cl.clear_log(confirm=True)
        else:
            print("Cancelled.")
    elif args.full:
        cl.print_full_log(days=args.days)
    else:
        cl.print_summary(days=args.days)
