# Quick Start: Sync with Summary Reporting

## Files to Install

### 1. sync_summary.py (NEW)
**Download:** `sync_summary.py`
**Location:** Same folder as your other Python files
**Purpose:** Comprehensive change tracking and reporting

### 2. sync_engine.py (REPLACE)
**Download:** `sync_engine_WITH_SUMMARY.py`
**Action:** Rename to `sync_engine.py` and replace current file
**Changes:**
- Added `from sync_summary import SyncSummary, ChangeDetail`
- Added `self.summary = SyncSummary()` in __init__
- Tracks all changes in `_compute_field_updates()`
- Tracks task creation in `_create_notion_task()` and `_create_todoist_task()`
- Tracks conflicts
- Generates and prints report at end of sync
- Saves report to `sync_report.txt`

---

## Installation (2 Minutes)

### Step 1: Backup Current File

```batch
copy sync_engine.py sync_engine_BACKUP.py
```

### Step 2: Add New Files

```batch
# 1. Download sync_summary.py → Save to project folder
# 2. Download sync_engine_WITH_SUMMARY.py → Rename to sync_engine.py
```

### Step 3: Verify Files

Your project should have:
```
your-project/
├── sync_summary.py         ← NEW
├── sync_engine.py          ← REPLACED  
├── sync_state_manager.py
├── todoist_api.py
├── notion_api.py
├── models.py
├── config.py
└── main.py
```

---

## Test It

```batch
python main.py
```

**Expected Output:**

```
INFO - Starting sync cycle
INFO - Fetched 15 Todoist tasks, 15 Notion tasks
...
INFO - Sync cycle completed

======================================================================
📊 SYNC SUMMARY REPORT
======================================================================
⏱️  Duration: 2.34 seconds
📅 Completed: 2026-02-14 22:30:15

📈 OVERVIEW
----------------------------------------------------------------------
  Total Tasks Synced: 15
  Total Changes: 3
  Todoist → Notion: 2 changes
  Notion → Todoist: 1 changes

📤 TODOIST → NOTION CHANGES
----------------------------------------------------------------------
  TITLE (1 changes):
    • Weekly planning
      'Plan week' → 'Plan week - Updated'
  
  PRIORITY (1 changes):
    • Code review
      '1' → '3'

📥 NOTION → TODOIST CHANGES
----------------------------------------------------------------------
  DUE_DATE (1 changes):
    • Submit report
      '2026-02-15' → '2026-02-20'

======================================================================

Sync report saved to sync_report.txt
```

---

## What Gets Tracked

### ✅ Field Changes
- **Title** changes
- **Description** changes
- **Priority** changes
- **Due date** changes
- **Labels** changes
- **Completion** status

### ✅ Task Operations
- Tasks **created** in Notion
- Tasks **created** in Todoist
- Tasks **completed**
- Tasks **reopened**

### ✅ Conflicts
- When both systems change the same field
- Shows which value was used (resolution)

### ✅ Statistics
- Total tasks synced
- Total changes made
- Changes by direction (Todoist→Notion vs Notion→Todoist)
- Sync duration
- Error count

---

## Output Files

### Console Output
- Printed at end of every sync
- Detailed report with all changes
- Color-coded (in terminals that support it)

### sync_report.txt
- Saved automatically after each sync
- Full detailed report
- Can be shared with team
- Timestamped

---

## Customizing Summary

### Brief Summary (Less Detail)

Edit `sync_engine.py`, find this line:
```python
print("\n" + self.summary.generate_report(detailed=True))
```

Change to:
```python
print("\n" + self.summary.generate_report(detailed=False))
```

**Result:** Shows only overview stats, no field-by-field details

### No Console Output (File Only)

Comment out the print line:
```python
# print("\n" + self.summary.generate_report(detailed=True))
```

**Result:** Report saved to file, nothing printed to console

### Custom Report Filename

Change this line:
```python
self.summary.save_to_file("sync_report.txt")
```

To:
```python
from datetime import datetime
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
self.summary.save_to_file(f"sync_report_{timestamp}.txt")
```

**Result:** Timestamped report files (keeps history)

---

## Example Use Cases

### Scenario 1: Daily Sync Review

```batch
# Run your morning sync
python main.py

# Review what changed overnight
type sync_report.txt
```

**Benefit:** See what your team updated in Notion

### Scenario 2: Debugging Sync Issues

```batch
# Run sync with debug
python main.py --log-level DEBUG

# Check detailed report
type sync_report.txt
```

**Benefit:** Understand exactly why something didn't sync

### Scenario 3: Team Updates

```batch
# Run sync
python main.py

# Share report with team
copy sync_report.txt sync_report_20260214.txt
# Email or Slack the file
```

**Benefit:** Keep team informed of task changes

---

## Understanding the Report

### Overview Section
```
📈 OVERVIEW
  Total Tasks Synced: 15      ← How many tasks are synced
  Total Changes: 3             ← How many fields changed
  Todoist → Notion: 2 changes  ← Changes from Todoist
  Notion → Todoist: 1 changes  ← Changes from Notion
```

### Change Details
```
📤 TODOIST → NOTION CHANGES
  TITLE (1 changes):           ← Field name and count
    • Weekly planning          ← Task name
      'Plan week' → 'Updated'  ← Old value → New value
```

### Conflicts
```
⚠️  CONFLICTS RESOLVED
  • Task Name - field_name     ← Which task and field
    Resolution: Used Todoist   ← How it was resolved
```

---

## Troubleshooting

### Problem: No summary printed

**Check 1:** Is sync_summary.py in the same folder?
```batch
dir sync_summary.py
```

**Check 2:** Import error?
```batch
python -c "from sync_summary import SyncSummary; print('OK')"
```

**Fix:** Make sure both files are in the same directory

### Problem: Report file not created

**Reason:** Dry run mode enabled

**Check:**
```batch
# Look for this in output:
[DRY RUN]
```

**Fix:** Run without --dry-run flag
```batch
python main.py
```

### Problem: Empty report

**Reason:** No changes detected

**This is normal if:**
- Tasks already in sync
- No edits were made since last sync
- First sync after state file created

**Test:** Make a change and sync again

---

## Benefits

### ✅ Visibility
- See every change made
- Track data flow direction
- Understand what's happening

### ✅ Debugging
- Quickly identify sync issues
- See why tasks didn't sync
- Track down conflicts

### ✅ Confidence
- Verify sync worked correctly
- Confirm all changes propagated
- Catch issues early

### ✅ Audit Trail
- Record of all sync operations
- Historical changes
- Team accountability

---

## Summary

**Files:** 2 (sync_summary.py + updated sync_engine.py)  
**Installation Time:** 2 minutes  
**Result:** Professional sync reports!  
**Output:** Console + sync_report.txt  
**Tracking:** All changes, conflicts, task creation  

---

**Start using it now - you'll immediately see the value!** 📊✨
