"""
fix_duplicates.py
─────────────────
Finds ALL Notion pages sharing the same Todoist Task ID.
Keeps the NEWEST (by last_edited_time), archives the rest.
Runs automatically - no prompts needed.
"""

from collections import defaultdict
from datetime import datetime
from notion_client import Client
from config import settings

client = Client(auth=settings.notion_api_token)
DB_ID  = settings.notion_database_id

print("\n" + "=" * 70)
print("🔍 COMPREHENSIVE DUPLICATE FINDER & FIXER")
print("=" * 70)

# ── Fetch ALL pages directly from Notion API (raw) ────────────────────────────
print("\n📥 Fetching ALL Notion pages (raw API)...")

all_pages    = []
has_more     = True
start_cursor = None

while has_more:
    kwargs = {"database_id": DB_ID, "page_size": 100}
    if start_cursor:
        kwargs["start_cursor"] = start_cursor

    response     = client.databases.query(**kwargs)
    all_pages.extend(response.get("results", []))
    has_more     = response.get("has_more", False)
    start_cursor = response.get("next_cursor")

print(f"   Total pages fetched: {len(all_pages)}")

# ── Extract Todoist Task ID from each page ────────────────────────────────────
def get_todoist_id(page):
    props = page.get("properties", {})
    rt    = props.get("Todoist Task ID", {}).get("rich_text", [])
    return rt[0]["text"]["content"] if rt else None

def get_title(page):
    props      = page.get("properties", {})
    title_list = props.get("Title", {}).get("title", [])
    return title_list[0]["text"]["content"] if title_list else "(no title)"

def get_last_edited(page):
    ts = page.get("last_edited_time", "")
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.replace(tzinfo=None)
    except Exception:
        return datetime.min

def get_created(page):
    ts = page.get("created_time", "")
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.replace(tzinfo=None)
    except Exception:
        return datetime.min

# ── Group by Todoist Task ID ──────────────────────────────────────────────────
by_todoist_id = defaultdict(list)
no_id_pages   = []

for page in all_pages:
    tid = get_todoist_id(page)
    if tid:
        by_todoist_id[tid].append(page)
    else:
        no_id_pages.append(page)

# ── Find duplicates ───────────────────────────────────────────────────────────
duplicates = {
    tid: pages
    for tid, pages in by_todoist_id.items()
    if len(pages) > 1
}

print(f"   Unique Todoist IDs:  {len(by_todoist_id)}")
print(f"   Pages without ID:   {len(no_id_pages)}")
print(f"   Duplicate groups:   {len(duplicates)}")

if not duplicates:
    print("\n✅ No duplicates found! All Todoist IDs are unique.")
    exit(0)

# ── Show and fix duplicates ───────────────────────────────────────────────────
print(f"\n{'─' * 70}")
print(f"⚠️  DUPLICATES FOUND")
print(f"{'─' * 70}")

total_archived = 0
total_failed   = 0

for todoist_id, pages in duplicates.items():

    # Sort by last_edited_time DESCENDING (newest first)
    sorted_pages = sorted(pages, key=get_last_edited, reverse=True)

    keep   = sorted_pages[0]
    remove = sorted_pages[1:]

    print(f"\n  Todoist ID: [{todoist_id}]")
    print(f"  Copies:     {len(pages)}")
    print()
    print(f"  ✅ KEEP:   '{get_title(keep)[:55]}'")
    print(f"             Page ID:      {keep['id']}")
    print(f"             Last edited:  {get_last_edited(keep)}")
    print(f"             Created:      {get_created(keep)}")
    print()

    for old_page in remove:
        print(f"  ❌ REMOVE: '{get_title(old_page)[:55]}'")
        print(f"             Page ID:      {old_page['id']}")
        print(f"             Last edited:  {get_last_edited(old_page)}")
        print(f"             Created:      {get_created(old_page)}")

        # Archive (soft delete - recoverable from Notion trash)
        try:
            client.pages.update(
                page_id  = old_page["id"],
                archived = True
            )
            print(f"             Status:       📦 ARCHIVED ✅")
            total_archived += 1
        except Exception as e:
            print(f"             Status:       ❌ FAILED: {e}")
            total_failed += 1
        print()

# ── Final summary ─────────────────────────────────────────────────────────────
print("=" * 70)
print("📊 RESULTS")
print("=" * 70)
print(f"\n  Duplicate groups:  {len(duplicates)}")
print(f"  Pages archived:    {total_archived} ✅")
print(f"  Pages failed:      {total_failed}")

if total_archived > 0 and total_failed == 0:
    print(f"\n  🎉 All duplicates fixed!")
    print(f"  💡 Run: python check_notion_sync.py to verify")
elif total_failed > 0:
    print(f"\n  ⚠️  Some pages could not be archived.")
    print(f"      Try archiving them manually in Notion.")

print(f"\n  Note: Archived pages go to Notion Trash")
print(f"        You can restore them from Trash if needed")
print(f"{'=' * 70}\n")
