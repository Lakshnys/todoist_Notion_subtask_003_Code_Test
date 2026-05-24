# Integration Guide: Adding Summary Reporting

## Files to Add

1. **sync_summary.py** (NEW) - Summary reporting module
2. **sync_engine.py** (UPDATE) - Add summary tracking

---

## Step 1: Update sync_engine.py Imports

At the top of `sync_engine.py`, add:

```python
from sync_summary import SyncSummary, ChangeDetail
```

---

## Step 2: Initialize Summary in __init__

In the `SyncEngine.__init__` method:

```python
def __init__(self, todoist_client: TodoistClient, notion_client: NotionClient):
    self.todoist = todoist_client
    self.notion = notion_client
    self.state_manager = SyncStateManager()
    self.summary = SyncSummary()  # NEW: Add this line
    self.stats = SyncStats()
    self.decisions: List[SyncDecision] = []
```

---

## Step 3: Track Changes in _compute_field_updates

Replace the `_compute_field_updates` method to track changes:

```python
def _compute_field_updates(
    self,
    todoist_task: TodoistTask,
    notion_task: NotionTask
) -> Tuple[List[FieldUpdate], List[FieldUpdate]]:
    """Compute field updates and track changes for summary."""
    notion_updates: List[FieldUpdate] = []
    todoist_updates: List[FieldUpdate] = []
    
    todoist_model = todoist_task.to_task()
    notion_model = notion_task.to_task()
    
    # Three-way merge
    changes = self.state_manager.detect_changes(
        todoist_model,
        notion_model,
        todoist_task.id
    )
    
    # Track Todoist → Notion changes
    for field, new_value in changes['todoist_changed'].items():
        logger.info(f"Task {todoist_task.id}: {field} changed in Todoist")
        
        # Add to updates list
        notion_updates.append(FieldUpdate(
            field_name=field,
            old_value=getattr(notion_model, field),
            new_value=new_value,
            source=TaskSource.TODOIST,
            timestamp=datetime.utcnow()
        ))
        
        # NEW: Track for summary
        self.summary.add_change(ChangeDetail(
            task_id=todoist_task.id,
            task_title=todoist_model.title,
            field=field,
            old_value=getattr(notion_model, field),
            new_value=new_value,
            source="Todoist",
            change_type="updated"
        ))
    
    # Track Notion → Todoist changes
    for field, new_value in changes['notion_changed'].items():
        logger.info(f"Task {todoist_task.id}: {field} changed in Notion")
        
        todoist_field = 'content' if field == 'title' else field
        todoist_updates.append(FieldUpdate(
            field_name=todoist_field,
            old_value=getattr(todoist_model, field),
            new_value=new_value,
            source=TaskSource.NOTION,
            timestamp=datetime.utcnow()
        ))
        
        # NEW: Track for summary
        self.summary.add_change(ChangeDetail(
            task_id=todoist_task.id,
            task_title=todoist_model.title,
            field=field,
            old_value=getattr(todoist_model, field),
            new_value=new_value,
            source="Notion",
            change_type="updated"
        ))
    
    # Track conflicts
    if changes['conflicts']:
        logger.warning(f"Task {todoist_task.id} has conflicts: {list(changes['conflicts'].keys())}")
        
        for field, values in changes['conflicts'].items():
            logger.warning(f"  {field}: Todoist='{values['todoist']}' vs Notion='{values['notion']}'")
            logger.info(f"  Resolution: Using Todoist value for {field}")
            
            # Add to updates
            notion_updates.append(FieldUpdate(
                field_name=field,
                old_value=values['notion'],
                new_value=values['todoist'],
                source=TaskSource.TODOIST,
                timestamp=datetime.utcnow()
            ))
            
            # NEW: Track conflict
            self.summary.add_change(ChangeDetail(
                task_id=todoist_task.id,
                task_title=todoist_model.title,
                field=field,
                old_value=values['notion'],
                new_value=values['todoist'],
                source="Todoist",
                change_type="conflict"
            ))
    
    return notion_updates, todoist_updates
```

---

## Step 4: Track Task Creation

In `_create_notion_task` method, add after creating the task:

```python
def _create_notion_task(self, todoist_task: TodoistTask) -> None:
    """Create task in Notion and track in summary."""
    # ... existing code ...
    
    self.notion.create_task(
        title=todoist_task.content,
        todoist_task_id=todoist_task.id,
        # ... other params ...
    )
    
    # NEW: Track creation
    self.summary.tasks_created_in_notion.append(todoist_task.content)
```

Similarly for `_create_todoist_task`:

```python
def _create_todoist_task(self, notion_task: NotionTask) -> None:
    """Create task in Todoist and track in summary."""
    # ... existing code ...
    
    created_task = self.todoist.create_task(
        content=notion_task.title,
        # ... other params ...
    )
    
    # NEW: Track creation
    self.summary.tasks_created_in_todoist.append(notion_task.title)
```

---

## Step 5: Track Completion Changes

In the completion handling code, add:

```python
# When completing a task
if task_completed:
    self.summary.tasks_completed.append(task_title)

# When reopening a task
if task_reopened:
    self.summary.tasks_reopened.append(task_title)
```

