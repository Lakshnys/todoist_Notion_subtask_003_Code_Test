"""
inspect_notion_page.py
───────────────────────
Inspects raw Notion page data to find field mismatches.
"""

import json
from notion_client import Client
from config import settings
from notion_api import NotionClient
from todoist_api import TodoistClient

TODOIST_ID = "6gRh8xg3QpmVHpXh"

client  = Client(auth=settings.notion_api_token)
notion  = NotionClient(settings.notion_api_token)
todoist = TodoistClient(settings.todoist_api_token)

# ── Find Notion page ──────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("🔍 RAW NOTION PAGE INSPECTION")
print("=" * 70)

n_tasks = notion.get_all_tasks()
n_task  = next(
    (t for t in n_tasks if t.todoist_task_id == TODOIST_ID),
    None
)

if not n_task:
    print(f"❌ Task [{TODOIST_ID}] not found in Notion!")
    exit(1)

print(f"\nNotion Page ID: {n_task.id}")
print(f"Title:          {n_task.title}")
print(f"Description:    {n_task.description}")
print(f"Due:            {n_task.due_date}")
print(f"Last edited:    {n_task.last_modified_time}")
print(f"Last source:    {n_task.last_modified_source}")

# ── Fetch raw page ────────────────────────────────────────────────────────────
print("\n" + "─" * 70)
print("📋 RAW PROPERTIES FROM NOTION API")
print("─" * 70)

raw   = client.pages.retrieve(page_id=n_task.id)
props = raw.get('properties', {})

print(f"\nAll property names in this page:")
for name in sorted(props.keys()):
    prop_type = props[name].get('type', 'unknown')
    print(f"  • '{name}' ({prop_type})")

# ── Check specific fields ─────────────────────────────────────────────────────
print(f"\n{'─' * 70}")
print("📋 FIELD VALUES (Raw)")
print(f"{'─' * 70}")

# Description
print(f"\n1. Description field:")
desc_raw = props.get('Description', {})
if desc_raw:
    rt = desc_raw.get('rich_text', [])
    if rt:
        print(f"   Value: '{rt[0].get('text', {}).get('content', '')}'")
    else:
        print(f"   Value: EMPTY (rich_text is empty list)")
    print(f"   Type:  {desc_raw.get('type')}")
else:
    print(f"   ❌ 'Description' column NOT FOUND in this page!")

# Due Date
print(f"\n2. Due Date field:")
due_raw = props.get('Due Date', {})
if due_raw:
    date_obj = due_raw.get('date', {})
    if date_obj:
        print(f"   Start: {date_obj.get('start')}")
        print(f"   End:   {date_obj.get('end')}")
    else:
        print(f"   Value: EMPTY (date is null)")
else:
    print(f"   ❌ 'Due Date' column NOT FOUND!")

# Last Modified Time
print(f"\n3. Last Modified Time:")
lmt_raw = props.get('Last Modified Time', {})
if lmt_raw:
    date_obj = lmt_raw.get('date', {})
    print(f"   Value: {date_obj.get('start') if date_obj else 'EMPTY'}")
else:
    print(f"   ❌ 'Last Modified Time' column NOT FOUND!")

# Last Modified Source
print(f"\n4. Last Modified Source:")
lms_raw = props.get('Last Modified Source', {})
if lms_raw:
    sel = lms_raw.get('select', {})
    print(f"   Value: {sel.get('name') if sel else 'EMPTY'}")
else:
    print(f"   ❌ 'Last Modified Source' column NOT FOUND!")

# ── Show raw page metadata ─────────────────────────────────────────────────────
print(f"\n{'─' * 70}")
print("📋 PAGE METADATA")
print(f"{'─' * 70}")
print(f"\n  last_edited_time: {raw.get('last_edited_time')}")
print(f"  created_time:     {raw.get('created_time')}")

# ── Todoist comparison ────────────────────────────────────────────────────────
print(f"\n{'─' * 70}")
print("📋 TODOIST vs NOTION COMPARISON")
print(f"{'─' * 70}")

tasks    = todoist.get_all_tasks()
t_task   = next((t for t in tasks if t.id == TODOIST_ID), None)

if t_task:
    print(f"\n  Field          Todoist                    Notion")
    print(f"  {'─' * 65}")
    print(f"  Title          {t_task.content[:25]:<25}  {n_task.title[:25]}")
    print(f"  Description    {(t_task.description or '')[:25]:<25}  {(n_task.description or '')[:25]}")
    print(f"  Due            {str(t_task.due_datetime or 'None')[:25]:<25}  {str(n_task.due_date or 'None')[:25]}")
    print(f"  Priority       {t_task.priority:<25}  {n_task.priority}")
    print(f"  Updated at     {str(t_task.updated_at or 'None')[:25]:<25}  {str(n_task.last_modified_time or 'None')[:25]}")

print(f"\n{'=' * 70}\n")
