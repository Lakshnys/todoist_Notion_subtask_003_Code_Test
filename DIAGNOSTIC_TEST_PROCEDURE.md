# Diagnostic Script - Test State-Based Sync

## What was fixed:

### Issue 1: State not saved for unchanged tasks
**Problem:** Only updated state when there were changes
**Fix:** Now updates state for ALL synced tasks

### Issue 2: First sync returned empty changes
**Problem:** When no stored state, returned empty dicts
**Fix:** On first sync, compares Todoist vs Notion and treats Todoist as primary

### Issue 3: Save only called in non-dry-run
**Problem:** State file not created in dry run
**Fix:** Now always saves state (even in dry run for testing)

---

## Test Procedure

### Test 1: First Sync (Creates State File)

```batch
# Run first sync
python main.py

# Expected:
# - Creates sync_state.json
# - Syncs any differences (Todoist → Notion)
# - File contains all task states
```

**Check:**
```batch
# Verify file exists
dir sync_state.json

# View content (first few lines)
type sync_state.json | more
```

**Expected content:**
```json
{
  "task_id_123": {
    "title": "Task title",
    "description": "...",
    "priority": 1,
    ...
  }
}
```

---

### Test 2: Edit in Todoist

```batch
# 1. Edit task in Todoist app
#    Change title: "Original" → "Todoist Edit 1"

# 2. Run sync
python main.py --log-level DEBUG

# 3. Check logs for:
#    "Task XXX: title changed in Todoist"
#    "Updating Notion task"
#    "Saved sync state for N tasks"

# 4. Check Notion
#    Should show "Todoist Edit 1"

# 5. Check sync_state.json
#    Should have "title": "Todoist Edit 1"
```

---

### Test 3: Edit in Notion

```batch
# 1. Edit same task in Notion
#    Change title: "Todoist Edit 1" → "Notion Edit 1"

# 2. Run sync
python main.py --log-level DEBUG

# 3. Check logs for:
#    "Task XXX: title changed in Notion"
#    "Updating Todoist task"
#    "Saved sync state for N tasks"

# 4. Check Todoist
#    Should show "Notion Edit 1"

# 5. Check sync_state.json
#    Should have "title": "Notion Edit 1"
```

---

### Test 4: No Changes

```batch
# Run sync without making any edits
python main.py --log-level DEBUG

# Expected:
# - "No updates needed" or similar
# - State still saved (refreshes timestamps)
# - No actual updates applied
```

---

## Debug Commands

### View sync_state.json

```batch
# Windows
type sync_state.json

# Or open in notepad
notepad sync_state.json
```

### Check if file exists

```batch
dir sync_state.json
```

### View with line numbers

```batch
type sync_state.json | findstr /N "title"
```

### Check file size

```batch
dir sync_state.json | findstr "sync_state"
```

---

## Expected Log Output

### First Sync:
```
INFO - --- Field-Level Updates ---
DEBUG - Task 123: First sync, comparing Todoist vs Notion
DEBUG -   title: Todoist='My Task' vs Notion='My Task' → Use Todoist
INFO - Updated sync state for task 123
INFO - Saved sync state for 5 tasks to sync_state.json
```

### After Todoist Edit:
```
INFO - --- Field-Level Updates ---
DEBUG - Task 123: title changed in Todoist
INFO - Updating Notion task: title changed (from Todoist)
DEBUG - Updated sync state for task 123
INFO - Saved sync state for 5 tasks to sync_state.json
```

### After Notion Edit:
```
INFO - --- Field-Level Updates ---
DEBUG - Task 123: title changed in Notion
INFO - Updating Todoist task: title changed (from Notion)
DEBUG - Updated sync state for task 123
INFO - Saved sync state for 5 tasks to sync_state.json
```

---

## Troubleshooting

### Problem: sync_state.json not created

**Check 1:** Is sync_state_manager.py in the same directory?
```batch
dir sync_state_manager.py
```

**Check 2:** Are there any import errors?
```batch
python -c "from sync_state_manager import SyncStateManager; print('OK')"
```

**Check 3:** Run with debug logging:
```batch
python main.py --log-level DEBUG 2>&1 | findstr "state"
```

### Problem: Changes not detected

**Check 1:** Does sync_state.json have entries?
```batch
type sync_state.json
```

**Check 2:** Are the stored values correct?
- Open sync_state.json
- Find your task ID
- Check if values match current state

**Check 3:** Run with DEBUG and check detection:
```batch
python main.py --log-level DEBUG 2>&1 | findstr "changed"
```

### Problem: All changes treated as Todoist changes

**This is normal on first sync!**
- First sync: No stored state → Todoist wins
- Second sync onwards: State exists → Real detection

---

## Success Criteria

✅ sync_state.json created on first run
✅ File contains entries for all synced tasks
✅ Todoist edits detected and synced to Notion
✅ Notion edits detected and synced to Todoist
✅ Alternating edits work correctly
✅ State file updated after each sync

---

## Manual State Reset

If you want to test first sync again:

```batch
# Delete state file
del sync_state.json

# Run sync again
python main.py
```

This will treat it as first sync again.

---

## File Location

`sync_state.json` should be created in the same directory as your `main.py`

If it's not there, check:
1. Current working directory when running script
2. Write permissions in that directory
3. Any errors in the logs

---

## Next Steps

1. Run first sync and verify file is created
2. Make a test edit in Todoist
3. Run sync and verify it propagates
4. Make a test edit in Notion
5. Run sync and verify it propagates

If all 5 steps work → Success! 🎉

If any step fails → Share the debug logs from that step
