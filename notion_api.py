"""
notion_api.py
─────────────
Notion API client wrapper.
Handles all interactions with Notion API.

KEY IMPROVEMENTS in this version:
  1. create_task() returns page_id (str) instead of NotionTask
     → sync_engine needs the ID to store in state
  2. Parent Task relation set correctly for subtasks
  3. get_tasks_modified_after() for delta sync support
  4. _format_datetime_for_notion() applies workspace timezone
  5. Cached page lookup (avoids repeated API calls)
  6. Retry logic via retry_utils
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from notion_client import Client

from models import NotionTask, TaskSource, Priority
from config import settings
from retry_utils import retry_on_failure

logger = logging.getLogger(__name__)


class NotionClient:
    """
    Wrapper around Notion API for safe, typed interactions.
    """

    def __init__(self, api_token: str):
        """Initialize Notion client with timezone support."""
        self.client      = Client(auth=api_token)
        self.database_id = settings.notion_database_id

        # Workspace timezone for datetime formatting
        self.workspace_tz = timezone(
            timedelta(hours=settings.notion_timezone_offset)
        )

        # Page ID cache: todoist_task_id → notion_page_id
        # Avoids repeated API calls when looking up parents
        self._page_id_cache: Dict[str, str] = {}

        tz_sign  = "+" if settings.notion_timezone_offset >= 0 else ""
        logger.info(
            f"Notion client initialized | "
            f"DB: {self.database_id} | "
            f"TZ: UTC{tz_sign}{settings.notion_timezone_offset}"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # DATETIME FORMATTING
    # ─────────────────────────────────────────────────────────────────────────

    def _format_datetime_for_notion(
        self, dt: Optional[datetime]
    ) -> Optional[str]:
        """
        Format datetime for Notion API with explicit workspace timezone.

        Notion defaults to UTC if no timezone provided.
        We must send explicit timezone to ensure correct display.

        Args:
            dt: Datetime to format (naive or aware)

        Returns:
            ISO 8601 string with timezone e.g. "2026-02-22T14:30:00+04:00"
        """
        if dt is None:
            return None

        if dt.tzinfo is not None:
            # Convert aware datetime to workspace timezone
            dt = dt.astimezone(self.workspace_tz)
        else:
            # Naive datetime: add workspace timezone
            dt = dt.replace(tzinfo=self.workspace_tz)

        return dt.isoformat()

    # ─────────────────────────────────────────────────────────────────────────
    # FETCH TASKS
    # ─────────────────────────────────────────────────────────────────────────

    @retry_on_failure(max_retries=3, backoff_base=2.0)
    def get_all_tasks(self) -> List[NotionTask]:
        """
        Fetch ALL tasks from the Notion database (paginated).

        Returns:
            List of NotionTask objects
        """
        try:
            logger.info(f"Fetching all tasks from Notion...")

            results      = []
            has_more     = True
            start_cursor = None

            while has_more:
                response = self.client.databases.query(
                    database_id  = self.database_id,
                    start_cursor = start_cursor
                )
                results.extend(response.get('results', []))
                has_more     = response.get('has_more', False)
                start_cursor = response.get('next_cursor')

            notion_tasks = []
            for page in results:
                try:
                    task = self._page_to_model(page)
                    notion_tasks.append(task)
                    # Pre-populate cache with ALL todoist IDs → page IDs
                    # This prevents duplicate API calls during parent lookups
                    if task.todoist_task_id:
                        self._page_id_cache[task.todoist_task_id] = task.id
                except Exception as e:
                    logger.warning(
                        f"Failed to parse Notion page {page.get('id')}: {e}"
                    )

            # Pre-populate parent relations cache from raw page data
            # This avoids extra API calls when resolving parent IDs
            for page in results:
                page_id = page.get('id', '')
                props   = page.get('properties', {})
                if 'Parent Task' in props:
                    relations = props['Parent Task'].get('relation', [])
                    if relations:
                        parent_page_id = relations[0]['id']
                        # Cache: parent_page_id → we know it exists
                        # Will be resolved to Todoist ID on demand
                        self._page_id_cache.setdefault(
                            f'_page_{parent_page_id}', parent_page_id
                        )

            logger.info(
                f"Fetched {len(notion_tasks)} Notion tasks | "
                f"Cache: {len(self._page_id_cache)} entries"
            )
            return notion_tasks

        except Exception as e:
            logger.error(f"Failed to fetch Notion tasks: {e}")
            raise

    @retry_on_failure(max_retries=3, backoff_base=2.0)
    def get_tasks_modified_after(
        self, since: datetime
    ) -> List[NotionTask]:
        """
        Fetch tasks modified after a specific datetime.
        Used for delta sync (only fetch what changed).

        Args:
            since: Only return tasks edited after this time

        Returns:
            List of recently modified NotionTask objects
        """
        try:
            # Format timestamp for Notion filter
            since_str = since.isoformat() if since.tzinfo else (
                since.replace(tzinfo=timezone.utc).isoformat()
            )

            logger.info(f"Fetching Notion tasks modified after {since_str}")

            results      = []
            has_more     = True
            start_cursor = None

            while has_more:
                response = self.client.databases.query(
                    database_id  = self.database_id,
                    start_cursor = start_cursor,
                    filter       = {
                        "timestamp": "last_edited_time",
                        "last_edited_time": {
                            "after": since_str
                        }
                    }
                )
                results.extend(response.get('results', []))
                has_more     = response.get('has_more', False)
                start_cursor = response.get('next_cursor')

            notion_tasks = []
            for page in results:
                try:
                    task = self._page_to_model(page)
                    notion_tasks.append(task)
                except Exception as e:
                    logger.warning(
                        f"Failed to parse page {page.get('id')}: {e}"
                    )

            logger.info(
                f"Found {len(notion_tasks)} tasks modified after {since_str}"
            )
            return notion_tasks

        except Exception as e:
            logger.error(f"Failed to fetch modified Notion tasks: {e}")
            raise

    # ─────────────────────────────────────────────────────────────────────────
    # CREATE TASK
    # ─────────────────────────────────────────────────────────────────────────

    @retry_on_failure(max_retries=3, backoff_base=2.0)
    def create_task(
        self,
        title: str,
        todoist_task_id: str,
        description: str = "",
        priority: int = Priority.NONE.value,
        due_date: Optional[datetime] = None,
        completed: bool = False,
        labels: Optional[List[str]] = None,
        parent_todoist_id: Optional[str] = None,
        source: TaskSource = TaskSource.TODOIST
    ) -> str:
        """
        Create a new task in Notion.

        Args:
            title:             Task title
            todoist_task_id:   Todoist task ID to store
            description:       Task description
            priority:          Priority level (1-4)
            due_date:          Optional due date/time
            completed:         Completion status
            labels:            List of label names
            parent_todoist_id: Parent's Todoist ID (for subtasks)
            source:            Source system (TODOIST or NOTION)

        Returns:
            Notion page ID of created task (str)
        """
        try:
            is_subtask = bool(parent_todoist_id)
            logger.info(
                f"Creating Notion task: '{title}' "
                f"[Todoist: {todoist_task_id}]"
                f"{' (subtask)' if is_subtask else ''}"
            )

            # ── Build properties ──────────────────────────────────────────────
            properties: Dict[str, Any] = {
                "Title": {
                    "title": [{"text": {"content": title}}]
                },
                "Todoist Task ID": {
                    "rich_text": [{"text": {"content": todoist_task_id}}]
                },
                "Priority": {
                    "number": priority
                },
                "Completed": {
                    "checkbox": completed
                },
                "Sync Enabled": {
                    "checkbox": True
                },
                "Source": {
                    "select": {"name": source.value}
                },
                "Last Modified Source": {
                    "select": {"name": source.value}
                },
                "Last Modified Time": {
                    "date": {"start": datetime.utcnow().isoformat()}
                }
            }

            # Due date with workspace timezone
            if due_date:
                formatted = self._format_datetime_for_notion(due_date)
                if formatted:
                    properties["Due Date"] = {
                        "date": {"start": formatted}
                    }

            # Description
            if description:
                properties["Description"] = {
                    "rich_text": [{"text": {"content": description}}]
                }

            # Labels
            if labels:
                properties["Labels"] = {
                    "multi_select": [{"name": lbl} for lbl in labels]
                }

            # ── Parent Task relation (subtask support) ────────────────────────
            if parent_todoist_id:
                parent_page_id = self._find_page_by_todoist_id(
                    parent_todoist_id
                )
                if parent_page_id:
                    properties["Parent Task"] = {
                        "relation": [{"id": parent_page_id}]
                    }
                    logger.info(
                        f"  Linking to parent page: {parent_page_id}"
                    )
                else:
                    logger.warning(
                        f"  Parent Todoist ID {parent_todoist_id} "
                        f"not found in Notion - skipping relation"
                    )

            # ── Create page ───────────────────────────────────────────────────
            page = self.client.pages.create(
                parent     = {"database_id": self.database_id},
                properties = properties
            )

            page_id = page["id"]

            # Update cache
            self._page_id_cache[todoist_task_id] = page_id

            logger.info(
                f"✅ Created Notion task: '{title}' → Page: {page_id}"
            )
            return page_id

        except Exception as e:
            logger.error(f"Failed to create Notion task '{title}': {e}")
            raise

    # ─────────────────────────────────────────────────────────────────────────
    # UPDATE TASK
    # ─────────────────────────────────────────────────────────────────────────

    @retry_on_failure(max_retries=3, backoff_base=2.0)
    def update_task(
        self,
        page_id: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        priority: Optional[int] = None,
        due_date: Optional[datetime] = None,
        completed: Optional[bool] = None,
        todoist_task_id: Optional[str] = None,
        labels: Optional[List[str]] = None,
        parent_todoist_id: Optional[str] = None,
        last_modified_source: Optional[TaskSource] = None,
        last_modified_time: Optional[datetime] = None
    ) -> None:
        """
        Update an existing Notion task.

        Args:
            page_id:              Notion page ID to update
            title:                New title (if changed)
            description:          New description (if changed)
            priority:             New priority (if changed)
            due_date:             New due date (if changed)
            completed:            New completion status (if changed)
            todoist_task_id:      Todoist ID (when first linking)
            labels:               New labels (if changed)
            parent_todoist_id:    Parent's Todoist ID (for subtask linking)
            last_modified_source: Which system made this change
            last_modified_time:   When the change was made
        """
        try:
            logger.debug(f"Updating Notion task {page_id}")

            properties: Dict[str, Any] = {}

            if title is not None:
                properties["Title"] = {
                    "title": [{"text": {"content": title}}]
                }

            if description is not None:
                properties["Description"] = {
                    "rich_text": [{"text": {"content": description}}]
                }

            if priority is not None:
                properties["Priority"] = {
                    "number": priority
                }

            if due_date is not None:
                formatted = self._format_datetime_for_notion(due_date)
                if formatted:
                    properties["Due Date"] = {
                        "date": {"start": formatted}
                    }

            if completed is not None:
                properties["Completed"] = {
                    "checkbox": completed
                }

            if todoist_task_id is not None:
                properties["Todoist Task ID"] = {
                    "rich_text": [{"text": {"content": todoist_task_id}}]
                }
                # Update cache
                self._page_id_cache[todoist_task_id] = page_id

            if labels is not None:
                properties["Labels"] = {
                    "multi_select": [{"name": lbl} for lbl in labels]
                }

            # Parent Task relation
            if parent_todoist_id is not None:
                parent_page_id = self._find_page_by_todoist_id(
                    parent_todoist_id
                )
                if parent_page_id:
                    properties["Parent Task"] = {
                        "relation": [{"id": parent_page_id}]
                    }
                    logger.info(
                        f"  Updated parent relation → {parent_page_id}"
                    )

            # Always update metadata when making changes
            if properties:
                if last_modified_source:
                    properties["Last Modified Source"] = {
                        "select": {"name": last_modified_source.value}
                    }
                properties["Last Modified Time"] = {
                    "date": {
                        "start": (
                            last_modified_time or datetime.utcnow()
                        ).isoformat()
                    }
                }

            if not properties:
                logger.debug(
                    f"No changes for Notion task {page_id}, skipping"
                )
                return

            # Apply update
            self.client.pages.update(
                page_id    = page_id,
                properties = properties
            )

            logger.info(f"✅ Updated Notion task {page_id}")

        except Exception as e:
            logger.error(f"Failed to update Notion task {page_id}: {e}")
            raise

    # ─────────────────────────────────────────────────────────────────────────
    # GET SINGLE TASK
    # ─────────────────────────────────────────────────────────────────────────

    @retry_on_failure(max_retries=3, backoff_base=2.0)
    def get_task(self, page_id: str) -> NotionTask:
        """Fetch a single Notion task by page ID."""
        try:
            page = self.client.pages.retrieve(page_id=page_id)
            return self._page_to_model(page)
        except Exception as e:
            logger.error(f"Failed to fetch Notion task {page_id}: {e}")
            raise

    # ─────────────────────────────────────────────────────────────────────────
    # FIND PAGE BY TODOIST ID
    # ─────────────────────────────────────────────────────────────────────────

    def _find_page_by_todoist_id(
        self, todoist_task_id: str
    ) -> Optional[str]:
        """
        Find a Notion page ID by its Todoist Task ID.
        Uses cache first to avoid unnecessary API calls.

        Args:
            todoist_task_id: Todoist task ID to search for

        Returns:
            Notion page ID if found, None otherwise
        """
        # Check cache first
        if todoist_task_id in self._page_id_cache:
            return self._page_id_cache[todoist_task_id]

        try:
            response = self.client.databases.query(
                database_id = self.database_id,
                filter      = {
                    "property": "Todoist Task ID",
                    "rich_text": {
                        "equals": todoist_task_id
                    }
                }
            )

            results = response.get('results', [])
            if results:
                page_id = results[0]['id']
                # Store in cache
                self._page_id_cache[todoist_task_id] = page_id
                return page_id

            return None

        except Exception as e:
            logger.warning(
                f"Failed to find page by Todoist ID {todoist_task_id}: {e}"
            )
            return None

    # ─────────────────────────────────────────────────────────────────────────
    # PAGE TO MODEL
    # ─────────────────────────────────────────────────────────────────────────

    def _page_to_model(self, page: Dict[str, Any]) -> NotionTask:
        """
        Convert a Notion API page dict to our NotionTask model.

        Handles all database columns including:
        - Parent Task (relation)
        - Related back to Todoist Tasks (relation)
        - All standard fields
        """
        props = page.get('properties', {})

        # ── Title ─────────────────────────────────────────────────────────────
        title = ""
        if 'Title' in props and props['Title'].get('title'):
            title_list = props['Title']['title']
            if title_list:
                title = title_list[0]['text']['content']

        # ── Todoist Task ID ───────────────────────────────────────────────────
        todoist_task_id = None
        if 'Todoist Task ID' in props:
            rt = props['Todoist Task ID'].get('rich_text', [])
            if rt:
                todoist_task_id = rt[0]['text']['content']

        # ── Description ───────────────────────────────────────────────────────
        description = ""
        if 'Description' in props:
            rt = props['Description'].get('rich_text', [])
            if rt:
                description = rt[0]['text']['content']

        # ── Priority ─────────────────────────────────────────────────────────
        priority = Priority.NONE.value
        if 'Priority' in props:
            num = props['Priority'].get('number')
            if num is not None:
                priority = int(num)

        # ── Due Date ─────────────────────────────────────────────────────────
        due_date = None
        if 'Due Date' in props and props['Due Date'].get('date'):
            date_str = props['Due Date']['date']['start']
            try:
                due_date = datetime.fromisoformat(
                    date_str.replace('Z', '+00:00')
                )
            except ValueError:
                logger.warning(f"Could not parse due date: {date_str}")

        # ── Completed ─────────────────────────────────────────────────────────
        completed = False
        if 'Completed' in props:
            cb = props['Completed'].get('checkbox')
            if cb is not None:
                completed = bool(cb)

        # ── Labels ───────────────────────────────────────────────────────────
        labels = []
        if 'Labels' in props:
            ms = props['Labels'].get('multi_select', [])
            labels = [item['name'] for item in ms]

        # ── Parent Task (relation) ────────────────────────────────────────────
        parent_id = None
        if 'Parent Task' in props:
            relations = props['Parent Task'].get('relation', [])
            if relations:
                parent_page_id = relations[0]['id']

                # Check if we already know this page's Todoist ID
                # Search cache for todoist_id → page_id mapping (reverse lookup)
                cached_todoist_id = next(
                    (tid for tid, pid in self._page_id_cache.items()
                     if pid == parent_page_id and not tid.startswith('_page_')),
                    None
                )

                if cached_todoist_id:
                    parent_id = cached_todoist_id
                    logger.debug(
                        f"Parent resolved from cache: {parent_page_id} "
                        f"→ {parent_id}"
                    )
                else:
                    # Not in cache - fetch from API
                    try:
                        parent_page  = self.client.pages.retrieve(
                            page_id=parent_page_id
                        )
                        parent_props = parent_page.get('properties', {})
                        if 'Todoist Task ID' in parent_props:
                            parent_rt = parent_props['Todoist Task ID'].get(
                                'rich_text', []
                            )
                            if parent_rt:
                                parent_id = parent_rt[0]['text']['content']
                                # Cache for future lookups
                                if parent_id:
                                    self._page_id_cache[parent_id] = \
                                        parent_page_id
                                    logger.debug(
                                        f"Parent fetched + cached: "
                                        f"{parent_page_id} → {parent_id}"
                                    )
                    except Exception as e:
                        logger.warning(
                            f"Failed to resolve parent page "
                            f"{parent_page_id}: {e}"
                        )

        # ── Sync Enabled ──────────────────────────────────────────────────────
        sync_enabled = True
        if 'Sync Enabled' in props:
            cb = props['Sync Enabled'].get('checkbox')
            if cb is not None:
                sync_enabled = bool(cb)

        # ── Source ────────────────────────────────────────────────────────────
        source = TaskSource.TODOIST
        if 'Source' in props and props['Source'].get('select'):
            try:
                source = TaskSource(props['Source']['select']['name'])
            except ValueError:
                pass

        # ── Last Modified Source ──────────────────────────────────────────────
        last_modified_source = None
        if 'Last Modified Source' in props:
            sel = props['Last Modified Source'].get('select')
            if sel:
                try:
                    last_modified_source = TaskSource(sel['name'])
                except ValueError:
                    pass

        # ── Last Modified Time ────────────────────────────────────────────────
        last_modified_time = None
        if 'Last Modified Time' in props:
            dt_prop = props['Last Modified Time'].get('date')
            if dt_prop and dt_prop.get('start'):
                try:
                    last_modified_time = datetime.fromisoformat(
                        dt_prop['start'].replace('Z', '+00:00')
                    )
                except ValueError:
                    pass

        return NotionTask(
            id                   = page['id'],
            title                = title,
            description          = description,
            todoist_task_id      = todoist_task_id,
            priority             = priority,
            due_date             = due_date,
            completed            = completed,
            labels               = labels,
            parent_id            = parent_id,
            sync_enabled         = sync_enabled,
            source               = source,
            last_modified_source = last_modified_source,
            last_modified_time   = last_modified_time
        )
