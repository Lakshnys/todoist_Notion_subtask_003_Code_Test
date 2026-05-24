"""
test_completed_direct.py
─────────────────────────
Directly tests fetching completed tasks using the
correct endpoint and structure WITHOUT importing todoist_api.py
This confirms the fix works before you replace the file.
"""

import requests
from config import settings

headers = {
    "Authorization": f"Bearer {settings.todoist_api_token}",
    "Content-Type": "application/json"
}

base_url   = "https://api.todoist.com/api/v1"
project_id = settings.todoist_project_id

print("\n" + "=" * 70)
print("🧪 DIRECT TEST: Completed Tasks Fetch")
print("=" * 70)

# ── Fetch ACTIVE tasks ────────────────────────────────────────────────────────
print("\n📥 Fetching active tasks...")
r      = requests.get(f"{base_url}/tasks", headers=headers)
data   = r.json()
active = [t for t in data.get("results", []) if t.get("project_id") == project_id]
print(f"  Active tasks in project: {len(active)}")

# ── Fetch COMPLETED tasks (correct endpoint) ──────────────────────────────────
print("\n📥 Fetching completed tasks...")
r    = requests.get(
    f"{base_url}/tasks/completed",
    headers=headers,
    params={"project_id": project_id, "limit": 100}
)
data       = r.json()
items      = data.get("items", [])
print(f"  Completed items returned: {len(items)}")

# ── Normalize completed tasks ─────────────────────────────────────────────────
print("\n🔄 Normalizing completed tasks...")
completed_normalized = []
for item in items:
    normalized = {
        "id":           item.get("task_id"),   # ← Real task ID (NOT 'id'!)
        "content":      item.get("content", ""),
        "description":  item.get("description", ""),
        "priority":     item.get("priority", 4),
        "project_id":   item.get("project_id", ""),
        "parent_id":    item.get("parent_id"),
        "labels":       item.get("labels", []),
        "due":          item.get("due"),
        "is_completed": True,
        "created_at":   item.get("created_at"),
        "updated_at":   item.get("completed_at"),
    }
    completed_normalized.append(normalized)

print(f"  Normalized completed tasks: {len(completed_normalized)}")

# ── Combined result ───────────────────────────────────────────────────────────
all_tasks = active + completed_normalized
print(f"\n📊 RESULTS:")
print(f"  Active:    {len(active)}")
print(f"  Completed: {len(completed_normalized)}")
print(f"  Total:     {len(all_tasks)}")

# ── Show completed tasks ──────────────────────────────────────────────────────
if completed_normalized:
    print(f"\n  Completed tasks (first 5):")
    for t in completed_normalized[:5]:
        print(f"    ✓ [{t['id']}] {t['content'][:55]}")

# ── Verify the 11 known IDs are now found ─────────────────────────────────────
print(f"\n\n{'─' * 70}")
print("🔍 Verifying the 11 previously-missing tasks...")
print(f"{'─' * 70}")

known_missing = [
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
]

all_ids = {t["id"] for t in all_tasks}
found   = [tid for tid in known_missing if tid in all_ids]
missing = [tid for tid in known_missing if tid not in all_ids]

print(f"\n  Found: {len(found)}/11")
print(f"  Still missing: {len(missing)}/11")

for tid in found:
    task = next((t for t in all_tasks if t["id"] == tid), None)
    if task:
        status = "completed" if task["is_completed"] else "active"
        print(f"  ✅ [{tid}] {task['content'][:45]} ({status})")

for tid in missing:
    print(f"  ❌ [{tid}] Still not found")

# ── Conclusion ────────────────────────────────────────────────────────────────
print(f"\n\n{'=' * 70}")
if len(found) == 11:
    print("✅ SUCCESS! All 11 tasks found when using correct endpoint!")
    print()
    print("ACTION NEEDED:")
    print("  Replace your local todoist_api.py with the updated version")
    print("  Download from: outputs/todoist_api.py")
    print()
    print("The fix: Use task_id (not id) from /tasks/completed endpoint")
elif len(found) > 0:
    print(f"⚠️  Partial: {len(found)}/11 tasks found")
else:
    print("❌ Still not found - different issue")
print(f"{'=' * 70}\n")
