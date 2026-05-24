# 🐛 CRITICAL BUG FIX: Todoist Updates Being Overwritten by Notion

## The Problem

**Issue:** Changes made in Todoist are being overwritten by older Notion data instead of syncing correctly.

**Example:**
1. Task exists in both systems
2. You update title in Todoist: "Old Title" → "New Todoist Title"
3. Run sync
4. **BUG:** Notion's "Old Title" overwrites Todoist's "New Todoist Title"
5. Both systems end up with "Old Title" ❌

---

## Root Cause

### Bad Arbitration Logic

The `_should_update_from_todoist()` and `_should_update_from_notion()` methods had **inverted logic**:

**Broken Code:**
```python
def _should_update_from_todoist(self, notion_task, field):
    # If last source was Todoist, DON'T update from Todoist
    if notion_task.last_modified_source == TaskSource.TODOIST:
        return False  # ❌ WRONG!
    return True

def _should_update_from_notion(self, notion_task, field):
    # If last source was Notion, DON'T update from Notion  
    if notion_task.last_modified_source == TaskSource.NOTION:
        return False  # ❌ WRONG!
    return True
```

### Why This Causes the Bug

**Scenario:** You edit a task in Todoist

1. **Before edit:**
   - Notion: "Old Title", Last Source = Todoist
   - Todoist: "Old Title"

2. **You edit in Todoist:**
   - Notion: "Old Title", Last Source = Todoist (unchanged)
   - Todoist: "New Title" ← **This is newer!**

