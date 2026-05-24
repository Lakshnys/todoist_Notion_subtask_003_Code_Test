"""
find_duplicates.py
──────────────────
Finds Notion pages with duplicate Todoist Task IDs.
Shows details of each duplicate so you can decide
which one to keep and which to delete.

Usage:
  python find_duplicates.py          # Find duplicates
  python find_duplicates.py --fix    # Auto-fix (keep newer, archive older)
"""

import argparse
from collections import defaultdict
from datetime import datetime
from notion_client import Client
from config import settings
from notion_api import NotionClient

client = Client(auth=settings.notion_api_token)
notion = NotionClient(settings.notion_api_token)

print("\n" + "=" * 70)
print("🔍 NOTION DUPLICATE TASK FINDER")
print("=" * 70)

# ── Fetch all Notion tasks ────────────────────────────────────────────────────
print("\n📥 Fetching all Notion tasks...")
tasks = notion.get_all_tasks()
print(f"   Total tasks: {len(tasks)}")

# ── Group by Todoist ID ───────────────────────────────────────────────────────
by_todoist_id = defaultdict(list)
no_id_tasks   = []

for task in tasks:
    if task.todoist_task_id:
        by_todoist_id[task.todoist_task_id].append(task)
    else:
        no_id_tasks.append(task)

# ── Find duplicates ───────────────────────────────────────────────────────────
duplicates = {
    tid: pages
    for tid, pages in by_todoist_id.items()
    if len(pages) > 1
}

print(f"   Tasks with Todoist ID: {len(by_todoist_id)}")
print(f"   Tasks without ID:      {len(no_id_tasks)}")
print(f"   Duplicate groups:      {len(duplicates)}")

if not duplicates:
    print("\n✅ No duplicates found! All Todoist IDs are unique.")
    exit(0)

# ── Show duplicates ───────────────────────────────────────────────────────────
print(f"\n{'─' * 70}")
print(f"⚠️  DUPLICATES FOUND: {len(duplicates)} group(s)")
print(f"{'─' * 70}")

to_delete = []  # Pages recommended for deletion
to_keep   = []  # Pages recommended to keep

for todoist_id, pages in duplicates.items():
    print(f"\n  Todoist ID: [{todoist_id}]")
    print(f"  Copies:     {len(pages)}")
    print()

    # Sort by last_modified_time (newest first)
    def get_ts(task):
        if task.last_modified_time:
            ts = task.last_modified_time
            if hasattr(ts, 'tzinfo') and ts.tzinfo:
                ts = ts.replace(tzinfo=None)
            return ts
        return datetime.min

    sorted_pages = sorted(pages, key=get_ts, reverse=True)

    for i, page in enumerate(sorted_pages):
        ts     = get_ts(page)
        status = "✅ KEEP (newest)"   if i == 0 else "❌ DELETE (older)"
        marker = "→" if i == 0 else " "

        print(f"  {marker} [{i+1}] {status}")
        print(f"      Page ID:      {page.id}")
        print(f"      Title:        {page.title[:55]}")
        print(f"      Description:  {(page.description or 'None')[:40]}")
        print(f"      Last edited:  {ts}")
        print(f"      Completed:    {page.completed}")
        print(f"      Parent ID:    {page.parent_id or 'None'}")
        print()

        if i == 0:
            to_keep.append(page)
        else:
            to_delete.append(page)

# ── Summary ───────────────────────────────────────────────────────────────────
print(f"{'=' * 70}")
print(f"📊 SUMMARY")
print(f"{'=' * 70}")
print(f"\n  Pages to KEEP:   {len(to_keep)}")
print(f"  Pages to DELETE: {len(to_delete)}")

print(f"\n  Pages recommended for deletion:")
for page in to_delete:
    print(f"    ❌ [{page.id}] '{page.title[:50]}'")

print(f"""
  STRATEGY: Keep NEWEST version (most recently edited)
  → Preserves latest changes from either system
  → Deletes older duplicate
""")

# ── Auto-fix option ───────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument('--fix', action='store_true',
                    help='Auto-fix: archive duplicate pages')
parser.add_argument('--delete', action='store_true',
                    help='Hard delete duplicates (cannot be undone!)')
args, _ = parser.parse_known_args()

if args.fix or args.delete:
    print(f"\n{'─' * 70}")
    action = "DELETING" if args.delete else "ARCHIVING"
    print(f"🔧 {action} {len(to_delete)} duplicate page(s)...")
    print(f"{'─' * 70}")

    fixed  = 0
    failed = 0

    for page in to_delete:
        try:
            if args.delete:
                # Hard delete (moves to Notion trash)
                client.pages.update(
                    page_id    = page.id,
                    in_trash   = True
                )
                print(f"  🗑️  Deleted: '{page.title[:50]}' [{page.id}]")
            else:
                # Archive (soft delete - can be recovered)
                client.pages.update(
                    page_id  = page.id,
                    archived = True
                )
                print(f"  📦 Archived: '{page.title[:50]}' [{page.id}]")
            fixed += 1

        except Exception as e:
            print(f"  ❌ Failed [{page.id}]: {e}")
            failed += 1

    print(f"\n  ✅ Fixed:  {fixed}")
    print(f"  ❌ Failed: {failed}")

    if fixed > 0:
        print(f"\n  💡 Run check_notion_sync.py to verify health")

else:
    print(f"""
{'─' * 70}
💡 HOW TO FIX:
{'─' * 70}

Option 1: ARCHIVE duplicates (recommended - recoverable)
  python find_duplicates.py --fix

Option 2: HARD DELETE duplicates (permanent)
  python find_duplicates.py --delete

Option 3: Manual fix in Notion
  → Open each duplicate page listed above
  → Delete the OLDER one manually
  → Keep the NEWER one

⚠️  Always run a backup first:
  python main.py --backup
{'─' * 70}
""")
