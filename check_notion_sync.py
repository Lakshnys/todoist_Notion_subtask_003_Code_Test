"""
check_notion_sync.py
────────────────────
Complete sync verification script.

Checks:
  1. All Todoist tasks (parents + subtasks) exist in Notion
  2. All Notion tasks have valid Todoist IDs
  3. Field-level comparison (title, priority, labels, due date)
  4. Parent-child relationships correctly linked
  5. Local state consistency vs backup
  6. Links present in both systems
  7. Overall health score

Usage:
  python check_notion_sync.py              # Standard check
  python check_notion_sync.py --verbose    # Show all tasks
  python check_notion_sync.py --fix        # Auto-fix by running sync
"""

import re
import sys
import argparse
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

from config import settings
from todoist_api import TodoistClient
from notion_api import NotionClient
from sync_state_manager import SyncStateManager


def extract_links(text: str) -> List[str]:
    if not text:
        return []
    return re.findall(r'https?://[^\s\)\]>\"\']+', text)


def normalize_dt(dt_str: Optional[str]) -> Optional[str]:
    if not dt_str:
        return None
    try:
        from dateutil import parser as dtparser
        dt = dtparser.parse(str(dt_str))
        if dt.tzinfo:
            dt = dt.replace(tzinfo=None)
        return dt.isoformat()
    except Exception:
        return str(dt_str)


def fmt_dt(dt_str: Optional[str]) -> str:
    if not dt_str:
        return "N/A"
    try:
        from dateutil import parser as dtparser
        return dtparser.parse(str(dt_str)).strftime('%Y-%m-%d %H:%M')
    except Exception:
        return str(dt_str)


