"""
find_task_projects.py
─────────────────────
Find which Todoist project the 11 "missing" tasks belong to.
Compares against configured project ID.
"""

import requests
from config import settings

headers = {
    "Authorization": f"Bearer {settings.todoist_api_token}",
    "Content-Type": "application/json"
}

# All 11 active tasks not returned by get_all_tasks()
ids_to_check = [
    ("Todoist-Notion-App-Report & Updates",                "6g2WxPFh7cC6g5v9"),
    ("New Sub Task from Notion to Parent Notion 002 Task", "6g93WM63WjV4gvr9"),
    ("Notion 001 Updated from Notion Notion",              "6g93JQp8c27RpjQ9"),
    ("New Sub Task Added from Notion",                     "6g93WMM2WFg3MV79"),
    ("Todo 002 002 002 002 Notion From Notion",            "6g93Hw4JrqCmmwH9"),
    ("Any Task not in the plan is the RED LINE.",          "6g95cpG26WwVhW2h"),
    ("Plan *today for tomorrow* from Todoist",             "6g95X7V53JX4w8F9"),
    ("Sub Task 002 from Todoist 002",                      "6g93Qw82frrVJQRh"),
    ("Todoist 001 001. Todoist Updated",                   "6g93HpMFMPWPVCvh"),
    ("Execute the Task as planned",                        "6g95c6mJXj7GX7g9"),
    ("Sub Task 001 from Todoist 001",                      "6g93QmvGFpqCW92h"),
]

# Fetch all Todoist projects for reference
print("\n" + "=" * 70)
print("📋 YOUR TODOIST PROJECTS")
print("=" * 70)

r = requests.get(
    "https://api.todoist.com/api/v1/projects",
    headers=headers
)
projects = {p["id"]: p["name"] for p in r.json().get("results", [])}

print(f"\n  Configured project ID: {settings.todoist_project_id}")
configured_name = projects.get(settings.todoist_project_id, "NOT FOUND!")
print(f"  Configured project:    {configured_name}\n")

print("  All your projects:")
for pid, pname in projects.items():
    marker = " ← CONFIGURED" if pid == settings.todoist_project_id else ""
    print(f"    [{pid}] {pname}{marker}")

# ── Check each task ───────────────────────────────────────────────────────────
print("\n\n" + "=" * 70)
print("🔍 TASK PROJECT ANALYSIS")
print("=" * 70)

same_project      = []
different_project = []

for title, task_id in ids_to_check:
    r = requests.get(
        f"https://api.todoist.com/api/v1/tasks/{task_id}",
        headers=headers
    )
    task       = r.json()
    project_id = task.get("project_id", "")
    project_nm = projects.get(project_id, f"Unknown [{project_id}]")
    is_yours   = project_id == settings.todoist_project_id
    parent_id  = task.get("parent_id", None)

    if is_yours:
        same_project.append((title, task_id, project_id, parent_id))
        print(f"\n  ✅ YOUR PROJECT: '{task.get('content', '')[:50]}'")
        print(f"     Project:  {project_nm} [{project_id}]")
        print(f"     Parent:   {parent_id or 'None (top-level)'}")
    else:
        different_project.append((title, task_id, project_id, project_nm))
        print(f"\n  ⚠️  DIFFERENT PROJECT: '{task.get('content', '')[:50]}'")
        print(f"     Project:  {project_nm} [{project_id}]")
        print(f"     Parent:   {parent_id or 'None (top-level)'}")

# ── Summary ───────────────────────────────────────────────────────────────────
print("\n\n" + "=" * 70)
print("📊 SUMMARY")
print("=" * 70)
print(f"\n  In YOUR project:       {len(same_project)}")
print(f"  In DIFFERENT project:  {len(different_project)}")

if different_project:
    print("\n\n" + "=" * 70)
    print("💡 DIAGNOSIS: Tasks in DIFFERENT project")
    print("=" * 70)

    # Group by project
    by_project = {}
    for title, tid, pid, pname in different_project:
        key = f"{pname} [{pid}]"
        by_project.setdefault(key, []).append((title, tid))

    for proj, tasks in by_project.items():
        print(f"\n  Project: {proj}")
        for title, tid in tasks:
            print(f"    • [{tid}] {title[:55]}")

    print(f"""
  ROOT CAUSE:
    These {len(different_project)} tasks are in a DIFFERENT Todoist project
    than the one configured in your .env file.

  OPTIONS:
    A) Update .env TODOIST_PROJECT_ID to include these tasks
       → If these tasks should be in your sync

    B) Move tasks to your configured project in Todoist
       → If you want them synced with Notion

    C) Remove their Todoist IDs from Notion
       → If these Notion pages should not be linked to Todoist
""")

elif same_project:
    print("\n\n" + "=" * 70)
    print("💡 DIAGNOSIS: All in YOUR project but not returned!")
    print("=" * 70)

    # Check if they have parents
    has_parent = [(t, tid, pid) for t, tid, pid, parent in same_project if parent]
    no_parent  = [(t, tid, pid) for t, tid, pid, parent in same_project if not parent]

    print(f"""
  All {len(same_project)} tasks ARE in your configured project
  but get_all_tasks() is not returning them!

  Tasks with parent (subtasks): {len(has_parent)}
  Tasks without parent:         {len(no_parent)}

  POSSIBLE CAUSE:
    → Pagination issue (tasks beyond cursor limit)
    → API returning partial results
    → Tasks in sub-sections not being fetched
""")
    print("\n  Task details:")
    for title, tid, pid, parent in same_project:
        print(f"    • [{tid}] {title[:50]}")
        print(f"      Parent: {parent or 'None'}")
