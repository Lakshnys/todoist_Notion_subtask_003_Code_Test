"""
debug_completed_endpoint.py
────────────────────────────
Directly inspect the /tasks/completed endpoint response
to understand the exact structure.
"""

import json
import requests
from config import settings

headers = {
    "Authorization": f"Bearer {settings.todoist_api_token}",
    "Content-Type": "application/json"
}

base_url = "https://api.todoist.com/api/v1"

print("\n" + "=" * 70)
print("🔍 RAW COMPLETED ENDPOINT INSPECTION")
print("=" * 70)

# ── Test 1: Basic completed endpoint ─────────────────────────────────────────
print("\n📋 Test 1: GET /tasks/completed (no filters)")
r = requests.get(f"{base_url}/tasks/completed", headers=headers)
print(f"  Status: {r.status_code}")
data = r.json()
print(f"  Response keys: {list(data.keys())}")
items = data.get("items", [])
print(f"  Items count: {len(items)}")
if items:
    print(f"\n  First item keys: {list(items[0].keys())}")
    print(f"  First item sample:")
    print(f"    id:           {items[0].get('id', items[0].get('task_id', '?'))}")
    print(f"    content:      {items[0].get('content', items[0].get('task', {}).get('content', '?'))}")
    print(f"    project_id:   {items[0].get('project_id', '?')}")
    print(f"\n  Full first item (raw):")
    print(json.dumps(items[0], indent=4)[:800])

# ── Test 2: With project_id filter ───────────────────────────────────────────
print(f"\n\n📋 Test 2: GET /tasks/completed?project_id={settings.todoist_project_id}")
r = requests.get(
    f"{base_url}/tasks/completed",
    headers=headers,
    params={"project_id": settings.todoist_project_id}
)
print(f"  Status: {r.status_code}")
data = r.json()
print(f"  Response keys: {list(data.keys())}")
items = data.get("items", [])
print(f"  Items count: {len(items)}")

# ── Test 3: Check if known task ID appears ────────────────────────────────────
print(f"\n\n📋 Test 3: Search for known task in completed items")
known_id = "6g2WxPFh7cC6g5v9"

r = requests.get(f"{base_url}/tasks/completed", headers=headers)
data  = r.json()
items = data.get("items", [])

print(f"  Total completed items: {len(items)}")
print(f"  Looking for: {known_id}")

found = False
for item in items:
    # Check all possible ID fields
    item_id      = item.get("id") or item.get("task_id") or ""
    item_content = (
        item.get("content") or
        item.get("task", {}).get("content", "") or ""
    )
    if known_id in str(item):
        print(f"  ✅ FOUND in item!")
        print(f"     Keys: {list(item.keys())}")
        found = True
        break

if not found:
    print(f"  ❌ Not found in completed items")
    print(f"\n  All item IDs in response:")
    for item in items[:5]:
        iid = item.get("id") or item.get("task_id") or "unknown"
        icontent = (
            item.get("content") or
            str(item.get("task", {}).get("content", ""))[:40]
        )
        print(f"    [{iid}] {icontent[:50]}")

# ── Test 4: Try Sync API v9 ───────────────────────────────────────────────────
print(f"\n\n📋 Test 4: Sync API v9 - items/get_all")
r = requests.get(
    "https://api.todoist.com/sync/v9/items/get_all",
    headers=headers,
    params={"project_id": settings.todoist_project_id}
)
print(f"  Status: {r.status_code}")
if r.status_code == 200:
    data  = r.json()
    items = data.get("items", data.get("results", []))
    print(f"  Response keys: {list(data.keys())}")
    print(f"  Items: {len(items)}")
    if items:
        print(f"  First item keys: {list(items[0].keys())[:8]}")
        # Check for our known ID
        ids = [i.get("id") for i in items]
        print(f"  Known ID found: {known_id in ids}")
else:
    print(f"  Response: {r.text[:150]}")

# ── Test 5: Sync API - all items ──────────────────────────────────────────────
print(f"\n\n📋 Test 5: Sync API v9 - sync endpoint")
r = requests.post(
    "https://api.todoist.com/sync/v9/sync",
    headers=headers,
    json={"sync_token": "*", "resource_types": ["items"]}
)
print(f"  Status: {r.status_code}")
if r.status_code == 200:
    data  = r.json()
    items = data.get("items", [])
    print(f"  Total items from sync: {len(items)}")
    proj_items = [
        i for i in items
        if i.get("project_id") == settings.todoist_project_id
    ]
    print(f"  Items in your project: {len(proj_items)}")
    known_found = any(i.get("id") == known_id for i in items)
    print(f"  Known ID [{known_id}] found: {known_found}")
    if proj_items:
        print(f"\n  Sample project items:")
        for item in proj_items[:3]:
            print(f"    [{item.get('id')}] {item.get('content','')[:45]}"
                  f" checked={item.get('checked', item.get('is_completed','?'))}")
