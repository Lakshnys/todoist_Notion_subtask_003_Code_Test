"""
sync_engine.py
──────────────
Core synchronization engine for Todoist ↔ Notion bidirectional sync.

SYNC LOGIC (confirmed architecture):
  Local DB = source of truth
  → Compare timestamps → latest wins
  → Update local → push to both systems
  → Store sync timestamp

DELTA SYNC (Phase 3):
  First run (is_initial_sync_done = False):
    → Full fetch: get ALL tasks from both systems
    → Mark initial sync done after completion

  Subsequent runs (is_initial_sync_done = True):
    → Delta fetch: get ONLY tasks modified since last_sync_time
    → Todoist: GET /tasks?updated_after=last_sync_time
    → Notion:  filter by last_edited_time > last_sync_time
    → Process only changed tasks = 10x faster

SYNC FLOW:
  Step 1: Determine sync mode (full vs delta)
  Step 2: Fetch tasks (full or delta)
  Step 3: Handle Notion tasks with NO Todoist ID
  Step 4: Handle completed tasks
  Step 5: Sync Todoist → Notion (parents first)
  Step 6: Apply field-level updates (latest wins)
  Step 7: Update global last_sync_time
  Step 8: Generate summary report
"""

import logging
import sys
from typing import List, Dict, Optional, Tuple, Set
from datetime import datetime

from models import (
    Task, TodoistTask, NotionTask, TaskSource, Priority,
    SyncDecision, FieldUpdate, SyncStats
)
from todoist_api import TodoistClient
from notion_api import NotionClient
from sync_state_manager import SyncStateManager
from sync_summary import SyncSummary, ChangeDetail
from conflict_logger import ConflictLogger
from config import settings

logger = logging.getLogger(__name__)


