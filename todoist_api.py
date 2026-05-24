"""
todoist_api.py
──────────────
Todoist API client wrapper.
Handles all interactions with Todoist REST API using direct HTTP requests.
Uses v1 API with pagination (confirmed working).

KEY IMPROVEMENTS in this version:
  1. Fixed create_task() bug: task_data['due_datetime'] (not update_kwargs)
  2. _dict_to_model() now captures updated_at for conflict resolution
  3. get_tasks_modified_after() for delta sync support
  4. Retry logic via retry_utils
  5. All datetime handling clean and consistent

IMPORTANT: Todoist API uses INVERTED priority scale:
  API 1 = Priority 4 (Urgent)   ← Most urgent
  API 4 = Priority 1 (Normal)   ← Least urgent
"""

import logging
import requests
from typing import List, Optional, Dict, Any
from datetime import datetime

from models import TodoistTask, Priority
from config import settings
from retry_utils import retry_on_failure

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# PRIORITY CONVERSION
# ─────────────────────────────────────────────────────────────────────────────

def todoist_api_to_internal_priority(api_priority: int) -> int:
    """
    Convert Todoist API priority to internal priority.
    Todoist API: 1=urgent, 4=normal (inverted!)
    Internal:    1=normal, 4=urgent (standard)
    """
    return 5 - api_priority


def internal_to_todoist_api_priority(internal_priority: int) -> int:
    """
    Convert internal priority to Todoist API priority.
    Internal:    1=normal, 4=urgent (standard)
    Todoist API: 1=urgent, 4=normal (inverted!)
    """
    return 5 - internal_priority


# ─────────────────────────────────────────────────────────────────────────────
# CLIENT
# ─────────────────────────────────────────────────────────────────────────────

