"""
check_completed_tasks.py
────────────────────────
Checks if the "invalid" Todoist IDs in Notion
are actually COMPLETED tasks (which are excluded
from the active task list).

This explains why check_notion_sync.py flags them
as "invalid" - they exist but are completed.
"""

import requests
from config import settings

headers = {
    "Authorization": f"Bearer {settings.todoist_api_token}",
    "Content-Type": "application/json"
}

# All 11 "invalid" IDs from check_notion_sync output
ids_to_check = [
    ("Todoist-Notion-App-Report & Updates",                    "6g2WxPFh7cC6g5v9"),
    ("New Sub Task from Notion to Parent Notion 002 Task",     "6g93WM63WjV4gvr9"),
    ("Notion 001 Updated from Notion Notion",                  "6g93JQp8c27RpjQ9"),
    ("New Sub Task Added from Notion",                         "6g93WMM2WFg3MV79"),
    ("Todo 002 002 002 002 Notion From Notion",                "6g93Hw4JrqCmmwH9"),
    ("Any Task not in the plan is the RED LINE.",              "6g95cpG26WwVhW2h"),
    ("Plan *today for tomorrow* from Todoist",                 "6g95X7V53JX4w8F9"),
    ("Sub Task 002 from Todoist 002",                          "6g93Qw82frrVJQRh"),
    ("Todoist 001 001. Todoist Updated",                       "6g93HpMFMPWPVCvh"),
    ("Execute the Task as planned",                            "6g95c6mJXj7GX7g9"),
    ("Sub Task 001 from Todoist 001",                          "6g93QmvGFpqCW92h"),
]

print("\n" + "=" * 70)
print("🔍 CHECKING COMPLETED STATUS OF INVALID IDs")
print("=" * 70)
print()

completed_tasks    = []
active_tasks       = []
other_status       = []

for title, task_id in ids_to_check:
    try:
        r = requests.get(
            f"https://api.todoist.com/api/v1/tasks/{task_id}",
            headers=headers
        )
        task        = r.json()
        is_complete = task.get("is_completed", False)
        content     = task.get("content", "")
        project_id  = task.get("project_id", "")

        if is_complete:
            completed_tasks.append((title, task_id, content))
            print(f"  ✅ COMPLETED: [{task_id}]")
            print(f"     Notion:   {title[:55]}")
            print(f"     Todoist:  {content[:55]}")
        else:
            active_tasks.append((title, task_id, content))
            print(f"  🔵 ACTIVE:    [{task_id}]")
            print(f"     Notion:   {title[:55]}")
            print(f"     Todoist:  {content[:55]}")
        print()

    except Exception as e:
        other_status.append((title, task_id))
        print(f"  ❌ Error: [{task_id}] {e}\n")

# ── Summary ───────────────────────────────────────────────────────────────────
print("=" * 70)
print("📊 SUMMARY")
print("=" * 70)
print(f"\n  ✅ Completed tasks: {len(completed_tasks)}")
print(f"  🔵 Active tasks:    {len(active_tasks)}")
print(f"  ❌ Errors:          {len(other_status)}")

print("\n" + "=" * 70)
print("💡 DIAGNOSIS")
print("=" * 70)

if len(completed_tasks) == len(ids_to_check):
    print(f"""
  ✅ CONFIRMED: All {len(completed_tasks)} "invalid" tasks are COMPLETED

  ROOT CAUSE:
    → get_all_tasks() only returns ACTIVE tasks
    → Completed tasks are excluded from active list
    → Notion still has their Todoist IDs (correct!)
    → check_notion_sync.py incorrectly flags them as "invalid"

  THIS IS EXPECTED BEHAVIOUR:
    → Completed tasks in Notion = historical record ✅
    → Todoist IDs in Notion = correct reference ✅
    → No action needed for these tasks ✅

  FIX NEEDED:
    → Update check_notion_sync.py to skip completed tasks
    → Only flag truly invalid IDs (tasks that don't exist anywhere)
""")

elif len(completed_tasks) > 0:
    print(f"""
  ⚠️  MIXED: {len(completed_tasks)} completed, {len(active_tasks)} still active

  COMPLETED tasks ({len(completed_tasks)}):
    → These are fine - historical records in Notion ✅
    → check_notion_sync.py needs to skip these

  ACTIVE tasks still flagged ({len(active_tasks)}):
    → These need further investigation
    → May be a project filter issue
""")
    for title, task_id, content in active_tasks:
        print(f"     • [{task_id}] {title[:50]}")

else:
    print(f"""
  🔵 All {len(active_tasks)} tasks are ACTIVE - different issue
     → Tasks exist and are active but not returned by get_all_tasks()
     → Possible project ID filter issue
     → Check TODOIST_PROJECT_ID in .env
""")
    print(f"\n  Your configured project: {settings.todoist_project_id}")
