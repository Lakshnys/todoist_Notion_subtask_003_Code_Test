"""
debug_get_all_tasks.py
──────────────────────
Debugs why get_all_tasks() returns 31 tasks
but 11 tasks in the project are not returned.

Compares raw API response vs filtered results.
"""

import requests
from config import settings

headers = {
    "Authorization": f"Bearer {settings.todoist_api_token}",
    "Content-Type": "application/json"
}

# Tasks we KNOW exist but aren't returned
missing_ids = {
    "6g2WxPFh7cC6g5v9",
    "6g93WM63WjV4gvr9",
    "6g93JQp8c27RpjQ9",
    "6g93WMM2WFg3MV79",
    "6g93Hw4JrqCmmwH9",
    "6g95cpG26WwVhW2h",
    "6g95X7V53JX4w8F9",
    "6g93Qw82frrVJQRh",
    "6g93HpMFMPWPVCvh",
    "6g95c6mJXj7GX7g9",
    "6g93QmvGFpqCW92h",
}

print("\n" + "=" * 70)
print("🔍 DEBUG: RAW API RESPONSE ANALYSIS")
print("=" * 70)

# ── Step 1: Fetch ALL tasks (no project filter) ───────────────────────────────
print("\n📥 Step 1: Fetching ALL tasks (no project filter)...")

url           = "https://api.todoist.com/api/v1/tasks"
all_tasks_raw = []
cursor        = None
page          = 1

while True:
    params = {"limit": 100}
    if cursor:
        params["cursor"] = cursor

    r = requests.get(url, headers=headers, params=params)
    r.raise_for_status()
    data = r.json()

    batch = data.get("results", [])
    all_tasks_raw.extend(batch)

    print(f"   Page {page}: {len(batch)} tasks | "
          f"Total so far: {len(all_tasks_raw)} | "
          f"Has more: {bool(data.get('next_cursor'))}")

    cursor = data.get("next_cursor")
    page  += 1
    if not cursor:
        break

print(f"\n   Total tasks fetched (ALL projects): {len(all_tasks_raw)}")

# ── Step 2: Filter by project ──────────────────────────────────────────────────
print(f"\n📊 Step 2: Filter by project {settings.todoist_project_id}...")

project_tasks = [
    t for t in all_tasks_raw
    if t.get("project_id") == settings.todoist_project_id
]

print(f"   Tasks in configured project: {len(project_tasks)}")

# Check which missing tasks are in the raw data
found_in_raw = [
    t for t in all_tasks_raw
    if t["id"] in missing_ids
]
found_in_project = [
    t for t in project_tasks
    if t["id"] in missing_ids
]

print(f"\n   Of the 11 'missing' tasks:")
print(f"   → Found in raw API response: {len(found_in_raw)}/11")
print(f"   → Found after project filter: {len(found_in_project)}/11")

# ── Step 3: Show details of missing tasks in raw data ─────────────────────────
print(f"\n\n{'=' * 70}")
print("📋 Step 3: Details of 11 Tasks in Raw API Response")
print(f"{'=' * 70}\n")

for t in found_in_raw:
    task_id    = t["id"]
    project_id = t.get("project_id", "")
    matches    = project_id == settings.todoist_project_id

    print(f"  Task: '{t.get('content', '')[:55]}'")
    print(f"  ID:          {task_id}")
    print(f"  Project ID:  {project_id}")
    print(f"  Matches cfg: {matches} ← {'✅' if matches else '❌'}")
    print(f"  Completed:   {t.get('is_completed', False)}")
    print(f"  Parent ID:   {t.get('parent_id', 'None')}")
    print(f"  Section ID:  {t.get('section_id', 'None')}")
    print()

not_in_raw = missing_ids - {t["id"] for t in found_in_raw}
if not_in_raw:
    print(f"\n⚠️  {len(not_in_raw)} tasks NOT in raw API response at all:")
    for tid in not_in_raw:
        print(f"   • {tid}")

# ── Step 4: Compare project IDs ───────────────────────────────────────────────
print(f"\n\n{'=' * 70}")
print("🔬 Step 4: Project ID Comparison")
print(f"{'=' * 70}")

cfg_id = settings.todoist_project_id
print(f"\n  Configured ID:  '{cfg_id}'")
print(f"  Length:          {len(cfg_id)}")
print(f"  Bytes:           {cfg_id.encode()}")

if found_in_raw:
    raw_id = found_in_raw[0].get("project_id", "")
    print(f"\n  API returned ID: '{raw_id}'")
    print(f"  Length:          {len(raw_id)}")
    print(f"  Bytes:           {raw_id.encode()}")
    print(f"\n  Exact match:     {cfg_id == raw_id}")
    print(f"  Strip match:     {cfg_id.strip() == raw_id.strip()}")

# ── Step 5: Summary ───────────────────────────────────────────────────────────
print(f"\n\n{'=' * 70}")
print("📊 DIAGNOSIS")
print(f"{'=' * 70}")

if not found_in_raw:
    print("""
  ❌ Tasks NOT in raw API response
     → API is not returning these tasks at all
     → May be a Todoist API limitation
     → Check if tasks are in a "section" that requires filtering
""")
elif len(found_in_raw) == 11 and len(found_in_project) == 11:
    print("""
  ✅ All 11 tasks ARE in raw API and in project filter
     → get_all_tasks() SHOULD be returning them
     → There may be a caching or state issue
     → Try re-running: python main.py
""")
elif len(found_in_raw) == 11 and len(found_in_project) == 0:
    print("""
  ❌ Tasks in raw API but NOT passing project filter!
     → Project ID mismatch between API response and .env config
     → Check the project IDs printed above for differences
""")
else:
    print(f"""
  ⚠️  Partial results:
     Found in raw:    {len(found_in_raw)}/11
     Found in filter: {len(found_in_project)}/11
     → Some tasks missing from API, some failing filter
""")