class TodoistClient:
    """
    Wrapper around Todoist v1 API using direct HTTP requests.

    KEY BEHAVIOURS:
    - All tasks fetched with pagination (handles large projects)
    - Priority scale auto-converted (API inverted vs internal standard)
    - Subtasks supported via parent_id
    - updated_at captured for conflict resolution (latest-wins)
    - Retry logic on transient failures
    """

    def __init__(self, api_token: str):
        """Initialize Todoist client."""
        self.api_token  = api_token
        self.project_id = settings.todoist_project_id
        self.base_url   = "https://api.todoist.com/api/v1"
        self.headers    = {
            "Authorization":  f"Bearer {self.api_token}",
            "Content-Type":   "application/json"
        }
        logger.info(
            f"Todoist client initialized for project {self.project_id}"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # FETCH TASKS
    # ─────────────────────────────────────────────────────────────────────────

    @retry_on_failure(max_retries=3, backoff_base=2.0)
    def get_all_tasks(self) -> List[TodoistTask]:
        """
        Fetch ALL tasks (active + completed) from the configured project.
        Uses cursor-based pagination.

        WHY BOTH:
          - /tasks endpoint only returns ACTIVE tasks by default
          - Completed tasks exist but won't appear in list
          - Individual task lookup works for completed tasks
          - We need completed tasks to:
            a) Correctly sync completion status to Notion
            b) Avoid false "invalid ID" errors in check_notion_sync.py

        Returns:
            List of TodoistTask objects (active + completed)
        """
        try:
            logger.info("Fetching all tasks from Todoist (active + completed)...")

            # Fetch active tasks
            active_tasks = self._fetch_tasks_paginated(is_completed=False)
            logger.info(f"Active tasks in project: {len(active_tasks)}")

            # Fetch completed tasks
            completed_tasks = self._fetch_tasks_paginated(is_completed=True)
            logger.info(f"Completed tasks in project: {len(completed_tasks)}")

            all_tasks = active_tasks + completed_tasks

            # Log breakdown
            parents  = [t for t in all_tasks if not t.parent_id]
            subtasks = [t for t in all_tasks if t.parent_id]
            logger.info(
                f"Total: {len(all_tasks)} tasks "
                f"({len(parents)} parents, {len(subtasks)} subtasks | "
                f"{len(active_tasks)} active, {len(completed_tasks)} completed)"
            )

            return all_tasks

        except Exception as e:
            logger.error(f"Failed to fetch Todoist tasks: {e}")
            raise

    def _fetch_tasks_paginated(
        self, is_completed: bool = False
    ) -> List[TodoistTask]:
        """
        Internal: Fetch tasks with pagination.

        Active tasks:    GET /api/v1/tasks
                         → response has 'results' key

        Completed tasks: GET /api/v1/tasks/completed
                         → response has 'items' key (different structure!)
                         → requires project_id filter param

        Args:
            is_completed: True = use /tasks/completed endpoint

        Returns:
            List of TodoistTask objects for configured project
        """
        all_tasks_raw = []
        cursor        = None

        if is_completed:
            # ── Completed tasks: different endpoint + response structure ───────
            url = f"{self.base_url}/tasks/completed"

            while True:
                params = {
                    "project_id": self.project_id,
                    "limit":      100
                }
                if cursor:
                    params["cursor"] = cursor

                response = requests.get(
                    url, headers=self.headers, params=params
                )
                response.raise_for_status()

                data  = response.json()
                items = data.get("items", [])

                # IMPORTANT: Completed endpoint uses different structure:
                #   'id'      = completion EVENT id (not task id!)
                #   'task_id' = actual Todoist task ID
                # We normalize to match active task structure
                for item in items:
                    normalized = {
                        "id":           item.get("task_id"),   # ← Real task ID
                        "content":      item.get("content", ""),
                        "description":  item.get("description", ""),
                        "priority":     item.get("priority", 4),
                        "project_id":   item.get("project_id", ""),
                        "parent_id":    item.get("parent_id"),
                        "labels":       item.get("labels", []),
                        "due":          item.get("due"),
                        "is_completed": True,                  # ← Mark completed
                        "created_at":   item.get("created_at"),
                        "updated_at":   item.get("completed_at"),  # ← Use completed_at
                    }
                    all_tasks_raw.append(normalized)

                cursor = data.get("next_cursor")
                if not cursor:
                    break

        else:
            # ── Active tasks: standard endpoint ──────────────────────────────
            url = f"{self.base_url}/tasks"

            while True:
                params = {"limit": 100}
                if cursor:
                    params["cursor"] = cursor

                response = requests.get(
                    url, headers=self.headers, params=params
                )
                response.raise_for_status()

                data = response.json()
                all_tasks_raw.extend(data.get("results", []))

                cursor = data.get("next_cursor")
                if not cursor:
                    break

            # Filter to configured project for active tasks
            all_tasks_raw = [
                t for t in all_tasks_raw
                if t.get("project_id") == self.project_id
            ]

        # Convert to model
        tasks = []
        for task_data in all_tasks_raw:
            try:
                tasks.append(self._dict_to_model(task_data))
            except Exception as e:
                logger.warning(
                    f"Failed to parse task "
                    f"{task_data.get('id', 'unknown')}: {e}"
                )

        return tasks

    @retry_on_failure(max_retries=3, backoff_base=2.0)
    def get_tasks_modified_after(
        self, since: datetime
    ) -> List[TodoistTask]:
        """
        Fetch tasks updated after a specific datetime.
        Used for delta sync (only fetch what changed).

        Note: Todoist v1 API supports updated_after filter.

        Args:
            since: Only return tasks updated after this datetime

        Returns:
            List of recently modified TodoistTask objects (active + completed)
        """
        try:
            since_str = since.strftime("%Y-%m-%dT%H:%M:%S.000000Z")
            logger.info(f"Fetching Todoist tasks modified after {since_str}")

            # ── Active tasks ──────────────────────────────────────────────────
            # NOTE: Todoist API updated_after filter is unreliable.
            # We fetch all active tasks and filter client-side by updated_at.
            active_tasks = []
            url          = f"{self.base_url}/tasks"
            cursor       = None

            while True:
                params = {"limit": 100}
                if cursor:
                    params["cursor"] = cursor

                response = requests.get(
                    url, headers=self.headers, params=params
                )
                response.raise_for_status()
                data = response.json()

                for t in data.get("results", []):
                    if t.get("project_id") == self.project_id:
                        try:
                            active_tasks.append(self._dict_to_model(t))
                        except Exception as e:
                            logger.warning(f"Failed to parse task: {e}")

                cursor = data.get("next_cursor")
                if not cursor:
                    break

            # ── Client-side filter by updated_at ─────────────────────────────
            # Only keep tasks whose updated_at is after our since timestamp
            changed_active = []
            for task in active_tasks:
                if not task.updated_at:
                    # No timestamp → include (conservative: assume changed)
                    changed_active.append(task)
                    continue
                try:
                    from dateutil import parser as dtparser
                    task_ts = dtparser.parse(str(task.updated_at))
                    # Normalize to naive UTC
                    if task_ts.tzinfo:
                        task_ts = task_ts.replace(tzinfo=None)
                    if task_ts > since:
                        changed_active.append(task)
                except Exception:
                    # Can't parse timestamp → include conservatively
                    changed_active.append(task)

            logger.info(
                f"Active tasks: {len(active_tasks)} total → "
                f"{len(changed_active)} changed since {since_str}"
            )

            # ── Recently completed tasks ──────────────────────────────────────
            completed_tasks = []
            r = requests.get(
                f"{self.base_url}/tasks/completed",
                headers = self.headers,
                params  = {
                    "project_id": self.project_id,
                    "limit":      100,
                    "since":      since_str
                }
            )
            r.raise_for_status()
            comp_data = r.json()

            for item in comp_data.get("items", []):
                completed_at = item.get("completed_at", "")
                if completed_at >= since_str:
                    normalized = {
                        "id":           item.get("task_id"),
                        "content":      item.get("content", ""),
                        "description":  item.get("description", ""),
                        "priority":     item.get("priority", 4),
                        "project_id":   item.get("project_id", ""),
                        "parent_id":    item.get("parent_id"),
                        "labels":       item.get("labels", []),
                        "due":          item.get("due"),
                        "is_completed": True,
                        "created_at":   item.get("created_at"),
                        "updated_at":   item.get("completed_at"),
                    }
                    try:
                        completed_tasks.append(self._dict_to_model(normalized))
                    except Exception as e:
                        logger.warning(f"Failed to parse completed task: {e}")

            all_changed = changed_active + completed_tasks
            logger.info(
                f"Delta result: {len(changed_active)} active + "
                f"{len(completed_tasks)} completed = "
                f"{len(all_changed)} changed tasks"
            )
            return all_changed

        except Exception as e:
            logger.error(f"Failed to fetch modified Todoist tasks: {e}")
            raise

    # ─────────────────────────────────────────────────────────────────────────
    # CREATE TASK
    # ─────────────────────────────────────────────────────────────────────────

    @retry_on_failure(max_retries=3, backoff_base=2.0)
    def create_task(
        self,
        content: str,
        description: str = "",
        priority: int = Priority.NONE.value,
        due_date: Optional[datetime] = None,
        labels: Optional[List[str]] = None,
        parent_id: Optional[str] = None
    ) -> TodoistTask:
        """
        Create a new task in Todoist.

        Args:
            content:     Task title/content
            description: Task description/notes
            priority:    Priority level (1-4, internal standard scale)
            due_date:    Optional due date/time
            labels:      Optional list of label names
            parent_id:   Parent task ID (for subtasks)

        Returns:
            Created TodoistTask with new ID
        """
        try:
            is_subtask = bool(parent_id)
            logger.info(
                f"Creating Todoist task: '{content}'"
                f"{' (subtask)' if is_subtask else ''}"
                f"{f' parent: {parent_id}' if is_subtask else ''}"
            )

            # Convert priority to Todoist API scale
            api_priority = internal_to_todoist_api_priority(priority)

            # Build request payload
            task_data: Dict[str, Any] = {
                "content":    content,
                "project_id": self.project_id,
                "priority":   api_priority
            }

            if description:
                task_data["description"] = description

            # Due date/time handling
            if due_date is not None:
                # Remove timezone → Todoist uses naive local time
                if due_date.tzinfo is not None:
                    due_date_naive = due_date.replace(tzinfo=None)
                else:
                    due_date_naive = due_date

                # Use due_datetime for full datetime (preserves time for alarms)
                task_data['due_datetime'] = due_date_naive.isoformat()

            if labels:
                task_data["labels"] = labels

            # Subtask: set parent_id
            if parent_id:
                task_data["parent_id"] = parent_id

            # Create task via API
            response = requests.post(
                f"{self.base_url}/tasks",
                headers = self.headers,
                json    = task_data
            )
            response.raise_for_status()

            created_data = response.json()
            todoist_task = self._dict_to_model(created_data)

            logger.info(
                f"✅ Created Todoist task: '{content}' "
                f"→ ID: {todoist_task.id} "
                f"(priority {priority} → API {api_priority})"
            )
            return todoist_task

        except Exception as e:
            logger.error(f"Failed to create Todoist task '{content}': {e}")
            raise

    # ─────────────────────────────────────────────────────────────────────────
    # UPDATE TASK
    # ─────────────────────────────────────────────────────────────────────────

    @retry_on_failure(max_retries=3, backoff_base=2.0)
    def update_task(
        self,
        task_id: str,
        content: Optional[str] = None,
        description: Optional[str] = None,
        priority: Optional[int] = None,
        due_date: Optional[datetime] = None,
        labels: Optional[List[str]] = None
    ) -> TodoistTask:
        """
        Update an existing Todoist task.

        Args:
            task_id:     Todoist task ID to update
            content:     New content/title (if changed)
            description: New description (if changed)
            priority:    New priority (1-4 internal scale, if changed)
            due_date:    New due date/time (if changed)
            labels:      New labels (if changed)

        Returns:
            Updated TodoistTask
        """
        try:
            logger.debug(f"Updating Todoist task {task_id}")

            update_data: Dict[str, Any] = {}

            if content is not None:
                update_data['content'] = content

            if description is not None:
                update_data['description'] = description

            if priority is not None:
                api_priority = internal_to_todoist_api_priority(priority)
                update_data['priority'] = api_priority
                logger.debug(
                    f"Priority: internal {priority} → API {api_priority}"
                )

            if due_date is not None:
                # Remove timezone → Todoist uses naive local time
                if due_date.tzinfo is not None:
                    due_date_naive = due_date.replace(tzinfo=None)
                else:
                    due_date_naive = due_date

                # Use due_datetime for full datetime (preserves time!)
                update_data['due_datetime'] = due_date_naive.isoformat()

            if labels is not None:
                update_data['labels'] = labels

            # Skip if nothing to update
            if not update_data:
                logger.debug(
                    f"No changes for task {task_id}, skipping update"
                )
                return self.get_task(task_id)

            # Apply update
            response = requests.post(
                f"{self.base_url}/tasks/{task_id}",
                headers = self.headers,
                json    = update_data
            )
            response.raise_for_status()

            updated_task = self.get_task(task_id)
            logger.info(f"✅ Updated Todoist task {task_id}")
            return updated_task

        except Exception as e:
            logger.error(
                f"Failed to update Todoist task {task_id}: {e}"
            )
            raise

    # ─────────────────────────────────────────────────────────────────────────
    # COMPLETE / REOPEN
    # ─────────────────────────────────────────────────────────────────────────

    @retry_on_failure(max_retries=3, backoff_base=2.0)
    def complete_task(self, task_id: str) -> bool:
        """Mark a Todoist task as complete."""
        try:
            logger.info(f"Completing Todoist task {task_id}")
            response = requests.post(
                f"{self.base_url}/tasks/{task_id}/close",
                headers=self.headers
            )
            response.raise_for_status()
            logger.info(f"✅ Completed Todoist task {task_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to complete Todoist task {task_id}: {e}")
            return False

    @retry_on_failure(max_retries=3, backoff_base=2.0)
    def reopen_task(self, task_id: str) -> bool:
        """Reopen a completed Todoist task."""
        try:
            logger.info(f"Reopening Todoist task {task_id}")
            response = requests.post(
                f"{self.base_url}/tasks/{task_id}/reopen",
                headers=self.headers
            )
            response.raise_for_status()
            logger.info(f"✅ Reopened Todoist task {task_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to reopen Todoist task {task_id}: {e}")
            return False

    # ─────────────────────────────────────────────────────────────────────────
    # GET SINGLE TASK
    # ─────────────────────────────────────────────────────────────────────────

    @retry_on_failure(max_retries=3, backoff_base=2.0)
    def get_task(self, task_id: str) -> TodoistTask:
        """Fetch a single task by ID."""
        try:
            response = requests.get(
                f"{self.base_url}/tasks/{task_id}",
                headers=self.headers
            )
            response.raise_for_status()
            return self._dict_to_model(response.json())
        except Exception as e:
            logger.error(f"Failed to fetch Todoist task {task_id}: {e}")
            raise

    # ─────────────────────────────────────────────────────────────────────────
    # DICT TO MODEL
    # ─────────────────────────────────────────────────────────────────────────

    def _dict_to_model(self, task_dict: Dict[str, Any]) -> TodoistTask:
        """
        Convert Todoist API task dict to our TodoistTask model.

        Key fields captured:
        - id, content, description, priority (converted)
        - due (datetime + string + timezone)
        - labels, parent_id
        - created_at, updated_at  ← for timestamp-based conflict resolution
        """
        # Due date extraction
        due_dict = None
        if task_dict.get('due'):
            due_info = task_dict['due']
            due_dict = {
                'datetime': due_info.get('datetime') or due_info.get('date'),
                'string':   due_info.get('string'),
                'timezone': due_info.get('timezone')
            }

        # Priority conversion (API inverted → internal standard)
        api_priority      = task_dict.get('priority', 4)
        internal_priority = todoist_api_to_internal_priority(api_priority)

        logger.debug(
            f"Task {task_dict['id']}: "
            f"API priority {api_priority} → Internal {internal_priority}"
        )

        return TodoistTask(
            id          = task_dict['id'],
            content     = task_dict.get('content', ''),
            description = task_dict.get('description', ''),
            completed   = task_dict.get('is_completed', False),
            priority    = internal_priority,
            due         = due_dict,
            labels      = task_dict.get('labels', []),
            parent_id   = task_dict.get('parent_id'),
            created_at  = task_dict.get('created_at'),
            updated_at  = task_dict.get('updated_at'),   # ← NEW: for conflict resolution
        )
