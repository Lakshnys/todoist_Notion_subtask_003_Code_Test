"""
Enhanced Subtask Diagnostic Script

Compares parent tasks and subtasks between:
- Todoist (source of truth)
- Notion (sync target)
- Backup state (sync_state.json)

Shows exactly what's happening with subtasks and what needs fixing.
"""

import json
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

from config import settings
from todoist_api import TodoistClient
from notion_api import NotionClient


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def has_link(text: str) -> bool:
    """Check if text contains a URL."""
    return bool(text and ('http://' in text or 'https://' in text))


def extract_links(text: str) -> List[str]:
    """Extract all URLs from text."""
    if not text:
        return []
    return re.findall(r'https?://[^\s\)\]>]+', text)


def load_backup_state() -> Dict:
    """Load backup state from sync_state.json."""
    state_file = Path("sync_state.json")
    if not state_file.exists():
        print("⚠️  No sync_state.json found - backup comparison unavailable")
        return {}
    try:
        with open(state_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️  Failed to load sync_state.json: {e}")
        return {}


def format_datetime(dt_str: Optional[str]) -> str:
    """Format datetime string for display."""
    if not dt_str:
        return "N/A"
    try:
        dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return str(dt_str)


# ─────────────────────────────────────────────
# SECTION 1: TODOIST ANALYSIS
# ─────────────────────────────────────────────

def analyse_todoist(tasks) -> Tuple[Dict, Dict, Dict]:
    """
    Separate tasks into parents and subtasks.

    Returns:
        parents     - {task_id: task}
        subtasks    - {task_id: task}
        children    - {parent_id: [task, ...]}
    """
    parents  = {}
    subtasks = {}
    children = defaultdict(list)

    for task in tasks:
        if task.parent_id:
            subtasks[task.id] = task
            children[task.parent_id].append(task)
        else:
            parents[task.id] = task

    return parents, subtasks, children


def print_todoist_tree(parents, children):
    """Print Todoist task tree with subtasks."""
    print("\n" + "=" * 80)
    print("📋 TODOIST TASK TREE")
    print("=" * 80)

    for task_id, task in parents.items():
        link_flag = "🔗" if has_link(task.content) or has_link(task.description) else "  "
        print(f"\n{link_flag} 📌 [{task_id}] {task.content}")

        if task.description:
            print(f"      Description: {task.description[:80]}")
        if task.due_datetime:
            print(f"      Due: {task.due_datetime}")
        if task.labels:
            print(f"      Labels: {', '.join(task.labels)}")

        # Print subtasks
        subs = children.get(task_id, [])
        if subs:
            for sub in subs:
                sub_link = "🔗" if has_link(sub.content) or has_link(sub.description) else "  "
                print(f"      {sub_link} └── [{sub.id}] {sub.content}")
                if sub.description:
                    print(f"               Description: {sub.description[:60]}")
                if sub.due_datetime:
                    print(f"               Due: {sub.due_datetime}")
        else:
            print(f"      └── (no subtasks)")

    print()


# ─────────────────────────────────────────────
# SECTION 2: NOTION ANALYSIS
# ─────────────────────────────────────────────

def analyse_notion(tasks) -> Tuple[Dict, Dict, Dict]:
    """
    Separate Notion tasks into parents and subtasks.

    Returns:
        by_todoist_id  - {todoist_id: notion_task}
        parents        - {notion_id: task}  (no parent)
        subtasks       - {notion_id: task}  (has parent)
    """
    by_todoist_id = {}
    parents  = {}
    subtasks = {}

    for task in tasks:
        if task.todoist_task_id:
            by_todoist_id[task.todoist_task_id] = task

        if task.parent_id:
            subtasks[task.id] = task
        else:
            parents[task.id] = task

    return by_todoist_id, parents, subtasks


def print_notion_tree(notion_tasks, notion_by_todoist_id):
    """Print Notion task tree."""
    print("\n" + "=" * 80)
    print("📓 NOTION TASK TREE")
    print("=" * 80)

    # Group by parent
    notion_parents  = [t for t in notion_tasks if not t.parent_id]
    notion_subtasks = [t for t in notion_tasks if t.parent_id]

    # Build index: todoist_parent_id → [notion_subtask]
    subs_by_parent = defaultdict(list)
    for sub in notion_subtasks:
        subs_by_parent[sub.parent_id].append(sub)

    for task in notion_parents:
        link_flag = "🔗" if has_link(task.title) or has_link(task.description) else "  "
        todoist_ref = f"[Todoist: {task.todoist_task_id}]" if task.todoist_task_id else "[No Todoist ID]"
        print(f"\n{link_flag} 📌 {todoist_ref} {task.title}")

        if task.description:
            print(f"      Description: {task.description[:80]}")

        # Subtasks under this parent
        subs = subs_by_parent.get(task.todoist_task_id, [])
        if subs:
            for sub in subs:
                sub_link = "🔗" if has_link(sub.title) else "  "
                print(f"      {sub_link} └── [Todoist: {sub.todoist_task_id}] {sub.title}")
        else:
            print(f"      └── (no subtasks in Notion)")

    print()


# ─────────────────────────────────────────────
# SECTION 3: SYNC COMPARISON
# ─────────────────────────────────────────────

def compare_sync(
    todoist_parents, todoist_subtasks, todoist_children,
    notion_by_todoist_id, backup_state
):
    """Compare Todoist vs Notion vs Backup and show differences."""

    print("\n" + "=" * 80)
    print("🔍 SYNC COMPARISON REPORT")
    print("=" * 80)

    # ── 3.1 Parent Task Sync Status ──────────────────────────────
    print("\n📌 PARENT TASKS")
    print("-" * 80)

    missing_parents  = []
    synced_parents   = []
    changed_parents  = []

    for tid, task in todoist_parents.items():
        notion_task  = notion_by_todoist_id.get(tid)
        backup_entry = backup_state.get(tid, {})
        last_sync    = backup_entry.get('last_sync_time')

        if not notion_task:
            missing_parents.append(task)
            print(f"  ❌ MISSING  [{tid}] {task.content}")
        else:
            # Check for changes since backup
            changes = detect_changes(task, notion_task, backup_entry)
            if changes:
                changed_parents.append((task, notion_task, changes))
                print(f"  ⚠️  CHANGED  [{tid}] {task.content}")
                for change in changes:
                    print(f"              → {change}")
            else:
                synced_parents.append(task)
                print(f"  ✅ SYNCED   [{tid}] {task.content}")

            if last_sync:
                print(f"              Last sync: {format_datetime(last_sync)}")

    # ── 3.2 Subtask Sync Status ───────────────────────────────────
    print("\n\n🔗 SUBTASKS")
    print("-" * 80)

    missing_subtasks = []
    synced_subtasks  = []
    changed_subtasks = []
    orphan_subtasks  = []

    for tid, task in todoist_subtasks.items():
        notion_task  = notion_by_todoist_id.get(tid)
        backup_entry = backup_state.get(tid, {})
        last_sync    = backup_entry.get('last_sync_time')

        # Check if parent is synced
        parent_in_notion = notion_by_todoist_id.get(task.parent_id)

        if not parent_in_notion:
            orphan_subtasks.append(task)
            print(f"  🚫 ORPHAN   [{tid}] {task.content}")
            print(f"              Parent [{task.parent_id}] not in Notion!")
            continue

        if not notion_task:
            missing_subtasks.append(task)
            print(f"  ❌ MISSING  [{tid}] {task.content}")
            print(f"              Parent: [{task.parent_id}]")
        else:
            changes = detect_changes(task, notion_task, backup_entry)
            if changes:
                changed_subtasks.append((task, notion_task, changes))
                print(f"  ⚠️  CHANGED  [{tid}] {task.content}")
                for change in changes:
                    print(f"              → {change}")
            else:
                synced_subtasks.append(task)
                print(f"  ✅ SYNCED   [{tid}] {task.content}")

            # Verify Parent Task link in Notion
            if notion_task.parent_id != task.parent_id:
                print(f"  ⚠️  PARENT MISMATCH!")
                print(f"      Todoist parent: {task.parent_id}")
                print(f"      Notion parent:  {notion_task.parent_id}")

            if last_sync:
                print(f"              Last sync: {format_datetime(last_sync)}")

    return (
        missing_parents, synced_parents, changed_parents,
        missing_subtasks, synced_subtasks, changed_subtasks,
        orphan_subtasks
    )


def detect_changes(todoist_task, notion_task, backup_entry) -> List[str]:
    """
    Detect changes between Todoist, Notion and backup state.
    Uses backup last_sync_time as reference point.
    Returns list of human-readable change descriptions.
    """
    changes = []
    last_sync = backup_entry.get('last_sync_time')

    # Title
    t_title = todoist_task.content
    n_title = notion_task.title
    b_title = backup_entry.get('title')

    if t_title != n_title:
        changes.append(f"Title: Todoist='{t_title}' vs Notion='{n_title}'")
    elif b_title and t_title != b_title:
        changes.append(f"Title changed since backup: '{b_title}' → '{t_title}'")

    # Description
    t_desc = todoist_task.description or ""
    n_desc = notion_task.description or ""
    b_desc = backup_entry.get('description') or ""

    if t_desc != n_desc:
        changes.append(f"Description differs between systems")
    elif b_desc and t_desc != b_desc:
        changes.append(f"Description changed since backup")

    # Priority
    t_priority = todoist_task.priority
    n_priority = notion_task.priority
    b_priority = backup_entry.get('priority')

    if t_priority != n_priority:
        changes.append(f"Priority: Todoist={t_priority} vs Notion={n_priority}")

    # Completed
    t_done = todoist_task.completed
    n_done = notion_task.completed
    if t_done != n_done:
        changes.append(f"Completed: Todoist={t_done} vs Notion={n_done}")

    # Labels
    t_labels = sorted(todoist_task.labels or [])
    n_labels = sorted(notion_task.labels or [])
    if t_labels != n_labels:
        changes.append(f"Labels: Todoist={t_labels} vs Notion={n_labels}")

    return changes


# ─────────────────────────────────────────────
# SECTION 4: LINKS REPORT
# ─────────────────────────────────────────────

def print_links_report(todoist_tasks, notion_by_todoist_id):
    """Show all tasks with links and their sync status."""
    print("\n" + "=" * 80)
    print("🔗 TASKS WITH LINKS")
    print("=" * 80)

    tasks_with_links = []
    for task in todoist_tasks:
        links = extract_links(task.content) + extract_links(task.description or "")
        if links:
            tasks_with_links.append((task, links))

    if not tasks_with_links:
        print("\n  No tasks with links found in Todoist.\n")
        return

    print(f"\n  Found {len(tasks_with_links)} task(s) with links:\n")

    for task, links in tasks_with_links:
        notion_task = notion_by_todoist_id.get(task.id)
        is_sub = "└──" if task.parent_id else "📌"
        sync_status = "✅ Synced" if notion_task else "❌ Missing"

        print(f"  {is_sub} [{task.id}] {task.content[:60]}")
        print(f"       Status: {sync_status}")
        for link in links:
            print(f"       🔗 {link}")

        if notion_task:
            # Check links in Notion
            notion_links = (
                extract_links(notion_task.title) +
                extract_links(notion_task.description or "")
            )
            missing = [l for l in links if l not in notion_links]
            if missing:
                print(f"       ⚠️  Links missing in Notion:")
                for ml in missing:
                    print(f"          ❌ {ml}")
            else:
                print(f"       ✅ All links present in Notion")
        print()


# ─────────────────────────────────────────────
# SECTION 5: FINAL SUMMARY
# ─────────────────────────────────────────────

def print_summary(
    todoist_tasks, notion_tasks,
    todoist_parents, todoist_subtasks,
    missing_parents, synced_parents, changed_parents,
    missing_subtasks, synced_subtasks, changed_subtasks,
    orphan_subtasks
):
    """Print final summary with counts and recommendations."""
    print("\n" + "=" * 80)
    print("📊 FINAL SUMMARY")
    print("=" * 80)

    print(f"""
┌─────────────────────────────────────────────┐
│           TODOIST                           │
│  Total tasks:      {len(todoist_tasks):<5}                    │
│  Parent tasks:     {len(todoist_parents):<5}                    │
│  Subtasks:         {len(todoist_subtasks):<5}                    │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│           NOTION                            │
│  Total tasks:      {len(notion_tasks):<5}                    │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│           PARENT TASK SYNC                  │
│  ✅ Synced:        {len(synced_parents):<5}                    │
│  ⚠️  Changed:       {len(changed_parents):<5}                    │
│  ❌ Missing:       {len(missing_parents):<5}                    │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│           SUBTASK SYNC                      │
│  ✅ Synced:        {len(synced_subtasks):<5}                    │
│  ⚠️  Changed:       {len(changed_subtasks):<5}                    │
│  ❌ Missing:       {len(missing_subtasks):<5}                    │
│  🚫 Orphaned:      {len(orphan_subtasks):<5}                    │
└─────────────────────────────────────────────┘
""")

    # Recommendations
    print("💡 RECOMMENDATIONS")
    print("-" * 80)

    if not missing_parents and not missing_subtasks and not changed_parents and not changed_subtasks:
        print("\n  ✅ Everything is in sync! No action needed.\n")
        return

    if missing_parents:
        print(f"\n  ❌ {len(missing_parents)} parent task(s) missing in Notion:")
        for task in missing_parents:
            print(f"     • [{task.id}] {task.content}")
        print("     → Action: Run sync to create these in Notion")

    if missing_subtasks:
        print(f"\n  ❌ {len(missing_subtasks)} subtask(s) missing in Notion:")
        for task in missing_subtasks:
            print(f"     • [{task.id}] {task.content} (parent: {task.parent_id})")
        print("     → Action: Subtask sync needs to be implemented")

    if changed_parents:
        print(f"\n  ⚠️  {len(changed_parents)} parent task(s) have changes:")
        for task, notion_task, changes in changed_parents:
            print(f"     • [{task.id}] {task.content}")
        print("     → Action: Run sync to update these")

    if changed_subtasks:
        print(f"\n  ⚠️  {len(changed_subtasks)} subtask(s) have changes:")
        for task, notion_task, changes in changed_subtasks:
            print(f"     • [{task.id}] {task.content}")
        print("     → Action: Subtask sync needs to be implemented")

    if orphan_subtasks:
        print(f"\n  🚫 {len(orphan_subtasks)} subtask(s) are orphaned (parent not in Notion):")
        for task in orphan_subtasks:
            print(f"     • [{task.id}] {task.content}")
        print("     → Action: Sync parent tasks first")

    print()
    print("=" * 80)
    print("\n🔧 NEXT STEPS:")
    print("  1. Review the report above")
    print("  2. Share findings so we can proceed with interactive sync build")
    print("  3. We will implement subtask sync step by step")
    print()


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    print("\n" + "=" * 80)
    print("🔍 ENHANCED SUBTASK DIAGNOSTIC")
    print(f"   Run at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    # 1. Initialize clients
    print("\n⚙️  Initializing API clients...")
    todoist_client = TodoistClient(settings.todoist_api_token)
    notion_client  = NotionClient(settings.notion_api_token)

    # 2. Fetch data
    print("\n📥 Fetching data from Todoist...")
    todoist_tasks = todoist_client.get_all_tasks()
    print(f"   Found {len(todoist_tasks)} total tasks")

    print("\n📥 Fetching data from Notion...")
    notion_tasks = notion_client.get_all_tasks()
    print(f"   Found {len(notion_tasks)} total tasks")

    print("\n📥 Loading backup state...")
    backup_state = load_backup_state()
    print(f"   Found {len(backup_state)} entries in backup")

    # 3. Analyse
    todoist_parents, todoist_subtasks, todoist_children = analyse_todoist(todoist_tasks)
    notion_by_todoist_id, notion_parents, notion_subtasks = analyse_notion(notion_tasks)

    print(f"\n   Todoist → Parents: {len(todoist_parents)} | Subtasks: {len(todoist_subtasks)}")
    print(f"   Notion  → Parents: {len(notion_parents)} | Subtasks: {len(notion_subtasks)}")

    # 4. Print trees
    print_todoist_tree(todoist_parents, todoist_children)
    print_notion_tree(notion_tasks, notion_by_todoist_id)

    # 5. Compare
    results = compare_sync(
        todoist_parents, todoist_subtasks, todoist_children,
        notion_by_todoist_id, backup_state
    )

    # 6. Links report
    print_links_report(todoist_tasks, notion_by_todoist_id)

    # 7. Summary
    print_summary(
        todoist_tasks, notion_tasks,
        todoist_parents, todoist_subtasks,
        *results
    )


if __name__ == "__main__":
    main()
