"""
find_second_duplicate.py
─────────────────────────
Finds the second duplicate page ('New Task from 33333 Notion')
by searching by title and checking its raw Todoist ID field.
"""

import json
from notion_client import Client
from config import settings
from datetime import datetime

client = Client(auth=settings.notion_api_token)
DB_ID  = settings.notion_database_id

print("\n" + "=" * 70)
print("🔍 FINDING SECOND DUPLICATE PAGE")
print("=" * 70)

def get_title(page):
    props      = page.get("properties", {})
    title_list = props.get("Title", {}).get("title", [])
    return title_list[0]["text"]["content"] if title_list else "(no title)"

def get_todoist_id_raw(page):
    """Get raw Todoist ID including any hidden characters."""
    props = page.get("properties", {})
    rt    = props.get("Todoist Task ID", {}).get("rich_text", [])
    if rt:
        raw = rt[0]["text"]["content"]
        return raw
    return None

def get_last_edited(page):
    ts = page.get("last_edited_time", "")
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.replace(tzinfo=None)
    except Exception:
        return datetime.min

# ── Fetch all pages ───────────────────────────────────────────────────────────
print("\n📥 Fetching all pages...")
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

print(f"   Total active pages: {len(all_pages)}")

# ── Search by title ───────────────────────────────────────────────────────────
print("\n📋 Searching for 'New Task from 33333 Notion'...")

for page in all_pages:
    title = get_title(page)
    if "33333" in title or "Notion Test 001" in title:
        raw_id = get_todoist_id_raw(page)
        print(f"\n  ✅ FOUND: '{title}'")
        print(f"     Page ID:      {page['id']}")
        print(f"     Todoist ID:   [{raw_id}]")
        print(f"     ID length:    {len(raw_id) if raw_id else 0}")
        print(f"     ID bytes:     {raw_id.encode() if raw_id else b''}")
        print(f"     Last edited:  {get_last_edited(page)}")
        print(f"     Archived:     {page.get('archived', False)}")

# ── Find ALL pages with similar IDs (fuzzy match) ────────────────────────────
TARGET = "6gRXgc9CxGQJ62P9"
print(f"\n\n{'─' * 70}")
print(f"📋 Fuzzy search: IDs similar to [{TARGET}]...")

similar = []
for page in all_pages:
    raw_id = get_todoist_id_raw(page)
    if raw_id and (
        raw_id.strip() == TARGET or
        raw_id == TARGET or
        TARGET in raw_id or
        raw_id in TARGET
    ):
        similar.append(page)

print(f"   Found {len(similar)} similar pages:")
for page in similar:
    raw_id = get_todoist_id_raw(page)
    print(f"\n   Title:       {get_title(page)[:55]}")
    print(f"   Page ID:     {page['id']}")
    print(f"   Todoist ID:  [{raw_id}]")
    print(f"   ID == TARGET: {raw_id == TARGET}")
    print(f"   ID stripped:  {raw_id.strip() == TARGET}")
    print(f"   Last edited: {get_last_edited(page)}")

# ── Show ALL pages with their IDs ─────────────────────────────────────────────
print(f"\n\n{'─' * 70}")
print("📋 ALL pages and their Todoist IDs (checking for duplicates):")
print(f"{'─' * 70}\n")

from collections import defaultdict
by_id = defaultdict(list)

for page in all_pages:
    raw_id = get_todoist_id_raw(page)
    key    = raw_id.strip() if raw_id else "__NO_ID__"
    by_id[key].append(page)

# Show duplicates
dupes_found = False
for tid, pages in by_id.items():
    if len(pages) > 1:
        dupes_found = True
        print(f"  ⚠️  DUPLICATE: [{tid}] ({len(pages)} copies)")
        for p in pages:
            raw = get_todoist_id_raw(p)
            print(f"    • '{get_title(p)[:45]}' "
                  f"| edited: {get_last_edited(p)} "
                  f"| raw_id_bytes: {raw.encode()[:30] if raw else b''}")

        # Auto-fix: archive older
        sorted_p = sorted(pages, key=get_last_edited, reverse=True)
        print(f"\n    Fixing: Archiving {len(sorted_p)-1} older page(s)...")
        for old in sorted_p[1:]:
            try:
                client.pages.update(page_id=old["id"], archived=True)
                print(f"    📦 Archived: '{get_title(old)[:45]}' "
                      f"[{old['id']}]")
            except Exception as e:
                print(f"    ❌ Failed: {e}")
        print()

if not dupes_found:
    print("  ✅ No duplicates found with stripped ID comparison")
    print("\n  The Notion UI may be showing a cached/stale view.")
    print("  Try: Ctrl+Shift+R in Notion to hard refresh")
    print("  Or:  Close and reopen the database view")

print(f"\n{'=' * 70}\n")