---

## Step 6: Generate Report at End of Sync

In the `run_sync` method, at the end:

```python
def run_sync(self) -> SyncStats:
    """Execute sync and generate summary."""
    try:
        # ... existing sync logic ...
        
        # NEW: Finalize and print summary
        self.summary.total_tasks_synced = len(notion_index)
        self.summary.finalize()
        
        # Print summary to console
        print("\n" + self.summary.generate_report(detailed=True))
        
        # Save to file
        self.summary.save_to_file("sync_report.txt")
        
        return self.stats
        
    except Exception as e:
        self.summary.errors.append(str(e))
        raise
```

---

## Step 7: Add Command Line Option

In `main.py`, add option for summary detail level:

```python
parser.add_argument(
    '--summary',
    choices=['none', 'brief', 'detailed'],
    default='detailed',
    help='Summary report detail level'
)

# Then use it:
if args.summary != 'none':
    detailed = (args.summary == 'detailed')
    print(engine.summary.generate_report(detailed=detailed))
```

---

## Example Output

### Brief Summary:
```
======================================================================
📊 SYNC SUMMARY REPORT
======================================================================
⏱️  Duration: 2.34 seconds
📅 Completed: 2026-02-14 22:30:15

📈 OVERVIEW
----------------------------------------------------------------------
  Total Tasks Synced: 15
  Total Changes: 8
  Todoist → Notion: 5 changes
  Notion → Todoist: 3 changes
  ⚠️  Conflicts Resolved: 0

✨ NEW TASKS
----------------------------------------------------------------------
  Created in Notion: 2
    • Buy groceries
    • Call dentist

✅ COMPLETION STATUS
----------------------------------------------------------------------
  Completed: 1
    ✓ Finish project report

======================================================================
```

### Detailed Summary:
```
======================================================================
📊 SYNC SUMMARY REPORT
======================================================================
⏱️  Duration: 2.34 seconds
📅 Completed: 2026-02-14 22:30:15

📈 OVERVIEW
----------------------------------------------------------------------
  Total Tasks Synced: 15
  Total Changes: 8
  Todoist → Notion: 5 changes
  Notion → Todoist: 3 changes

📤 TODOIST → NOTION CHANGES
----------------------------------------------------------------------
  TITLE (2 changes):
    • Weekly planning
      'Plan week' → 'Plan week - Updated'
    • Team meeting
      'Meeting' → 'Team sync meeting'
  
  PRIORITY (2 changes):
    • Code review
      '1' → '3'
    • Bug fix
      '2' → '4'
  
  DESCRIPTION (1 changes):
    • Project proposal
      '(empty)' → 'Need to include budget section'

📥 NOTION → TODOIST CHANGES
----------------------------------------------------------------------
  DUE_DATE (2 changes):
    • Submit report
      '2026-02-15' → '2026-02-20'
    • Review PR
      '(empty)' → '2026-02-16'
  
  LABELS (1 changes):
    • Research task
      '[]' → '[work, urgent]'

✅ COMPLETION STATUS
----------------------------------------------------------------------
  Completed: 1
    ✓ Finish project report

✅ NO CONFLICTS
======================================================================
```

---

## Additional Robustness Features

### 1. State Backup

Add to `sync_state_manager.py`:

```python
def backup_state(self) -> None:
    """Create backup of current state."""
    import shutil
    backup_file = f"{self.state_file}.backup"
    if self.state_file.exists():
        shutil.copy(self.state_file, backup_file)
        logger.info(f"State backed up to {backup_file}")

def restore_state(self) -> bool:
    """Restore state from backup."""
    backup_file = Path(f"{self.state_file}.backup")
    if backup_file.exists():
        import shutil
        shutil.copy(backup_file, self.state_file)
        self.load_state()
        logger.info("State restored from backup")
        return True
    return False
```

### 2. Error Recovery

Add retry logic:

```python
def retry_on_failure(func, max_retries=3):
    """Retry function on failure."""
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            logger.warning(f"Attempt {attempt + 1} failed: {e}, retrying...")
            time.sleep(2 ** attempt)  # Exponential backoff
```

### 3. Validation

Add before saving:

```python
def validate_changes(self, changes):
    """Validate changes before applying."""
    for change in changes:
        # Check if values are valid
        if change.field == 'priority' and not (1 <= change.new_value <= 4):
            raise ValueError(f"Invalid priority: {change.new_value}")
        # Add more validations...
```

---

## Testing the Summary

```batch
# Run sync
python main.py

# Check console output for summary

# Check generated file
type sync_report.txt
```

---

## Benefits

✅ **Visibility:** See exactly what changed  
✅ **Debugging:** Track down issues easily  
✅ **Audit Trail:** Keep record of all changes  
✅ **Confidence:** Verify sync worked correctly  
✅ **Reports:** Share sync results with team  

---

## Summary

**New Files:**
- sync_summary.py (comprehensive reporting)

**Updated Files:**
- sync_engine.py (add summary tracking)
- main.py (optional: summary level flag)

**Output:**
- Console: Formatted summary
- File: sync_report.txt (detailed report)

**Result:** Professional sync reporting! 📊✨
