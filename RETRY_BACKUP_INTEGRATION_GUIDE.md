# Integration Guide: Retry Logic + State Backup

## Overview

This guide shows how to integrate the retry logic and state backup features into your sync engine.

---

## Part 1: Add Retry Logic to API Clients

### notion_api.py Changes

**Add import at top:**
```python
from retry_utils import retry_on_failure
```

**Wrap critical methods with retry decorator:**

#### Example 1: Update Task
```python
@retry_on_failure(max_retries=3, backoff_base=2.0)
def update_task(
    self,
    page_id: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    priority: Optional[int] = None,
    due_date: Optional[datetime] = None,
    completed: Optional[bool] = None,
    labels: Optional[List[str]] = None,
    todoist_task_id: Optional[str] = None,
    last_modified_source: Optional[TaskSource] = None
) -> None:
    # ... existing code ...
```

#### Example 2: Create Task
```python
@retry_on_failure(max_retries=3, backoff_base=2.0)
def create_task(
    self,
    title: str,
    todoist_task_id: str,
    description: str = "",
    priority: int = 1,
    due_date: Optional[datetime] = None,
    completed: bool = False,
    labels: Optional[List[str]] = None,
    parent_todoist_id: Optional[str] = None,
    source: TaskSource = TaskSource.TODOIST
) -> str:
    # ... existing code ...
```

#### Example 3: Get All Tasks
```python
@retry_on_failure(max_retries=3, backoff_base=2.0)
def get_all_tasks(self) -> List[NotionTask]:
    # ... existing code ...
```

---

### todoist_api.py Changes

**Add import at top:**
```python
from retry_utils import retry_on_failure
```

**Wrap critical methods:**

```python
@retry_on_failure(max_retries=3, backoff_base=2.0)
def get_all_tasks(self) -> List[TodoistTask]:
    # ... existing code ...

@retry_on_failure(max_retries=3, backoff_base=2.0)
def create_task(self, content: str, ...) -> TodoistTask:
    # ... existing code ...

@retry_on_failure(max_retries=3, backoff_base=2.0)
def update_task(self, task_id: str, ...) -> TodoistTask:
    # ... existing code ...

@retry_on_failure(max_retries=3, backoff_base=2.0)
def complete_task(self, task_id: str) -> bool:
    # ... existing code ...
```

---

## Part 2: Integrate State Backup into Sync Engine

### sync_engine.py Changes

**Update run_sync method:**

```python
def run_sync(self) -> SyncStats:
    """Execute a complete sync cycle with backup and error recovery."""
    logger.info("=" * 60)
    logger.info("Starting sync cycle")
    logger.info("=" * 60)
    
    try:
        # Check for incomplete previous sync
        if self.state_manager.check_incomplete_sync():
            logger.warning("⚠️  Previous sync was interrupted!")
            logger.warning("You may want to verify data integrity.")
            # Optionally: prompt user to restore from backup
        
        # Create backup before sync
        logger.info("Creating state backup...")
        backup_file = self.state_manager.backup_state()
        if backup_file:
            logger.info(f"✅ Backup created: {backup_file.name}")
        
        # Mark sync as in progress
        self.state_manager.mark_sync_in_progress()
        
        # Step 1: Fetch all tasks
        todoist_tasks = self.todoist.get_all_tasks()
        notion_tasks = self.notion.get_all_tasks()
        
        self.stats.todoist_tasks_fetched = len(todoist_tasks)
        self.stats.notion_tasks_fetched = len(notion_tasks)
        
        logger.info(f"Fetched {len(todoist_tasks)} Todoist tasks, {len(notion_tasks)} Notion tasks")
        
        # ... (rest of existing sync logic) ...
        
        # After successful sync, clear in-progress marker
        self.state_manager.clear_sync_in_progress()
        
        logger.info("=" * 60)
        logger.info("Sync cycle completed successfully")
        logger.info(str(self.stats))
        logger.info("=" * 60)
        
        # Print summary report
        print("\n" + self.summary.generate_report(detailed=True))
        
        # Save report to file
        if not settings.dry_run:
            self.summary.save_to_file("sync_report.txt")
        
        return self.stats
        
    except Exception as e:
        logger.error(f"Sync cycle failed: {e}", exc_info=True)
        self.stats.errors += 1
        self.summary.errors.append(str(e))
        
        # Clear in-progress marker even on failure
        self.state_manager.clear_sync_in_progress()
        
        # Log backup location for recovery
        backups = self.state_manager.list_backups()
        if backups:
            logger.error(f"💾 You can restore from backup: {backups[0].name}")
            logger.error(f"   Use: python -c \"from sync_state_manager import SyncStateManager; SyncStateManager().restore_from_backup()\"")
        
        raise
```

---

## Part 3: Add Manual Restore Command

Create a standalone script for manual state restoration:

### restore_state.py (new file)

```python
"""
Manual state restoration utility.
Use this to restore sync state from a backup.
"""

import sys
from pathlib import Path
from sync_state_manager import SyncStateManager

def main():
    manager = SyncStateManager()
    
    # List available backups
    backups = manager.list_backups()
    
    if not backups:
        print("❌ No backup files found")
        return 1
    
    print("📋 Available backups:")
    for i, backup in enumerate(backups, 1):
        size = backup.stat().st_size / 1024  # KB
        mtime = backup.stat().st_mtime
        from datetime import datetime
        timestamp = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
        print(f"  {i}. {backup.name} ({size:.1f} KB) - {timestamp}")
    
    # Prompt user
    choice = input("\nEnter backup number to restore (or 'q' to quit): ")
    
    if choice.lower() == 'q':
        print("Cancelled")
        return 0
    
    try:
        idx = int(choice) - 1
        if idx < 0 or idx >= len(backups):
            print("❌ Invalid backup number")
            return 1
        
        backup_file = backups[idx]
        print(f"\n⚠️  This will restore state from: {backup_file.name}")
        confirm = input("Continue? (yes/no): ")
        
        if confirm.lower() != 'yes':
            print("Cancelled")
            return 0
        
        # Restore
        if manager.restore_from_backup(backup_file):
            print(f"✅ Successfully restored state from {backup_file.name}")
            return 0
        else:
            print(f"❌ Failed to restore state")
            return 1
            
    except ValueError:
        print("❌ Invalid input")
        return 1

if __name__ == "__main__":
    sys.exit(main())
```