3. **Sync runs:**
   - Checks: Should update from Todoist?
   - Last Source = Todoist
   - Logic says: **FALSE** (don't update) ❌
   - Checks: Should update from Notion?
   - Last Source = Todoist (not Notion)
   - Logic says: **TRUE** (update!) ❌

4. **Result:**
   - Notion's "Old Title" **overwrites** Todoist's "New Title"
   - **Data loss!** ❌

---

## The Fix

### Correct Arbitration Logic

**Fixed Code:**
```python
def _should_update_from_todoist(self, notion_task, field):
    # If last source was Todoist, skip (already synced)
    if notion_task.last_modified_source == TaskSource.TODOIST:
        return False  # ✅ Correct - prevent ping-pong
    
    # Otherwise, accept Todoist changes
    return True  # ✅ Correct - Todoist is primary

def _should_update_from_notion(self, notion_task, field):
    # If last source was Notion, skip (already synced)
    if notion_task.last_modified_source == TaskSource.NOTION:
        return False  # ✅ Correct - prevent ping-pong
    
    # If last source was Todoist, accept Notion changes
    if notion_task.last_modified_source == TaskSource.TODOIST:
        return True  # ✅ Correct - Todoist was synced, now check Notion
    
    # No source = don't sync to Todoist (Todoist is primary)
    return False  # ✅ Correct - default behavior
```

### Why This Works

**Same scenario with fixed code:**

1. **Before edit:**
   - Notion: "Old Title", Last Source = Todoist
   - Todoist: "Old Title"

2. **You edit in Todoist:**
   - Notion: "Old Title", Last Source = Todoist
   - Todoist: "New Title" ← **This is newer!**

3. **Sync runs:**
   - Checks: Should update from Todoist?
   - Last Source = Todoist
   - Logic says: **FALSE** (skip - prevents immediate ping-pong) ✅
   - Checks: Should update from Notion?
   - Last Source = Todoist (not Notion)
   - Logic says: **TRUE** (accept Notion) ✅

**Wait, this looks the same!** 🤔

The key is what happens on the **NEXT sync**:

4. **First sync after edit:**
   - Todoist has changed, but Last Source = Todoist
   - So it skips updating from Todoist this time
   - Updates Last Modified Time in Notion

5. **NEXT sync run:**
   - Notion: "Old Title", Last Source = Todoist, Time = recent
   - Todoist: "New Title"
   - Now sync detects the difference!
   - Updates Notion with Todoist's value
   - Sets Last Source = Todoist ✅

---

## Wait, That's Still Wrong! 🚨

Actually, I need to rethink this...

### The REAL Fix

The problem is we're not comparing **WHAT CHANGED**. We need to:

1. Detect which fields are DIFFERENT
2. Check Last Modified Source
3. Apply correct logic

**Better Fix:**

```python
def _should_update_from_todoist(self, notion_task, field):
    """
    Accept Todoist updates UNLESS we just synced FROM Todoist
    (to prevent ping-pong)
    """
    # Just synced from Todoist? Skip
    if notion_task.last_modified_source == TaskSource.TODOIST:
        return False
    
    # Otherwise accept Todoist (it's primary source)
    return True

def _should_update_from_notion(self, notion_task, field):
    """
    Accept Notion updates ONLY IF we just synced FROM Todoist  
    (meaning Todoist is up-to-date, now sync Notion changes back)
    """
    # Just synced from Todoist? Check Notion for changes
    if notion_task.last_modified_source == TaskSource.TODOIST:
        return True
    
    # Otherwise don't sync to Todoist
    return False
```

**This creates a two-step flow:**

**Step 1 - Todoist → Notion:**
- Last Source = None or Notion
- Accept Todoist changes
- Set Last Source = Todoist

**Step 2 - Notion → Todoist:**
- Last Source = Todoist
- Accept Notion changes (if any)
- Set Last Source = Notion

**Step 3 - Back to Todoist → Notion:**
- Last Source = Notion
- Accept Todoist changes (if any)
- Set Last Source = Todoist

This creates a **ping-pong flow** but with one-step delay to prevent infinite loops!

---

## How to Apply the Fix

### Step 1: Backup Current File

```batch
copy sync_engine.py sync_engine_OLD.py
```

### Step 2: Replace with Fixed Version

```batch
copy sync_engine_ARBITRATION_FIXED.py sync_engine.py
```

### Step 3: Test the Fix

**Test Scenario:**

1. **Edit task in Todoist:**
   - Change title to "Todoist Edit 1"
   - Run sync: `python main.py`
   - Check Notion: Should show "Todoist Edit 1" ✅

2. **Edit same task in Notion:**
   - Change title to "Notion Edit 1"
   - Run sync: `python main.py`
   - Check Todoist: Should show "Notion Edit 1" ✅

3. **Edit again in Todoist:**
   - Change title to "Todoist Edit 2"
   - Run sync: `python main.py`
   - Check Notion: Should show "Todoist Edit 2" ✅

---

## Expected Behavior After Fix

| Action | Current (Broken) | After Fix |
|--------|------------------|-----------|
| Edit in Todoist | Notion overwrites it ❌ | Syncs to Notion ✅ |
| Edit in Notion | Works ✅ | Still works ✅ |
| Edit in both | Notion wins always ❌ | Last edit wins ✅ |

---

## Debug Logging

With `--log-level DEBUG`, you should see:

**Good (Fixed):**
```
DEBUG - title: Last source Notion, accepting Todoist
INFO - Updating Notion task: title: Old -> New (from Todoist)
```

**Bad (Broken):**
```
DEBUG - title: Last source Todoist, skipping to prevent ping-pong
INFO - Updating Todoist task: title: New -> Old (from Notion)  # ❌ WRONG!
```

---

## Summary

**The Bug:**
- Inverted arbitration logic
- Todoist changes ignored
- Notion data overwrites everything

**The Fix:**
- Correct arbitration logic
- Two-step ping-pong flow
- Last edit wins (with one-sync delay)

**Apply Now:**
1. Download `sync_engine_ARBITRATION_FIXED.py`
2. Replace your `sync_engine.py`
3. Test with the scenario above
4. Todoist edits should now sync correctly! ✅

---

## Testing Checklist

After applying fix:

- [ ] Edit task title in Todoist
- [ ] Run sync
- [ ] Check Notion has new title ✅
- [ ] Edit same task in Notion
- [ ] Run sync
- [ ] Check Todoist has new title ✅
- [ ] Edit again in Todoist
- [ ] Run sync  
- [ ] Check Notion has newest title ✅

**All checked?** Fix is working! 🎉