class SyncEngine:
    """
    Bidirectional sync engine for Todoist ↔ Notion.

    KEY BEHAVIOURS:
    - Delta sync: only fetch/process tasks changed since last sync
    - Full sync: on first run or when forced
    - Notion tasks with no Todoist ID → create in Todoist → update Notion
    - Parents synced before subtasks (topological order)
    - Three-way merge: Todoist vs Notion vs Local state
    - Conflicts resolved by latest timestamp
    - Conflict logging to file for visibility
    """

    def __init__(
        self,
        todoist_client: TodoistClient,
        notion_client: NotionClient,
        force_full_sync: bool = False
    ):
        self.todoist         = todoist_client
        self.notion          = notion_client
        self.state_manager   = SyncStateManager()
        self.summary         = SyncSummary()
        self.stats           = SyncStats()
        self.conflict_logger = ConflictLogger()
        self.decisions: List[SyncDecision] = []
        self.force_full_sync = force_full_sync

    # ─────────────────────────────────────────────────────────────────────────
    # MAIN SYNC CYCLE
    # ─────────────────────────────────────────────────────────────────────────

    def run_sync(self) -> SyncStats:
        """
        Execute a sync cycle (full or delta based on state).

        Returns:
            SyncStats with operation counts
        """
        sync_start = datetime.utcnow()
        is_delta   = (
            self.state_manager.is_initial_sync_done()
            and not self.force_full_sync
        )

        logger.info("=" * 60)
        logger.info(
            f"Starting {'DELTA' if is_delta else 'FULL'} sync | "
            f"Sync #{self.state_manager.get_sync_count() + 1}"
        )
        if is_delta:
            last = self.state_manager.get_last_sync_time()
            logger.info(f"Delta since: {last}")
        logger.info("=" * 60)

        self.state_manager.mark_sync_in_progress()

        try:
            # ── Step 1: Fetch tasks ───────────────────────────────────────────
            logger.info(f"--- Step 1: Fetching Tasks ({'DELTA' if is_delta else 'FULL'}) ---")

            if is_delta:
                todoist_tasks, notion_tasks, all_todoist, all_notion = \
                    self._fetch_delta()
            else:
                todoist_tasks, notion_tasks = self._fetch_full()
                all_todoist    = todoist_tasks
                all_notion     = notion_tasks

            # Track what changed for delta-mode skipping logic
            todoist_changed = todoist_tasks if is_delta else []
            notion_changed  = notion_tasks  if is_delta else []

            self.stats.todoist_tasks_fetched = len(todoist_tasks)
            self.stats.notion_tasks_fetched  = len(notion_tasks)

            # Build indices from ALL tasks (needed for parent lookups)
            todoist_index = {t.id: t for t in all_todoist}
            notion_by_todoist_id = {
                t.todoist_task_id: t
                for t in all_notion
                if t.todoist_task_id
            }

            # Notion tasks without Todoist ID (new tasks)
            notion_without_id = [
                t for t in notion_tasks
                if not t.todoist_task_id
            ]

            # Log what was fetched
            active_t   = [t for t in todoist_tasks if not t.completed]
            completed_t = [t for t in todoist_tasks if t.completed]
            logger.info(
                f"Todoist changed: {len(todoist_tasks)} "
                f"({len(active_t)} active, {len(completed_t)} completed)"
            )
            logger.info(
                f"Notion changed: {len(notion_tasks)} | "
                f"New (no ID): {len(notion_without_id)}"
            )
            if is_delta:
                logger.info(
                    f"All Todoist: {len(all_todoist)} | "
                    f"All Notion: {len(all_notion)}"
                )

            # ── Step 2: Handle Notion tasks with NO Todoist ID ────────────────
            logger.info("--- Step 2: Notion → Todoist (New Tasks) ---")
            if notion_without_id:
                logger.info(
                    f"Found {len(notion_without_id)} new Notion tasks"
                )
                self._sync_notion_new_tasks_to_todoist(
                    notion_without_id,
                    todoist_index,
                    notion_by_todoist_id
                )
                # Refresh ALL tasks after creating new ones
                all_todoist   = self.todoist.get_all_tasks()
                todoist_index = {t.id: t for t in all_todoist}
            else:
                logger.info("No new Notion tasks to push to Todoist")

            # ── Step 3: Handle completed tasks ────────────────────────────────
            logger.info("--- Step 3: Completed Tasks ---")
            self._handle_completed_tasks(todoist_index, notion_by_todoist_id)

            # ── Step 4: Sync Todoist → Notion (create missing) ────────────────
            logger.info("--- Step 4: Todoist → Notion (Create Missing) ---")

            # In delta mode with no changes: skip expensive notion fetch
            if is_delta and not todoist_changed and not notion_changed:
                logger.info(
                    "Delta mode + no changes → skipping creation check"
                )
                notion_by_todoist_id = {
                    t.todoist_task_id: t
                    for t in all_notion
                    if t.todoist_task_id
                }
            else:
                # Use ALL active tasks for creation check
                active_tasks = [t for t in all_todoist if not t.completed]
                sorted_tasks = self._topological_sort(active_tasks)
                self._sync_todoist_to_notion(sorted_tasks, notion_by_todoist_id)

                # Refresh Notion after potential creations
                all_notion = self.notion.get_all_tasks()
                notion_by_todoist_id = {
                    t.todoist_task_id: t
                    for t in all_notion
                    if t.todoist_task_id
                }

            # ── Step 5: Apply field-level updates ─────────────────────────────
            logger.info("--- Step 5: Field-Level Updates ---")
            # In delta mode: only update tasks that actually changed
            changed_todoist_ids = {t.id for t in todoist_tasks}
            changed_notion_ids  = {
                t.todoist_task_id for t in notion_tasks
                if t.todoist_task_id
            }
            changed_ids = changed_todoist_ids | changed_notion_ids

            self._apply_field_updates(
                todoist_index        = todoist_index,
                notion_index         = notion_by_todoist_id,
                changed_ids          = changed_ids if is_delta else None
            )

            # ── Step 6: Finalize ──────────────────────────────────────────────
            logger.info("--- Step 6: Finalizing ---")
            self.state_manager.set_last_sync_time(sync_start)

            if not self.state_manager.is_initial_sync_done():
                self.state_manager.mark_initial_sync_done()

            sync_count = self.state_manager.increment_sync_count()
            self.state_manager.save_state()
            self.state_manager.clear_sync_in_progress()

            # ── Step 7: Summary ───────────────────────────────────────────────
            self.summary.total_tasks_synced = len(notion_by_todoist_id)
            self.summary.finalize()

            logger.info("=" * 60)
            logger.info(
                f"{'DELTA' if is_delta else 'FULL'} Sync "
                f"#{sync_count} completed"
            )
            logger.info(str(self.stats))
            logger.info("=" * 60)

            report = self.summary.generate_report(detailed=True)
            print("\n" + report.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(sys.stdout.encoding or "utf-8"))

            if not settings.dry_run:
                self.summary.save_to_file("sync_report.txt")

            return self.stats

        except Exception as e:
            logger.error(f"Sync cycle failed: {e}", exc_info=True)
            self.stats.errors += 1
            self.summary.errors.append(str(e))
            self.state_manager.clear_sync_in_progress()
            raise

    # ─────────────────────────────────────────────────────────────────────────
    # FETCH METHODS
    # ─────────────────────────────────────────────────────────────────────────

    def _fetch_full(
        self
    ) -> Tuple[List[TodoistTask], List[NotionTask]]:
        """
        Full sync: fetch ALL tasks from both systems.
        Used on first run or when forced.

        Returns:
            (todoist_tasks, notion_tasks)
        """
        logger.info("FULL FETCH: Getting all tasks from both systems...")

        todoist_tasks = self.todoist.get_all_tasks()
        notion_tasks  = self.notion.get_all_tasks()

        logger.info(
            f"Full fetch: {len(todoist_tasks)} Todoist, "
            f"{len(notion_tasks)} Notion"
        )
        return todoist_tasks, notion_tasks

    def _fetch_delta(
        self
    ) -> Tuple[
        List[TodoistTask],
        List[NotionTask],
        List[TodoistTask],
        List[NotionTask]
    ]:
        """
        Delta sync: fetch ONLY tasks modified since last sync.
        Also fetches full index for parent lookups.

        Returns:
            (changed_todoist, changed_notion, all_todoist, all_notion)
        """
        last_sync = self.state_manager.get_last_sync_time()

        if not last_sync:
            logger.warning("No last_sync_time - falling back to full sync")
            todoist_all, notion_all = self._fetch_full()
            return todoist_all, notion_all, todoist_all, notion_all

        logger.info(f"DELTA FETCH: Changes since {last_sync.isoformat()}")

        # Fetch changed tasks
        todoist_changed = self.todoist.get_tasks_modified_after(last_sync)
        notion_changed  = self.notion.get_tasks_modified_after(last_sync)

        logger.info(
            f"Changed: {len(todoist_changed)} Todoist, "
            f"{len(notion_changed)} Notion"
        )

        # Only fetch full index if something changed or on first few syncs
        # This avoids expensive full fetch when nothing has changed
        sync_count = self.state_manager.get_sync_count()
        needs_full_index = (
            len(todoist_changed) > 0 or
            len(notion_changed) > 0 or
            sync_count <= 2  # Always refresh on first few syncs
        )

        if needs_full_index:
            logger.info("Fetching full index (changes detected or early sync)...")
            todoist_all = self.todoist.get_all_tasks()
            notion_all  = self.notion.get_all_tasks()
        else:
            # Nothing changed - use changed lists as the index
            # (they will be empty, so no processing happens)
            logger.info(
                "No changes detected - skipping full index fetch"
            )
            todoist_all = todoist_changed
            notion_all  = notion_changed

        logger.info(
            f"Delta: {len(todoist_changed)}/{len(todoist_all)} Todoist | "
            f"{len(notion_changed)}/{len(notion_all)} Notion"
        )

        return todoist_changed, notion_changed, todoist_all, notion_all

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 2: NOTION NEW TASKS → TODOIST
    # ─────────────────────────────────────────────────────────────────────────

    def _sync_notion_new_tasks_to_todoist(
        self,
        notion_tasks_without_id: List[NotionTask],
        todoist_index: Dict[str, TodoistTask],
        notion_by_todoist_id: Dict[str, NotionTask]
    ) -> None:
        """Create Notion tasks (no Todoist ID) in Todoist."""
        parents  = [t for t in notion_tasks_without_id if not t.parent_id]
        subtasks = [t for t in notion_tasks_without_id if t.parent_id]

        logger.info(
            f"New Notion tasks: {len(parents)} parents, "
            f"{len(subtasks)} subtasks"
        )

        for notion_task in parents:
            self._create_todoist_from_notion(
                notion_task, todoist_index, is_subtask=False
            )
        for notion_task in subtasks:
            self._create_todoist_from_notion(
                notion_task, todoist_index, is_subtask=True
            )

    def _create_todoist_from_notion(
        self,
        notion_task: NotionTask,
        todoist_index: Dict[str, TodoistTask],
        is_subtask: bool = False
    ) -> Optional[str]:
        """Create a single Notion task in Todoist and link back."""
        try:
            if not notion_task.sync_enabled:
                logger.debug(
                    f"Skipping '{notion_task.title}' - sync not enabled"
                )
                return None

            parent_todoist_id = None
            if is_subtask and notion_task.parent_id:
                if notion_task.parent_id not in todoist_index:
                    logger.warning(
                        f"Skipping subtask '{notion_task.title}' - "
                        f"parent {notion_task.parent_id} not in Todoist"
                    )
                    return None
                parent_todoist_id = notion_task.parent_id

            if settings.dry_run:
                logger.info(
                    f"[DRY RUN] Would create in Todoist: "
                    f"'{notion_task.title}'"
                )
                return None

            logger.info(
                f"Creating in Todoist: '{notion_task.title}'"
                f"{' (subtask)' if is_subtask else ''}"
            )

            created_task   = self.todoist.create_task(
                content     = notion_task.title,
                description = notion_task.description or "",
                priority    = notion_task.priority,
                due_date    = notion_task.due_date,
                labels      = notion_task.labels or [],
                parent_id   = parent_todoist_id
            )
            new_todoist_id = created_task.id

            self.notion.update_task(
                page_id              = notion_task.id,
                todoist_task_id      = new_todoist_id,
                last_modified_source = TaskSource.TODOIST
            )

            task_model = notion_task.to_task()
            self.state_manager.update_state(
                todoist_id     = new_todoist_id,
                task           = task_model,
                notion_page_id = notion_task.id
            )

            self.summary.tasks_created_in_todoist.append(notion_task.title)
            self.stats.tasks_created_in_todoist += 1
            logger.info(f"✅ Created [{new_todoist_id}]: '{notion_task.title}'")
            return new_todoist_id

        except Exception as e:
            logger.error(
                f"Failed to create Todoist task from Notion "
                f"'{notion_task.title}': {e}"
            )
            self.stats.errors += 1
            return None

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 3: COMPLETED TASKS
    # ─────────────────────────────────────────────────────────────────────────

    def _handle_completed_tasks(
        self,
        todoist_index: Dict[str, TodoistTask],
        notion_index: Dict[str, NotionTask]
    ) -> None:
        """Mark tasks completed in Todoist as completed in Notion."""
        for todoist_id, notion_task in notion_index.items():
            if todoist_id not in todoist_index:
                if notion_task.completed:
                    continue
                if notion_task.last_modified_source == TaskSource.NOTION:
                    continue

                logger.info(
                    f"'{notion_task.title}' not in active Todoist "
                    f"→ marking completed in Notion"
                )

                if settings.dry_run:
                    logger.info(
                        f"[DRY RUN] Would complete: '{notion_task.title}'"
                    )
                    continue

                try:
                    self.notion.update_task(
                        page_id              = notion_task.id,
                        completed            = True,
                        last_modified_source = TaskSource.TODOIST
                    )
                    self.stats.tasks_updated_in_notion += 1
                    self.summary.tasks_completed.append(notion_task.title)
                    logger.info(
                        f"✅ Completed in Notion: '{notion_task.title}'"
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to complete {notion_task.id}: {e}"
                    )
                    self.stats.errors += 1

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 4: TODOIST → NOTION (Create missing)
    # ─────────────────────────────────────────────────────────────────────────

    def _sync_todoist_to_notion(
        self,
        sorted_tasks: List[TodoistTask],
        notion_index: Dict[str, NotionTask]
    ) -> None:
        """Create active Todoist tasks that don't exist in Notion yet."""
        for todoist_task in sorted_tasks:
            try:
                # ── Duplicate prevention ──────────────────────────────────────
                # Check Notion index first
                if todoist_task.id in notion_index:
                    continue

                # Double-check via API to prevent duplicates
                # (catches cases where notion_index is stale)
                existing_page = self.notion._find_page_by_todoist_id(
                    todoist_task.id
                )
                if existing_page:
                    logger.debug(
                        f"Skipping '{todoist_task.content}' - "
                        f"already exists in Notion [{existing_page}]"
                    )
                    continue

                if todoist_task.parent_id:
                    if todoist_task.parent_id not in notion_index:
                        logger.warning(
                            f"Skipping subtask '{todoist_task.content}' - "
                            f"parent not in Notion yet"
                        )
                        self.stats.tasks_skipped += 1
                        continue

                if settings.dry_run:
                    logger.info(
                        f"[DRY RUN] Would create in Notion: "
                        f"'{todoist_task.content}'"
                    )
                    self.stats.tasks_created_in_notion += 1
                    continue

                self._create_notion_task(todoist_task)
                self.stats.tasks_created_in_notion += 1

            except Exception as e:
                logger.error(
                    f"Failed to create Notion task for "
                    f"{todoist_task.id}: {e}"
                )
                self.stats.errors += 1

    def _create_notion_task(self, todoist_task: TodoistTask) -> None:
        """Create a task in Notion from Todoist task."""
        logger.info(
            f"Creating in Notion: '{todoist_task.content}'"
            f"{' (subtask)' if todoist_task.parent_id else ''}"
        )

        notion_page_id = self.notion.create_task(
            title             = todoist_task.content,
            todoist_task_id   = todoist_task.id,
            description       = todoist_task.description,
            priority          = todoist_task.priority,
            due_date          = todoist_task.due_datetime,
            completed         = todoist_task.completed,
            labels            = todoist_task.labels,
            parent_todoist_id = todoist_task.parent_id,
            source            = TaskSource.TODOIST
        )

        task_model = todoist_task.to_task()
        self.state_manager.update_state(
            todoist_id     = todoist_task.id,
            task           = task_model,
            notion_page_id = notion_page_id
        )

        self.summary.tasks_created_in_notion.append(todoist_task.content)
        logger.info(
            f"✅ Created Notion task: '{todoist_task.content}' "
            f"→ Page: {notion_page_id}"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 5: FIELD-LEVEL UPDATES
    # ─────────────────────────────────────────────────────────────────────────

    def _apply_field_updates(
        self,
        todoist_index: Dict[str, TodoistTask],
        notion_index: Dict[str, NotionTask],
        changed_ids: Optional[Set[str]] = None
    ) -> None:
        """
        Apply field-level updates using three-way merge.

        Args:
            todoist_index: All Todoist tasks by ID
            notion_index:  All Notion tasks by Todoist ID
            changed_ids:   If set (delta mode), only update these task IDs.
                           If None (full mode), update all tasks.
        """
        updated_count = 0
        skipped_count = 0

        for todoist_id, notion_task in notion_index.items():
            try:
                todoist_task = todoist_index.get(todoist_id)
                if not todoist_task:
                    continue

                # Skip completed tasks in field updates
                if todoist_task.completed:
                    continue

                # DELTA MODE: skip tasks that haven't changed
                if changed_ids is not None and todoist_id not in changed_ids:
                    skipped_count += 1
                    continue

                todoist_updated_at = self._get_todoist_updated_at(todoist_task)
                notion_last_edited = self._get_notion_last_edited(notion_task)

                notion_updates, todoist_updates = self._compute_field_updates(
                    todoist_task       = todoist_task,
                    notion_task        = notion_task,
                    todoist_updated_at = todoist_updated_at,
                    notion_last_edited = notion_last_edited
                )

                if notion_updates:
                    if not settings.dry_run:
                        self._apply_notion_updates(
                            notion_task.id, notion_updates
                        )
                        self.stats.tasks_updated_in_notion += 1
                    else:
                        logger.info(
                            f"[DRY RUN] Would update Notion "
                            f"'{notion_task.title}': "
                            f"{len(notion_updates)} fields"
                        )

                if todoist_updates:
                    if not settings.dry_run:
                        self._apply_todoist_updates(
                            todoist_task.id, todoist_updates
                        )
                        self.stats.tasks_updated_in_todoist += 1
                    else:
                        logger.info(
                            f"[DRY RUN] Would update Todoist "
                            f"'{todoist_task.content}': "
                            f"{len(todoist_updates)} fields"
                        )

                # Always update local state baseline
                current_model = todoist_task.to_task()
                self.state_manager.update_state(
                    todoist_id         = todoist_id,
                    task               = current_model,
                    notion_page_id     = notion_task.id,
                    todoist_updated_at = todoist_updated_at,
                    notion_last_edited = notion_last_edited
                )
                updated_count += 1

            except Exception as e:
                logger.error(
                    f"Failed to apply updates for {todoist_id}: {e}"
                )
                self.stats.errors += 1

        self.state_manager.save_state()

        mode = "delta" if changed_ids is not None else "full"
        logger.info(
            f"Field updates ({mode}): {updated_count} processed | "
            f"{skipped_count} skipped (unchanged) | "
            f"Notion: {self.stats.tasks_updated_in_notion} | "
            f"Todoist: {self.stats.tasks_updated_in_todoist}"
        )

    def _get_todoist_updated_at(
        self, todoist_task: TodoistTask
    ) -> Optional[datetime]:
        """Get Todoist task last modified timestamp."""
        try:
            if hasattr(todoist_task, 'updated_at') and todoist_task.updated_at:
                from dateutil import parser as dtparser
                dt = dtparser.parse(str(todoist_task.updated_at))
                return dt.replace(tzinfo=None) if dt.tzinfo else dt
        except Exception:
            pass
        return None

    def _get_notion_last_edited(
        self, notion_task: NotionTask
    ) -> Optional[datetime]:
        """Get Notion task last edited timestamp."""
        try:
            if hasattr(notion_task, 'last_modified_time') \
                    and notion_task.last_modified_time:
                dt = notion_task.last_modified_time
                return dt.replace(tzinfo=None) if hasattr(dt, 'tzinfo') \
                    and dt.tzinfo else dt
        except Exception:
            pass
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # COMPUTE FIELD UPDATES
    # ─────────────────────────────────────────────────────────────────────────

    def _compute_field_updates(
        self,
        todoist_task: TodoistTask,
        notion_task: NotionTask,
        todoist_updated_at: Optional[datetime] = None,
        notion_last_edited: Optional[datetime] = None
    ) -> Tuple[List[FieldUpdate], List[FieldUpdate]]:
        """
        Compute field updates using three-way merge with latest-wins conflicts.

        Returns:
            (notion_updates, todoist_updates)
        """
        notion_updates:  List[FieldUpdate] = []
        todoist_updates: List[FieldUpdate] = []

        todoist_model = todoist_task.to_task()
        notion_model  = notion_task.to_task()

        changes = self.state_manager.detect_changes(
            todoist_task       = todoist_model,
            notion_task        = notion_model,
            todoist_id         = todoist_task.id,
            todoist_updated_at = todoist_updated_at,
            notion_last_edited = notion_last_edited
        )

        # Todoist changed → push to Notion
        for field, new_value in changes['todoist_changed'].items():
            old_value = getattr(notion_model, field, None)
            logger.info(
                f"[{todoist_task.id}] {field}: "
                f"Todoist→Notion '{old_value}'→'{new_value}'"
            )
            notion_updates.append(FieldUpdate(
                field_name = field,
                old_value  = old_value,
                new_value  = new_value,
                source     = TaskSource.TODOIST,
                timestamp  = datetime.utcnow()
            ))
            self.summary.add_change(ChangeDetail(
                task_id     = todoist_task.id,
                task_title  = todoist_model.title,
                field       = field,
                old_value   = old_value,
                new_value   = new_value,
                source      = "Todoist",
                change_type = "updated"
            ))
            if field == 'completed':
                (self.summary.tasks_completed
                 if new_value else
                 self.summary.tasks_reopened).append(todoist_model.title)

        # Notion changed → push to Todoist
        for field, new_value in changes['notion_changed'].items():
            old_value     = getattr(todoist_model, field, None)
            todoist_field = 'content' if field == 'title' else field
            logger.info(
                f"[{todoist_task.id}] {field}: "
                f"Notion→Todoist '{old_value}'→'{new_value}'"
            )
            todoist_updates.append(FieldUpdate(
                field_name = todoist_field,
                old_value  = old_value,
                new_value  = new_value,
                source     = TaskSource.NOTION,
                timestamp  = datetime.utcnow()
            ))
            self.summary.add_change(ChangeDetail(
                task_id     = todoist_task.id,
                task_title  = todoist_model.title,
                field       = field,
                old_value   = old_value,
                new_value   = new_value,
                source      = "Notion",
                change_type = "updated"
            ))
            if field == 'completed':
                (self.summary.tasks_completed
                 if new_value else
                 self.summary.tasks_reopened).append(todoist_model.title)

        # Conflicts → latest timestamp wins
        for field, conflict in changes['conflicts'].items():
            winner        = conflict.get('winner', 'todoist')
            winning_value = conflict.get('winning_value', conflict['todoist'])

            logger.warning(
                f"[{todoist_task.id}] CONFLICT {field}: "
                f"Todoist='{conflict['todoist']}' vs "
                f"Notion='{conflict['notion']}' → "
                f"{winner.upper()} wins"
            )

            # ── Log conflict to file ──────────────────────────────────────────
            self.conflict_logger.log_conflict(
                todoist_id    = todoist_task.id,
                task_title    = todoist_model.title,
                field         = field,
                todoist_value = conflict['todoist'],
                notion_value  = conflict['notion'],
                winner        = winner,
                winning_value = winning_value,
                todoist_ts    = todoist_updated_at,
                notion_ts     = notion_last_edited,
                sync_count    = self.state_manager.get_sync_count()
            )
            self.stats.conflicts_detected = getattr(
                self.stats, 'conflicts_detected', 0
            ) + 1

            if winner == 'notion':
                todoist_field = 'content' if field == 'title' else field
                todoist_updates.append(FieldUpdate(
                    field_name = todoist_field,
                    old_value  = conflict['todoist'],
                    new_value  = winning_value,
                    source     = TaskSource.NOTION,
                    timestamp  = datetime.utcnow()
                ))
            else:
                notion_updates.append(FieldUpdate(
                    field_name = field,
                    old_value  = conflict['notion'],
                    new_value  = winning_value,
                    source     = TaskSource.TODOIST,
                    timestamp  = datetime.utcnow()
                ))

            self.summary.add_change(ChangeDetail(
                task_id     = todoist_task.id,
                task_title  = todoist_model.title,
                field       = field,
                old_value   = conflict['notion'],
                new_value   = winning_value,
                source      = winner.capitalize(),
                change_type = "conflict"
            ))

        return notion_updates, todoist_updates

    # ─────────────────────────────────────────────────────────────────────────
    # APPLY UPDATES
    # ─────────────────────────────────────────────────────────────────────────

    def _apply_notion_updates(
        self, page_id: str, updates: List[FieldUpdate]
    ) -> None:
        """Apply field updates to a Notion task."""
        kwargs = {}
        for u in updates:
            if u.field_name == "title":
                kwargs["title"] = u.new_value
            elif u.field_name == "description":
                kwargs["description"] = u.new_value
            elif u.field_name == "priority":
                kwargs["priority"] = u.new_value
            elif u.field_name == "due_date":
                kwargs["due_date"] = u.new_value
            elif u.field_name == "completed":
                kwargs["completed"] = u.new_value
            elif u.field_name == "labels":
                kwargs["labels"] = u.new_value
        if kwargs:
            kwargs["last_modified_source"] = TaskSource.TODOIST
            self.notion.update_task(page_id=page_id, **kwargs)

    def _apply_todoist_updates(
        self, task_id: str, updates: List[FieldUpdate]
    ) -> None:
        """Apply field updates to a Todoist task."""
        kwargs            = {}
        completion_update = None
        for u in updates:
            if u.field_name == "content":
                kwargs["content"] = u.new_value
            elif u.field_name == "description":
                kwargs["description"] = u.new_value
            elif u.field_name == "priority":
                kwargs["priority"] = u.new_value
            elif u.field_name == "due_date":
                kwargs["due_date"] = u.new_value
            elif u.field_name == "labels":
                kwargs["labels"] = u.new_value
            elif u.field_name == "completed":
                completion_update = u.new_value
        if kwargs:
            self.todoist.update_task(task_id=task_id, **kwargs)
        if completion_update is not None:
            if completion_update:
                self.todoist.complete_task(task_id)
            else:
                self.todoist.reopen_task(task_id)

    # ─────────────────────────────────────────────────────────────────────────
    # TOPOLOGICAL SORT (Parents before subtasks)
    # ─────────────────────────────────────────────────────────────────────────

    def _topological_sort(
        self, tasks: List[TodoistTask]
    ) -> List[TodoistTask]:
        """Sort tasks so parents come before their children."""
        children_map: Dict[Optional[str], List[TodoistTask]] = {}
        for task in tasks:
            pid = task.parent_id
            if pid not in children_map:
                children_map[pid] = []
            children_map[pid].append(task)

        sorted_tasks: List[TodoistTask] = []
        visited = set()

        def visit(parent_id: Optional[str]):
            if parent_id in visited:
                return
            visited.add(parent_id)
            for task in children_map.get(parent_id, []):
                sorted_tasks.append(task)
                visit(task.id)

        visit(None)
        return sorted_tasks