**Usage:**
```bash
python restore_state.py
```

---

## Part 4: Add Validation

Add validation before applying changes to prevent bad data corruption:

### In sync_engine.py, add validation method:

```python
def _validate_field_update(self, update: FieldUpdate) -> bool:
    """
    Validate a field update before applying.
    
    Args:
        update: FieldUpdate to validate
        
    Returns:
        True if valid, False if should be skipped
    """
    # Validate priority range
    if update.field_name == 'priority' or update.field_name == 'Priority':
        if not isinstance(update.new_value, int):
            logger.error(f"Invalid priority type: {type(update.new_value)}")
            return False
        if not (1 <= update.new_value <= 4):
            logger.error(f"Priority out of range: {update.new_value}")
            return False
    
    # Validate title length
    if update.field_name == 'title' or update.field_name == 'Title':
        if not update.new_value:
            logger.error("Empty title not allowed")
            return False
        if len(str(update.new_value)) > 500:
            logger.warning(f"Title too long ({len(update.new_value)} chars), truncating")
            update.new_value = str(update.new_value)[:500]
    
    # Validate labels
    if update.field_name == 'labels' or update.field_name == 'Labels':
        if not isinstance(update.new_value, list):
            logger.error(f"Invalid labels type: {type(update.new_value)}")
            return False
        # Filter out invalid labels
        valid_labels = [l for l in update.new_value if isinstance(l, str) and len(l) > 0]
        if len(valid_labels) != len(update.new_value):
            logger.warning(f"Filtered invalid labels: {len(update.new_value)} → {len(valid_labels)}")
            update.new_value = valid_labels
    
    return True
```

**Then use it in _apply_notion_updates and _apply_todoist_updates:**

```python
def _apply_notion_updates(self, page_id: str, updates: List[FieldUpdate]) -> None:
    """Apply field updates to a Notion task."""
    # Validate all updates first
    valid_updates = []
    for update in updates:
        if self._validate_field_update(update):
            valid_updates.append(update)
        else:
            logger.warning(f"Skipping invalid update: {update.field_name}")
            self.summary.errors.append(f"Invalid update skipped: {update.field_name}")
    
    if not valid_updates:
        logger.debug(f"No valid updates for Notion task {page_id}")
        return
    
    # ... rest of existing code using valid_updates ...
```

---

## Testing the Implementation

### Test 1: Verify Backup Creation

```bash
# Run sync
python main.py

# Check for backups
ls -lh sync_state_backup_*.json

# Should see:
# sync_state_backup_20260215_143022.json
# sync_state_backup_20260215_142815.json
# etc.
```

### Test 2: Test Retry Logic

Temporarily disconnect network during sync - should see retry attempts in logs:

```
WARNING - update_task failed (attempt 1/3): Connection timeout
INFO - Retrying in 2.0 seconds...
WARNING - update_task failed (attempt 2/3): Connection timeout
INFO - Retrying in 4.0 seconds...
INFO - Successfully updated task (after 3 attempts)
```

### Test 3: Test State Restoration

```bash
# Corrupt state file (for testing)
echo "invalid json" > sync_state.json

# Restore from backup
python restore_state.py

# Select backup and confirm
# State should be restored
```

### Test 4: Test Incomplete Sync Detection

```bash
# Kill sync mid-run (Ctrl+C)
python main.py
^C

# Run again - should detect incomplete sync
python main.py
# Output:
# WARNING - ⚠️  Previous sync was interrupted!
# WARNING - You may want to verify data integrity.
```

---

## Summary of Changes

| File | Changes | Purpose |
|------|---------|---------|
| `retry_utils.py` | New file | Retry decorators and rate limiter |
| `sync_state_manager.py` | +150 lines | Backup, restore, cleanup methods |
| `notion_api.py` | Decorators on 3-5 methods | Retry on network failures |
| `todoist_api.py` | Decorators on 3-5 methods | Retry on network failures |
| `sync_engine.py` | +30 lines | Backup creation, validation, error handling |
| `restore_state.py` | New file | Manual restoration utility |

---

## Expected Benefits

✅ **Resilience:** Auto-retry on transient failures (network, API rate limits)  
✅ **Data Safety:** Backups before every sync  
✅ **Recovery:** Easy restoration from backups  
✅ **Detection:** Identifies interrupted syncs  
✅ **Validation:** Prevents bad data corruption  
✅ **Logging:** Clear error messages with recovery steps  

---

## Quick Implementation Checklist

- [ ] Add `retry_utils.py`
- [ ] Update `sync_state_manager.py` with backup methods
- [ ] Add retry decorators to `notion_api.py` methods
- [ ] Add retry decorators to `todoist_api.py` methods
- [ ] Update `sync_engine.py` run_sync method
- [ ] Add validation method to `sync_engine.py`
- [ ] Create `restore_state.py` utility
- [ ] Test backup creation
- [ ] Test retry logic
- [ ] Test state restoration

---

**Ready to implement! Follow the checklist and your sync will be bulletproof!** 🛡️✅
