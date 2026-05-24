"""
find_by_todoist_id.py
─────────────────────
Directly queries Notion for ALL pages with a specific
Todoist Task ID - including duplicates the API might miss.
Uses filter query to find exact matches.
"""

from notion_client import Client
from config import settings
from datetime import datetime

client = Client(auth=settings.notion_api_token)
DB_ID  = settings.notion_database_id

# ── The duplicate Todoist ID from the screenshot ──────────────────────────────
DUPLICATE_ID = "6gRXgc9CxGQJ62P9"

print("\n" + "=" * 70)
print(f"🔍 SEARCHING FOR TODOIST ID: {DUPLICATE_ID}")
print("=" * 70)

# ── Method 1: Filter query ────────────────────────────────────────────────────
print("\n📋 Method 1: Direct filter query...")

results = []
has_more     = True
start_cursor = None

while has_more:
    kwargs = {
        "database_id": DB_ID,
        "page_size":   100,
        "filter": {
            "property": "Todoist Task ID",
            "rich_text": {
                "equals": DUPLICATE_ID
            }
        }
    }
    if start_cursor:
        kwargs["start_cursor"] = start_cursor

    response     = client.databases.query(**kwargs)
    results.extend(response.get("results", []))
    has_more     = response.get("has_more", False)
    start_cursor = response.get("next_cursor")

print(f"   Pages found: {len(results)}")

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

for page in results:
    print(f"\n   Page ID:      {page['id']}")
    print(f"   Title:        {get_title(page)}")
    print(f"   Last edited:  {get_last_edited(page)}")
    print(f"   Created:      {get_created(page)}")
    print(f"   Archived:     {page.get('archived', False)}")
    print(f"   In trash:     {page.get('in_trash', False)}")

# ── Method 2: Full scan (no filter) ──────────────────────────────────────────
print(f"\n\n{'─' * 70}")
print("📋 Method 2: Full scan (no filter, check all pages)...")

all_pages    = []
has_more     = True
start_cursor = None

while has_more:
    kwargs = {
        "database_id":    DB_ID,
        "page_size":      100,
        "filter_properties": []
    }
    if start_cursor:
        kwargs["start_cursor"] = start_cursor

    response     = client.databases.query(**kwargs)
    all_pages.extend(response.get("results", []))
    has_more     = response.get("has_more", False)
    start_cursor = response.get("next_cursor")

print(f"   Total pages (all): {len(all_pages)}")

# Find matching pages
matching = []
for page in all_pages:
    props = page.get("properties", {})
    rt    = props.get("Todoist Task ID", {}).get("rich_text", [])
    tid   = rt[0]["text"]["content"] if rt else None
    if tid == DUPLICATE_ID:
        matching.append(page)

print(f"   Pages with ID [{DUPLICATE_ID}]: {len(matching)}")

if len(matching) > 1:
    print(f"\n   ✅ DUPLICATES CONFIRMED!")

    # Sort newest first
    sorted_pages = sorted(matching, key=get_last_edited, reverse=True)
    keep         = sorted_pages[0]
    to_remove    = sorted_pages[1:]

    print(f"\n   ✅ KEEP (newest):")
    print(f"      Title:       {get_title(keep)}")
    print(f"      Page ID:     {keep['id']}")
    print(f"      Last edited: {get_last_edited(keep)}")

    print(f"\n   ❌ REMOVE (older):")
    for old in to_remove:
        print(f"      Title:       {get_title(old)}")
        print(f"      Page ID:     {old['id']}")
        print(f"      Last edited: {get_last_edited(old)}")

    # ── Fix: Archive the older ones ───────────────────────────────────────────
    print(f"\n\n{'─' * 70}")
    confirm = input("Archive the older duplicate(s)? (yes/no): ")

    if confirm.lower() == "yes":
        for old in to_remove:
            try:
                client.pages.update(
                    page_id  = old["id"],
                    archived = True
                )
                print(f"   📦 Archived: '{get_title(old)}' [{old['id']}]")
            except Exception as e:
                print(f"   ❌ Failed [{old['id']}]: {e}")

        print(f"\n   ✅ Done! Run: python check_notion_sync.py")
    else:
        print("   Cancelled - no changes made.")

elif len(matching) == 1:
    print(f"\n   ℹ️  Only 1 page found - no duplicate to fix")
    print(f"   The other page may show same ID due to Notion display cache")
    print(f"   Try: Hard refresh Notion (Ctrl+Shift+R)")
else:
    print(f"\n   ❌ No pages found with this ID!")
    print(f"   Check if DUPLICATE_ID is correct: {DUPLICATE_ID}")

# ── Method 3: Also check archived pages ──────────────────────────────────────
print(f"\n\n{'─' * 70}")
print("📋 Method 3: Check archived/trashed pages...")

try:
    archived_results = []
    has_more         = True
    start_cursor     = None

    while has_more:
        kwargs = {
            "database_id": DB_ID,
            "page_size":   100,
            "filter": {
                "and": [
                    {
                        "property": "Todoist Task ID",
                        "rich_text": {"equals": DUPLICATE_ID}
                    }
                ]
            },
            "archived": True
        }
        if start_cursor:
            kwargs["start_cursor"] = start_cursor

        response     = client.databases.query(**kwargs)
        archived_results.extend(response.get("results", []))
        has_more     = response.get("has_more", False)
        start_cursor = response.get("next_cursor")

    print(f"   Archived pages with same ID: {len(archived_results)}")
    for p in archived_results:
        print(f"   📦 [{p['id']}] '{get_title(p)}'")

except Exception as e:
    print(f"   (archived check not supported: {e})")

print(f"\n{'=' * 70}\n")
