"""
investigate_invalid_ids.py
──────────────────────────
Check if the 11 "Invalid Todoist IDs" found in Notion
still exist in Todoist (any project) or have been deleted.
"""

import requests
from config import settings

headers = {
    "Authorization": f"Bearer {settings.todoist_api_token}",
    "Content-Type": "application/json"
}

# All 11 invalid IDs from the check_notion_sync.py output
ids_to_check = [
    ("Todoist-Notion-App-Report & Updates",                           "6g2WxPFh7cC6g5v9"),
    ("New Sub Task from Notion to Parent Notion 002 Task",            "6g93WM63WjV4gvr9"),
    ("Notion 001 Updated from Notion Notion",                         "6g93JQp8c27RpjQ9"),
    ("New Sub Task Added from Notion- Parent Task Notion 001",        "6g93WMM2WFg3MV79"),
    ("Todo 002 002 002 002 Notion From Notion",                       "6g93Hw4JrqCmmwH9"),
    ("Any Task not in the plan is the RED LINE.",                     "6g95cpG26WwVhW2h"),
    ("Plan *today for tomorrow* from Todoist",                        "6g95X7V53JX4w8F9"),
    ("Sub Task 002 from Todoist 002",                                 "6g93Qw82frrVJQRh"),
    ("Todoist 001 001. Todoist Updated",                              "6g93HpMFMPWPVCvh"),
    ("Execute the Task as planned *a day before*",                    "6g95c6mJXj7GX7g9"),
    ("Sub Task 001 from Todoist 001",                                 "6g93QmvGFpqCW92h"),
]

print("\n" + "=" * 70)
print("🔍 INVESTIGATING INVALID TODOIST IDs IN NOTION")
print("=" * 70)
print(f"\nChecking {len(ids_to_check)} task IDs...\n")

found_different_project = []
not_found               = []
found_same_project      = []

for title, task_id in ids_to_check:
    try:
        r = requests.get(
            f"https://api.todoist.com/api/v1/tasks/{task_id}",
            headers=headers
        )

        if r.status_code == 200:
            task       = r.json()
            project_id = task.get("project_id")
            is_yours   = project_id == settings.todoist_project_id

            if is_yours:
                found_same_project.append((title, task_id, task))
                print(f"  ✅ FOUND (YOUR PROJECT): [{task_id}]")
                print(f"     Notion title: {title[:55]}")
                print(f"     Todoist:      {task.get('content', '')[:55]}")
            else:
                found_different_project.append((title, task_id, task))
                print(f"  ⚠️  FOUND (DIFFERENT PROJECT): [{task_id}]")
                print(f"     Notion title: {title[:55]}")
                print(f"     Todoist:      {task.get('content', '')[:55]}")
                print(f"     Project ID:   {project_id}")

        elif r.status_code == 404:
            not_found.append((title, task_id))
            print(f"  ❌ DELETED: [{task_id}]")
            print(f"     Notion title: {title[:55]}")

        else:
            print(f"  ⚠️  Status {r.status_code}: [{task_id}]")
            print(f"     Notion title: {title[:55]}")

    except Exception as e:
        print(f"  ❌ Error checking [{task_id}]: {e}")

    print()

# ── Summary ───────────────────────────────────────────────────────────────────
print("=" * 70)
print("📊 SUMMARY")
print("=" * 70)
print(f"\n  ✅ Found in YOUR project:        {len(found_same_project)}")
print(f"  ⚠️  Found in DIFFERENT project:   {len(found_different_project)}")
print(f"  ❌ DELETED (not found anywhere):  {len(not_found)}")

print("\n" + "=" * 70)
print("💡 RECOMMENDED ACTION")
print("=" * 70)

if not_found:
    print(f"""
  ❌ {len(not_found)} tasks are DELETED from Todoist
     → These Notion pages have stale/invalid Todoist IDs
     → ACTION: Clear their Todoist ID in Notion
               OR delete them from Notion if no longer needed
""")

if found_different_project:
    print(f"""
  ⚠️  {len(found_different_project)} tasks are in a DIFFERENT Todoist project
     → They exist in Todoist but not in your configured project
     → ACTION: Move them to your project
               OR they are intentionally in another project
""")

if found_same_project:
    print(f"""
  ✅ {len(found_same_project)} tasks found in YOUR project
     → These should be syncing - check if IDs match
""")

if not not_found and not found_different_project:
    print("""
  ✅ All tasks found - IDs are valid
     → May be a filtering or project ID mismatch
     → Re-run check_notion_sync.py to verify
""")