class SyncChecker:

    def __init__(self, verbose: bool = False):
        self.verbose  = verbose
        self.issues   = []
        self.warnings = []
        self.passed   = []

        print(f"\n{'=' * 78}")
        print("🔍  NOTION ↔ TODOIST SYNC VERIFICATION")
        print(f"    {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'=' * 78}\n")

        print("⚙️   Initializing clients...")
        self.todoist = TodoistClient(settings.todoist_api_token)
        self.notion  = NotionClient(settings.notion_api_token)
        self.state   = SyncStateManager()

        print("📥  Fetching Todoist tasks...")
        self.todoist_tasks = self.todoist.get_all_tasks()

        print("📥  Fetching Notion tasks...")
        self.notion_tasks = self.notion.get_all_tasks()

        self.state_meta   = self.state._get_metadata()
        self.todoist_by_id = {t.id: t for t in self.todoist_tasks}
        self.notion_by_tid = {
            t.todoist_task_id: t
            for t in self.notion_tasks if t.todoist_task_id
        }

        self.todoist_parents  = [t for t in self.todoist_tasks if not t.parent_id]
        self.todoist_subtasks = [t for t in self.todoist_tasks if t.parent_id]
        self.notion_parents   = [t for t in self.notion_tasks if not t.parent_id]
        self.notion_subtasks  = [t for t in self.notion_tasks if t.parent_id]
        self.notion_no_id     = [t for t in self.notion_tasks if not t.todoist_task_id]

        print(f"\n   Todoist: {len(self.todoist_tasks)} tasks "
              f"({len(self.todoist_parents)} parents, "
              f"{len(self.todoist_subtasks)} subtasks)")
        print(f"   Notion:  {len(self.notion_tasks)} tasks "
              f"({len(self.notion_parents)} parents, "
              f"{len(self.notion_subtasks)} subtasks, "
              f"{len(self.notion_no_id)} without Todoist ID)")
        print(f"   State:   {len(self.state.get_all_task_ids())} entries | "
              f"Last sync: {fmt_dt(self.state_meta.get('last_sync_time'))}")

    def check_all(self) -> bool:
        self._check_todoist_in_notion()
        self._check_notion_ids()
        self._check_field_sync()
        self._check_subtask_relationships()
        self._check_state_consistency()
        self._check_links()
        self._check_duplicates()
        return self._print_summary()

    def _check_todoist_in_notion(self):
        print(f"\n\n{'─' * 78}")
        print("📋  CHECK 1: Todoist Tasks → Notion")
        print(f"{'─' * 78}")

        # Only check ACTIVE tasks against Notion
        # Completed tasks are historical - OK to not be in Notion
        active_tasks     = [t for t in self.todoist_tasks if not t.completed]
        completed_tasks  = [t for t in self.todoist_tasks if t.completed]

        print(f"\n  Checking {len(active_tasks)} active tasks "
              f"(skipping {len(completed_tasks)} completed)")

        missing_parents  = []
        missing_subtasks = []
        found = 0

        for task in active_tasks:
            if task.id in self.notion_by_tid:
                found += 1
                if self.verbose:
                    print(f"  ✅ {task.content[:60]}"
                          f"{' (sub)' if task.parent_id else ''}")
            else:
                (missing_subtasks if task.parent_id else missing_parents
                 ).append(task)

        for t in missing_parents:
            msg = f"Active parent missing in Notion: '{t.content}' [{t.id}]"
            self.issues.append(msg)
            print(f"  ❌ {msg}")

        for t in missing_subtasks:
            msg = (f"Active subtask missing in Notion: '{t.content}' "
                   f"[{t.id}] parent: {t.parent_id}")
            self.issues.append(msg)
            print(f"  ❌ {msg}")

        if not missing_parents and not missing_subtasks:
            msg = (f"All {len(active_tasks)} active Todoist tasks "
                   f"found in Notion")
            self.passed.append(msg)
            print(f"  ✅ {msg}")

        if completed_tasks:
            print(f"\n  ℹ️   {len(completed_tasks)} completed tasks "
                  f"not checked (historical - OK)")

        print(f"\n  Result: {found}/{len(active_tasks)} active tasks synced")

    def _check_notion_ids(self):
        print(f"\n\n{'─' * 78}")
        print("📋  CHECK 2: Notion Tasks → Todoist IDs")
        print(f"{'─' * 78}")

        # Separate active and completed tasks
        active_ids    = {t.id for t in self.todoist_tasks if not t.completed}
        completed_ids = {t.id for t in self.todoist_tasks if t.completed}

        no_id       = []
        invalid_id  = []
        completed   = []
        valid       = 0

        for task in self.notion_tasks:
            if not task.todoist_task_id:
                no_id.append(task)
            elif task.todoist_task_id in active_ids:
                valid += 1
                if self.verbose:
                    print(
                        f"  ✅ '{task.title[:50]}' "
                        f"→ [{task.todoist_task_id}]"
                    )
            elif task.todoist_task_id in completed_ids:
                # Task is completed in Todoist - this is fine!
                completed.append(task)
                if self.verbose:
                    print(
                        f"  ✓  '{task.title[:50]}' "
                        f"→ [{task.todoist_task_id}] (completed)"
                    )
            else:
                invalid_id.append(task)
                msg = (
                    f"Truly invalid Todoist ID: '{task.title}' "
                    f"→ [{task.todoist_task_id}]"
                )
                self.issues.append(msg)
                print(f"  ❌ {msg}")

        if no_id:
            msg = f"{len(no_id)} Notion task(s) without Todoist ID (new tasks)"
            self.warnings.append(msg)
            print(f"\n  ⚠️   {msg}:")
            print(f"       Will be created in Todoist on next sync")
            for t in no_id:
                print(f"       • {t.title[:65]}")

        if completed:
            print(
                f"\n  ✓   {len(completed)} Notion task(s) linked to "
                f"COMPLETED Todoist tasks (historical records - OK)"
            )

        if not invalid_id:
            summary = (
                f"{valid} active + {len(completed)} completed "
                f"= {valid + len(completed)} valid IDs"
            )
            self.passed.append(summary)
            if not no_id:
                print(f"\n  ✅ All Notion Todoist IDs are valid")
            else:
                print(f"\n  ✅ All linked Notion tasks have valid IDs")

        print(
            f"\n  Result: {valid} active | {len(completed)} completed | "
            f"{len(no_id)} new | {len(invalid_id)} invalid"
        )

    def _check_field_sync(self):
        print(f"\n\n{'─' * 78}")
        print("📋  CHECK 3: Field-Level Sync")
        print(f"{'─' * 78}")

        mismatches = []
        synced     = 0
        skipped    = 0

        for todoist_id, notion_task in self.notion_by_tid.items():
            todoist_task = self.todoist_by_id.get(todoist_id)
            if not todoist_task:
                continue

            # Skip completed tasks - no need to field-sync historical records
            if todoist_task.completed:
                skipped += 1
                continue

            task_issues = []

            if todoist_task.content.strip() != notion_task.title.strip():
                task_issues.append(
                    f"Title: '{todoist_task.content[:25]}' vs "
                    f"'{notion_task.title[:25]}'"
                )

            if todoist_task.priority != notion_task.priority:
                task_issues.append(
                    f"Priority: {todoist_task.priority} vs "
                    f"{notion_task.priority}"
                )

            if sorted(todoist_task.labels or []) != sorted(notion_task.labels or []):
                task_issues.append(
                    f"Labels: {sorted(todoist_task.labels or [])} vs "
                    f"{sorted(notion_task.labels or [])}"
                )

            t_due = normalize_dt(
                todoist_task.due_datetime.isoformat()
                if todoist_task.due_datetime else None
            )
            n_due = normalize_dt(
                notion_task.due_date.isoformat()
                if notion_task.due_date else None
            )
            if t_due != n_due:
                task_issues.append(f"Due: '{t_due}' vs '{n_due}'")

            if todoist_task.completed != notion_task.completed:
                task_issues.append(
                    f"Completed: {todoist_task.completed} vs "
                    f"{notion_task.completed}"
                )

            if task_issues:
                mismatches.append((todoist_task, notion_task, task_issues))
                print(f"\n  ⚠️   '{todoist_task.content[:55]}'")
                for issue in task_issues:
                    print(f"       • {issue}")
            else:
                synced += 1
                if self.verbose:
                    print(f"  ✅ '{todoist_task.content[:60]}'")

        if not mismatches:
            msg = f"All {synced} active tasks have matching fields"
            self.passed.append(msg)
            print(f"  ✅ {msg}")
        else:
            msg = f"{len(mismatches)} task(s) have field mismatches"
            self.warnings.append(msg)
            print(f"\n  ⚠️   {msg} (run sync to fix)")

        if skipped:
            print(f"\n  ℹ️   {skipped} completed tasks skipped (historical)")

        print(f"\n  Result: {synced}/{synced + len(mismatches)} active tasks in sync")

    def _check_subtask_relationships(self):
        print(f"\n\n{'─' * 78}")
        print("📋  CHECK 4: Parent-Child Relationships")
        print(f"{'─' * 78}")

        # Only check ACTIVE subtasks
        active_subtasks = [t for t in self.todoist_subtasks if not t.completed]
        skipped         = len(self.todoist_subtasks) - len(active_subtasks)

        print(f"\n  Checking {len(active_subtasks)} active subtasks "
              f"(skipping {skipped} completed)")

        orphaned     = []
        wrong_parent = []
        correct      = 0

        for task in active_subtasks:
            notion_task = self.notion_by_tid.get(task.id)
            if not notion_task:
                continue

            if task.parent_id not in self.notion_by_tid:
                # Check if parent is completed (OK) or truly missing
                parent_task = self.todoist_by_id.get(task.parent_id)
                if parent_task and parent_task.completed:
                    # Parent is completed - this is an edge case
                    if self.verbose:
                        print(f"  ℹ️   '{task.content[:40]}' parent is completed")
                else:
                    orphaned.append(task)
                    msg = (f"Active subtask '{task.content}' has parent "
                           f"[{task.parent_id}] not in Notion")
                    self.issues.append(msg)
                    print(f"  ❌ Orphaned: {msg}")
            elif notion_task.parent_id != task.parent_id:
                wrong_parent.append((task, notion_task))
                msg = (f"Parent mismatch '{task.content}': "
                       f"Todoist=[{task.parent_id}] "
                       f"Notion=[{notion_task.parent_id}]")
                self.warnings.append(msg)
                print(f"  ⚠️   {msg}")
            else:
                correct += 1
                if self.verbose:
                    parent = self.todoist_by_id.get(task.parent_id)
                    pname  = parent.content[:30] if parent else task.parent_id
                    print(f"  ✅ '{task.content[:40]}' → parent: '{pname}'")

        if not orphaned and not wrong_parent:
            msg = (f"All {len(active_subtasks)} active subtask "
                   f"relationships correct")
            self.passed.append(msg)
            print(f"  ✅ {msg}")

        print(f"\n  Result: {correct}/{len(active_subtasks)} correct | "
              f"Orphaned: {len(orphaned)} | Wrong: {len(wrong_parent)}")

    def _check_state_consistency(self):
        print(f"\n\n{'─' * 78}")
        print("📋  CHECK 5: Local State Consistency")
        print(f"{'─' * 78}")

        state_ids   = set(self.state.get_all_task_ids())
        todoist_ids = set(self.todoist_by_id.keys())

        # Active and completed IDs
        active_ids    = {t.id for t in self.todoist_tasks if not t.completed}
        completed_ids = {t.id for t in self.todoist_tasks if t.completed}
        all_todoist   = active_ids | completed_ids

        missing_from_state = todoist_ids - state_ids
        # Only flag as stale if not a completed task
        truly_stale = state_ids - all_todoist
        meta = self.state._get_metadata()

        print(f"\n  📊 Metadata:")
        print(f"     Schema:        {meta.get('schema_version', 'unknown')}")
        print(f"     Initial done:  {meta.get('is_initial_sync_done', False)}")
        print(f"     Sync count:    {meta.get('sync_count', 0)}")
        print(f"     Last sync:     {fmt_dt(meta.get('last_sync_time'))}")
        print(f"     Total entries: {len(state_ids)}")

        tasks_with_notion_id = sum(
            1 for tid in state_ids
            if self.state.get_notion_page_id(tid)
        )
        print(f"     With Notion ID:{tasks_with_notion_id}/{len(state_ids)}")

        if missing_from_state:
            msg = (f"{len(missing_from_state)} Todoist tasks not yet "
                   f"in local state")
            self.warnings.append(msg)
            print(f"\n  ⚠️   {msg} (added on next sync)")

        # Show completed tasks in state (these are OK)
        completed_in_state = state_ids & completed_ids
        if completed_in_state:
            print(
                f"\n  ✓   {len(completed_in_state)} completed task(s) "
                f"in state (historical records - OK)"
            )

        # Only flag truly stale (not completed, not in Todoist at all)
        if truly_stale:
            msg = (f"{len(truly_stale)} truly stale entries "
                   f"(tasks deleted from Todoist entirely)")
            self.warnings.append(msg)
            print(f"  ⚠️   {msg}")

        if not missing_from_state and not truly_stale:
            msg = "Local state fully consistent with Todoist"
            self.passed.append(msg)
            print(f"\n  ✅ {msg}")

    def _check_links(self):
        print(f"\n\n{'─' * 78}")
        print("📋  CHECK 6: Tasks with Links")
        print(f"{'─' * 78}")

        tasks_with_links = [
            (t, extract_links(t.content) + extract_links(t.description or ""))
            for t in self.todoist_tasks
            if extract_links(t.content) or extract_links(t.description or "")
        ]

        if not tasks_with_links:
            print("  ℹ️   No tasks with links found")
            self.passed.append("No link tasks to verify")
            return

        print(f"\n  Found {len(tasks_with_links)} task(s) with links:\n")

        all_ok = True
        for task, links in tasks_with_links:
            notion_task = self.notion_by_tid.get(task.id)
            status      = "✅" if notion_task else "❌"
            is_sub      = " (subtask)" if task.parent_id else ""
            print(f"  {status} '{task.content[:55]}'{is_sub}")

            for link in links[:3]:
                print(f"       🔗 {link[:72]}")

            if notion_task:
                notion_links = (
                    extract_links(notion_task.title) +
                    extract_links(notion_task.description or "")
                )
                missing = [l for l in links if l not in notion_links]
                if missing:
                    all_ok = False
                    for ml in missing:
                        msg = f"Link missing in Notion: {ml[:60]}"
                        self.warnings.append(msg)
                        print(f"       ⚠️  Not in Notion: {ml[:65]}")
                else:
                    print(f"       ✅ All links synced")
            print()

        if all_ok:
            self.passed.append(
                f"All links from {len(tasks_with_links)} tasks synced"
            )

    def _check_duplicates(self):
        print(f"\n\n{'─' * 78}")
        print("📋  CHECK 7: Duplicate Notion Pages")
        print(f"{'─' * 78}")

        from collections import defaultdict
        by_todoist_id = defaultdict(list)

        for task in self.notion_tasks:
            if task.todoist_task_id:
                by_todoist_id[task.todoist_task_id].append(task)

        duplicates = {
            tid: pages
            for tid, pages in by_todoist_id.items()
            if len(pages) > 1
        }

        if not duplicates:
            msg = "No duplicate Notion pages found"
            self.passed.append(msg)
            print(f"  ✅ {msg}")
        else:
            total_dupes = sum(len(p) - 1 for p in duplicates.values())
            msg = (f"{len(duplicates)} duplicate group(s) found "
                   f"({total_dupes} extra pages)")
            self.issues.append(msg)
            print(f"  ❌ {msg}")
            for tid, pages in duplicates.items():
                print(f"\n  Todoist ID: [{tid}]")
                for p in pages:
                    print(f"    • [{p.id}] '{p.title[:50]}'")
            print(f"\n  Fix: python find_duplicates.py --fix")

        print(f"\n  Result: {len(duplicates)} duplicate groups")

    def _print_summary(self) -> bool:
        total = len(self.passed) + len(self.warnings) + len(self.issues)
        score = (len(self.passed) / total * 100) if total > 0 else 100

        icon = ("🟢" if score == 100 else
                "🟡" if score >= 80 else
                "🟠" if score >= 60 else "🔴")
        text = ("EXCELLENT" if score == 100 else
                "GOOD"      if score >= 80 else
                "FAIR"      if score >= 60 else "NEEDS ATTENTION")

        state_ids = self.state.get_all_task_ids()

        print(f"\n\n{'=' * 78}")
        print("📊  SYNC HEALTH REPORT")
        print(f"{'=' * 78}")
        print(f"""
  {icon}  Health Score: {score:.0f}% - {text}

  ┌─────────────────────────────────────────────────┐
  │  TODOIST                                        │
  │    Total:      {len(self.todoist_tasks):<5}  Parents: {len(self.todoist_parents):<5}  Subtasks: {len(self.todoist_subtasks):<5} │
  ├─────────────────────────────────────────────────┤
  │  NOTION                                         │
  │    Total:      {len(self.notion_tasks):<5}  Parents: {len(self.notion_parents):<5}  Subtasks: {len(self.notion_subtasks):<5} │
  │    No ID:      {len(self.notion_no_id):<5}                               │
  ├─────────────────────────────────────────────────┤
  │  LOCAL STATE                                    │
  │    Entries:    {len(state_ids):<5}                               │
  │    Last sync:  {fmt_dt(self.state_meta.get('last_sync_time')):<20}             │
  │    Sync count: {self.state_meta.get('sync_count', 0):<5}                               │
  ├─────────────────────────────────────────────────┤
  │  CHECKS                                         │
  │    ✅ Passed:  {len(self.passed):<5}                               │
  │    ⚠️  Warnings:{len(self.warnings):<5}                               │
  │    ❌ Issues:  {len(self.issues):<5}                               │
  └─────────────────────────────────────────────────┘""")

        if self.passed:
            print(f"\n  ✅ PASSED:")
            for p in self.passed:
                print(f"     • {p}")

        if self.warnings:
            print(f"\n  ⚠️   WARNINGS:")
            for w in self.warnings:
                print(f"     • {w}")

        if self.issues:
            print(f"\n  ❌ ISSUES:")
            for issue in self.issues:
                print(f"     • {issue}")

        print(f"\n  💡 NEXT STEPS:")
        if not self.issues and not self.warnings:
            print("     🎉 System perfectly healthy - no action needed!")
        else:
            if self.issues or self.warnings:
                print("     → Run sync to fix:  python main.py")
            if self.notion_no_id:
                print(f"     → {len(self.notion_no_id)} new Notion task(s) "
                      f"will sync to Todoist automatically")

        print(f"\n{'=' * 78}\n")
        return len(self.issues) == 0


def main():
    parser = argparse.ArgumentParser(
        description="Verify Todoist ↔ Notion sync health"
    )
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Show all tasks')
    parser.add_argument('--fix', action='store_true',
                        help='Auto-fix by running sync')
    args = parser.parse_args()

    checker = SyncChecker(verbose=args.verbose)
    ok      = checker.check_all()

    if args.fix and not ok:
        print("\n🔧  Running sync to fix issues...")
        from sync_engine import SyncEngine
        engine = SyncEngine(checker.todoist, checker.notion)
        engine.run_sync()
        print("\n🔁  Re-checking after fix...\n")
        SyncChecker(verbose=args.verbose).check_all()

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
