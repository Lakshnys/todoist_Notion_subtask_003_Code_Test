"""
Data models for Todoist and Notion tasks.
Provides type-safe representation of task state.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Literal, List
from enum import Enum


class TaskSource(str, Enum):
    """Source system for a task."""
    TODOIST = "Todoist"
    NOTION = "Notion"


class Priority(int, Enum):
    """Task priority levels (aligned with Todoist)."""
    NONE = 1
    LOW = 2
    MEDIUM = 3
    HIGH = 4


@dataclass
class Task:
    """
    Unified task representation for both Todoist and Notion.
    
    This model represents the reconciled view of a task,
    independent of which system it came from.
    """
    
    # Identity
    id: str  # System-specific ID (Todoist ID or Notion page ID)
    todoist_task_id: Optional[str] = None  # Stored in Notion for sync
    
    # Core fields
    title: str = ""
    description: str = ""  # Task description/notes
    completed: bool = False
    priority: int = Priority.NONE.value
    due_date: Optional[datetime] = None
    labels: List[str] = field(default_factory=list)  # Task labels/tags
    
    # Hierarchy
    parent_id: Optional[str] = None  # Parent's Todoist ID
    
    # Sync metadata
    source: TaskSource = TaskSource.TODOIST
    sync_enabled: bool = True
    last_modified_source: Optional[TaskSource] = None
    last_modified_time: Optional[datetime] = None
    
    # System timestamps (for field-level arbitration)
    title_modified_at: Optional[datetime] = None
    priority_modified_at: Optional[datetime] = None
    due_date_modified_at: Optional[datetime] = None
    completed_modified_at: Optional[datetime] = None
    description_modified_at: Optional[datetime] = None
    labels_modified_at: Optional[datetime] = None
    
    def __post_init__(self):
        """Validate task state after initialization."""
        if self.priority not in [p.value for p in Priority]:
            self.priority = Priority.NONE.value


@dataclass
class TodoistTask:
    """
    Raw Todoist task representation.
    Maps directly to Todoist API response.
    """
    
    id: str
    content: str
    description: str = ""
    completed: bool = False
    priority: int = 1  # Todoist uses 1-4, where 4 is highest
    due: Optional[dict] = None
    labels: List[str] = field(default_factory=list)
    parent_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None  # ← NEW: for timestamp-based conflict resolution

    @property
    def due_datetime(self) -> Optional[datetime]:
        """Parse due date from Todoist format."""
        if not self.due or not self.due.get('datetime'):
            return None
        try:
            return datetime.fromisoformat(self.due['datetime'].replace('Z', '+00:00'))
        except (ValueError, KeyError):
            return None
    
    def to_task(self) -> Task:
        """Convert Todoist task to unified Task model."""
        return Task(
            id=self.id,
            todoist_task_id=self.id,
            title=self.content,
            description=self.description,
            completed=self.completed,
            priority=self.priority,
            due_date=self.due_datetime,
            labels=self.labels,
            parent_id=self.parent_id,
            source=TaskSource.TODOIST,
            last_modified_source=TaskSource.TODOIST,
            last_modified_time=datetime.utcnow()
        )


@dataclass
class NotionTask:
    """
    Raw Notion task representation.
    Maps to Notion database page properties.
    """
    
    id: str  # Notion page ID
    title: str
    description: str = ""
    todoist_task_id: Optional[str] = None
    priority: int = Priority.NONE.value
    due_date: Optional[datetime] = None
    completed: bool = False
    labels: List[str] = field(default_factory=list)
    parent_id: Optional[str] = None  # Parent's Todoist ID (from relation)
    sync_enabled: bool = True
    source: TaskSource = TaskSource.TODOIST
    last_modified_source: Optional[TaskSource] = None
    last_modified_time: Optional[datetime] = None
    
    def to_task(self) -> Task:
        """Convert Notion task to unified Task model."""
        return Task(
            id=self.id,
            todoist_task_id=self.todoist_task_id,
            title=self.title,
            description=self.description,
            completed=self.completed,
            priority=self.priority,
            due_date=self.due_date,
            labels=self.labels,
            parent_id=self.parent_id,
            source=self.source,
            sync_enabled=self.sync_enabled,
            last_modified_source=self.last_modified_source,
            last_modified_time=self.last_modified_time
        )


@dataclass
class SyncDecision:
    """
    Represents a decision made by the sync engine.
    Used for logging and debugging.
    """
    
    action: Literal[
        "create_in_notion",
        "create_in_todoist", 
        "update_notion",
        "update_todoist",
        "skip",
        "no_op"
    ]
    task_id: str
    task_title: str
    reason: str
    details: dict = field(default_factory=dict)
    
    def __str__(self) -> str:
        return f"[{self.action}] {self.task_title} ({self.task_id}): {self.reason}"


@dataclass
class FieldUpdate:
    """
    Represents a single field update decision.
    Used for field-level conflict resolution.
    """
    
    field_name: str
    old_value: any
    new_value: any
    source: TaskSource
    timestamp: datetime
    
    def __str__(self) -> str:
        return f"{self.field_name}: {self.old_value} -> {self.new_value} (from {self.source.value})"


@dataclass
class SyncStats:
    """
    Statistics for a sync run.
    """
    
    todoist_tasks_fetched: int = 0
    notion_tasks_fetched: int = 0
    tasks_created_in_notion: int = 0
    tasks_created_in_todoist: int = 0
    tasks_updated_in_notion: int = 0
    tasks_updated_in_todoist: int = 0
    tasks_skipped: int = 0
    errors: int = 0
    
    def __str__(self) -> str:
        return (
            f"Sync Stats:\n"
            f"  Fetched: {self.todoist_tasks_fetched} Todoist, {self.notion_tasks_fetched} Notion\n"
            f"  Created: {self.tasks_created_in_notion} Notion, {self.tasks_created_in_todoist} Todoist\n"
            f"  Updated: {self.tasks_updated_in_notion} Notion, {self.tasks_updated_in_todoist} Todoist\n"
            f"  Skipped: {self.tasks_skipped}\n"
            f"  Errors: {self.errors}"
        )
