"""
test_todoist_completed.py
─────────────────────────
Tests different ways to fetch completed tasks
from Todoist v1 API to find the correct parameter.
"""

import requests
from config import settings

headers = {
    "Authorization": f"Bearer {settings.todoist_api_token}",
    "Content-Type": "application/json"
}

base_url = "https://api.todoist.com/api/v1"

# Known completed task ID (from our investigation)
known_id = "6g2WxPFh7cC6g5v9"

print("\n" + "=" * 70)
print("🔍 TESTING TODOIST API COMPLETED TASKS PARAMETERS")
print("=" * 70)

# ── Test 1: Individual task fetch ─────────────────────────────────────────────
print("\n📋 Test 1: Individual task fetch (known ID)")
r = requests.get(f"{base_url}/tasks/{known_id}", headers=headers)
if r.status_code == 200:
    t = r.json()
    print(f"  ✅ Found: '{t.get('content')}'")
    print(f"     is_completed: {t.get('is_completed')}")
    print(f"     project_id:   {t.get('project_id')}")
else:
    print(f"  ❌ Status: {r.status_code}")

# ── Test 2: Try different completed parameters ────────────────────────────────
print("\n📋 Test 2: Different API parameters for completed tasks")
print()

params_to_try = [
    {"is_completed": "true"},
    {"is_completed": True},
    {"completed": "true"},
    {"filter": "completed"},
]

for params in params_to_try:
    try:
        r = requests.get(
            f"{base_url}/tasks",
            headers=headers,
            params={**params, "limit": 10}
        )
        data   = r.json()
        tasks  = data.get("results", [])
        proj_t = [t for t in tasks
                  if t.get("project_id") == settings.todoist_project_id]

        print(f"  Params: {params}")
        print(f"  Status: {r.status_code} | "
              f"Total: {len(tasks)} | "
              f"In project: {len(proj_t)}")

        # Check if our known task is there
        found = any(t["id"] == known_id for t in tasks)
        print(f"  Known task found: {'✅ YES' if found else '❌ No'}")
        print()

    except Exception as e:
        print(f"  Params: {params} → Error: {e}\n")

# ── Test 3: Try tasks/completed endpoint ──────────────────────────────────────
print("\n📋 Test 3: Alternative endpoints")
print()

endpoints = [
    f"{base_url}/tasks/completed",
    f"{base_url}/tasks/completed/get_all",
    "https://api.todoist.com/sync/v9/items/completed/get_all",
]

for endpoint in endpoints:
    try:
        r = requests.get(
            endpoint,
            headers=headers,
            params={"project_id": settings.todoist_project_id, "limit": 10}
        )
        print(f"  Endpoint: {endpoint}")
        print(f"  Status: {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            print(f"  Response keys: {list(data.keys())[:5]}")
            items = data.get("results", data.get("items", []))
            print(f"  Items found: {len(items)}")
        else:
            print(f"  Response: {r.text[:100]}")
        print()
    except Exception as e:
        print(f"  Error: {e}\n")

# ── Test 4: Check raw response for active tasks ───────────────────────────────
print("\n📋 Test 4: Check if known tasks appear with status filter")
print()

# Try fetching with project_id directly
r = requests.get(
    f"{base_url}/tasks",
    headers=headers,
    params={
        "project_id": settings.todoist_project_id,
        "limit": 100
    }
)
data  = r.json()
tasks = data.get("results", [])
ids   = {t["id"] for t in tasks}

known_missing = [
    "6g2WxPFh7cC6g5v9",
    "6g93WM63WjV4gvr9",
    "6g93JQp8c27RpjQ9",
]

print(f"  Tasks returned with project_id filter: {len(tasks)}")
for kid in known_missing:
    found = kid in ids
    print(f"  Known task [{kid}]: {'✅ Found' if found else '❌ Not found'}")

print(f"\n  All task IDs in response:")
for t in tasks[:5]:
    print(f"    [{t['id']}] {t.get('content', '')[:45]}"
          f" completed={t.get('is_completed', '?')}")
