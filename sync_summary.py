"""
Enhanced Sync Summary Reporter
Provides detailed change tracking and reporting for sync operations.
"""

import logging
from typing import List, Dict, Any
from datetime import datetime
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ChangeDetail:
    """Detailed information about a single field change."""
    task_id: str
    task_title: str
    field: str
    old_value: Any
    new_value: Any
    source: str  # "Todoist" or "Notion"
    change_type: str  # "updated", "added", "removed", "conflict"
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    def __str__(self) -> str:
        """Format change for display."""
        if self.change_type == "conflict":
            return f"⚠️  {self.task_title} - {self.field}: CONFLICT resolved (used {self.source})"
        elif self.change_type == "added":
            return f"✨ {self.task_title} - {self.field}: Added '{self.new_value}'"
        elif self.change_type == "removed":
            return f"🗑️  {self.task_title} - {self.field}: Removed"
        else:
            return f"📝 {self.task_title} - {self.field}: '{self.old_value}' → '{self.new_value}'"


@dataclass
class SyncSummary:
    """Comprehensive summary of a sync operation."""
    
    # Timestamps
    sync_start: datetime = field(default_factory=datetime.utcnow)
    sync_end: datetime = None
    
    # Task creation/deletion
    tasks_created_in_notion: List[str] = field(default_factory=list)
    tasks_created_in_todoist: List[str] = field(default_factory=list)
    tasks_completed: List[str] = field(default_factory=list)
    tasks_reopened: List[str] = field(default_factory=list)
    
    # Field changes
    todoist_to_notion: List[ChangeDetail] = field(default_factory=list)
    notion_to_todoist: List[ChangeDetail] = field(default_factory=list)
    conflicts_resolved: List[ChangeDetail] = field(default_factory=list)
    
    # Statistics
    total_tasks_synced: int = 0
    total_changes: int = 0
    errors: List[str] = field(default_factory=list)
    
    def add_change(self, change: ChangeDetail) -> None:
        """Add a change to the appropriate list."""
        if change.change_type == "conflict":
            self.conflicts_resolved.append(change)
        elif change.source == "Todoist":
            self.todoist_to_notion.append(change)
        else:
            self.notion_to_todoist.append(change)
        
        self.total_changes += 1
    
    def finalize(self) -> None:
        """Mark sync as complete and calculate final stats."""
        self.sync_end = datetime.utcnow()
    
    def get_duration(self) -> float:
        """Get sync duration in seconds."""
        if self.sync_end:
            return (self.sync_end - self.sync_start).total_seconds()
        return 0.0
    
    def has_changes(self) -> bool:
        """Check if any changes were made."""
        return (
            len(self.todoist_to_notion) > 0 or
            len(self.notion_to_todoist) > 0 or
            len(self.tasks_created_in_notion) > 0 or
            len(self.tasks_created_in_todoist) > 0 or
            len(self.conflicts_resolved) > 0
        )
    
    def generate_report(self, detailed: bool = True) -> str:
        """
        Generate formatted summary report.
        
        Args:
            detailed: Include detailed change list
            
        Returns:
            Formatted report string
        """
        lines = []
        lines.append("=" * 70)
        lines.append("📊 SYNC SUMMARY REPORT")
        lines.append("=" * 70)
        
        # Duration
        duration = self.get_duration()
        lines.append(f"⏱️  Duration: {duration:.2f} seconds")
        lines.append(f"📅 Completed: {self.sync_end.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")
        
        # Overview Statistics
        lines.append("📈 OVERVIEW")
        lines.append("-" * 70)
        lines.append(f"  Total Tasks Synced: {self.total_tasks_synced}")
        lines.append(f"  Total Changes: {self.total_changes}")
        lines.append(f"  Todoist → Notion: {len(self.todoist_to_notion)} changes")
        lines.append(f"  Notion → Todoist: {len(self.notion_to_todoist)} changes")
        if self.conflicts_resolved:
            lines.append(f"  ⚠️  Conflicts Resolved: {len(self.conflicts_resolved)}")
        lines.append("")
        
        # Task Creation/Deletion
        if self.tasks_created_in_notion or self.tasks_created_in_todoist:
            lines.append("✨ NEW TASKS")
            lines.append("-" * 70)
            if self.tasks_created_in_notion:
                lines.append(f"  Created in Notion: {len(self.tasks_created_in_notion)}")
                for task in self.tasks_created_in_notion[:5]:
                    lines.append(f"    • {task}")
                if len(self.tasks_created_in_notion) > 5:
                    lines.append(f"    ... and {len(self.tasks_created_in_notion) - 5} more")
            
            if self.tasks_created_in_todoist:
                lines.append(f"  Created in Todoist: {len(self.tasks_created_in_todoist)}")
                for task in self.tasks_created_in_todoist[:5]:
                    lines.append(f"    • {task}")
                if len(self.tasks_created_in_todoist) > 5:
                    lines.append(f"    ... and {len(self.tasks_created_in_todoist) - 5} more")
            lines.append("")
        
        # Completion Status Changes
        if self.tasks_completed or self.tasks_reopened:
            lines.append("✅ COMPLETION STATUS")
            lines.append("-" * 70)
            if self.tasks_completed:
                lines.append(f"  Completed: {len(self.tasks_completed)}")
                for task in self.tasks_completed[:5]:
                    lines.append(f"    ✓ {task}")
                if len(self.tasks_completed) > 5:
                    lines.append(f"    ... and {len(self.tasks_completed) - 5} more")
            
            if self.tasks_reopened:
                lines.append(f"  Reopened: {len(self.tasks_reopened)}")
                for task in self.tasks_reopened[:5]:
                    lines.append(f"    ↻ {task}")
                if len(self.tasks_reopened) > 5:
                    lines.append(f"    ... and {len(self.tasks_reopened) - 5} more")
            lines.append("")
        
        # Detailed Changes
        if detailed and self.has_changes():
            # Todoist → Notion changes
            if self.todoist_to_notion:
                lines.append("📤 TODOIST → NOTION CHANGES")
                lines.append("-" * 70)
                
                # Group by field type
                by_field = self._group_by_field(self.todoist_to_notion)
                for field, changes in by_field.items():
                    lines.append(f"  {field.upper()} ({len(changes)} changes):")
                    for change in changes[:5]:
                        old = self._format_value(change.old_value)
                        new = self._format_value(change.new_value)
                        lines.append(f"    • {change.task_title}")
                        lines.append(f"      '{old}' → '{new}'")
                    if len(changes) > 5:
                        lines.append(f"    ... and {len(changes) - 5} more")
                lines.append("")
            
            # Notion → Todoist changes
            if self.notion_to_todoist:
                lines.append("📥 NOTION → TODOIST CHANGES")
                lines.append("-" * 70)
                
                by_field = self._group_by_field(self.notion_to_todoist)
                for field, changes in by_field.items():
                    lines.append(f"  {field.upper()} ({len(changes)} changes):")
                    for change in changes[:5]:
                        old = self._format_value(change.old_value)
                        new = self._format_value(change.new_value)
                        lines.append(f"    • {change.task_title}")
                        lines.append(f"      '{old}' → '{new}'")
                    if len(changes) > 5:
                        lines.append(f"    ... and {len(changes) - 5} more")
                lines.append("")
            
            # Conflicts
            if self.conflicts_resolved:
                lines.append("⚠️  CONFLICTS RESOLVED")
                lines.append("-" * 70)
                for conflict in self.conflicts_resolved:
                    lines.append(f"  • {conflict.task_title} - {conflict.field}")
                    lines.append(f"    Resolution: Used {conflict.source} value")
                lines.append("")
        
        # Errors
        if self.errors:
            lines.append("❌ ERRORS")
            lines.append("-" * 70)
            for error in self.errors:
                lines.append(f"  • {error}")
            lines.append("")
        
        # Summary
        if not self.has_changes() and not self.errors:
            lines.append("✅ NO CHANGES")
            lines.append("-" * 70)
            lines.append("  All tasks are already in sync!")
            lines.append("")
        
        lines.append("=" * 70)
        
        return "\n".join(lines)
    
    def _group_by_field(self, changes: List[ChangeDetail]) -> Dict[str, List[ChangeDetail]]:
        """Group changes by field name."""
        grouped = {}
        for change in changes:
            if change.field not in grouped:
                grouped[change.field] = []
            grouped[change.field].append(change)
        return grouped
    
    def _format_value(self, value: Any) -> str:
        """Format a value for display."""
        if value is None:
            return "(empty)"
        elif isinstance(value, list):
            if not value:
                return "(empty)"
            return f"[{', '.join(str(v) for v in value[:3])}{'...' if len(value) > 3 else ''}]"
        elif isinstance(value, str):
            if len(value) > 50:
                return value[:47] + "..."
            return value
        else:
            return str(value)
    
    def save_to_file(self, filename: str = "sync_report.txt") -> None:
        """Save report to file."""
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(self.generate_report(detailed=True))
            logger.info(f"Sync report saved to {filename}")
        except Exception as e:
            logger.error(f"Failed to save sync report: {e}")
