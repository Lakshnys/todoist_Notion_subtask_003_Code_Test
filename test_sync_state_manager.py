"""
test_sync_state_manager.py
──────────────────────────
Quick test script to verify sync_state_manager.py is working correctly.
Shows full output including logging and state summary.
"""

import logging
import sys

# ── Setup logging FIRST so all INFO messages are visible ─────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

from sync_state_manager import SyncStateManager

def run_tests():

    print("\n" + "=" * 70)
    print("🧪 SYNC STATE MANAGER - TEST SUITE")
    print("=" * 70)

    passed = 0
    failed = 0

    def check(name: str, condition: bool, detail: str = ""):
        nonlocal passed, failed
        if condition:
            print(f"  ✅ {name}")
            passed += 1
        else:
            print(f"  ❌ {name} {detail}")
            failed += 1

    # ── TEST 1: Load state ────────────────────────────────────────────────────
    print("\n📋 TEST 1: Load State")
    print("-" * 70)
    mgr = SyncStateManager()
    all_ids = mgr.get_all_task_ids()
    check("State loads without error",     True)
    check("Task IDs retrieved",            isinstance(all_ids, list))
    check("Metadata block exists",         mgr._get_metadata() != {})
    check("Schema version is 2.0",         mgr._get_metadata().get("schema_version") == "2.0")

    # ── TEST 2: Metadata ──────────────────────────────────────────────────────
    print("\n📋 TEST 2: Metadata")
    print("-" * 70)
    meta = mgr._get_metadata()
    check("is_initial_sync_done exists",   "is_initial_sync_done" in meta)
    check("sync_count exists",             "sync_count" in meta)
    check("last_sync_time key exists",     "last_sync_time" in meta)
    check("is_initial_sync_done() works",  isinstance(mgr.is_initial_sync_done(), bool))
    check("get_sync_count() works",        isinstance(mgr.get_sync_count(), int))

    # ── TEST 3: Increment sync count ──────────────────────────────────────────
    print("\n📋 TEST 3: Sync Count")
    print("-" * 70)
    before = mgr.get_sync_count()
    mgr.increment_sync_count()
    after  = mgr.get_sync_count()
    check("Sync count increments",         after == before + 1)

    # ── TEST 4: Last sync time ────────────────────────────────────────────────
    print("\n📋 TEST 4: Last Sync Time")
    print("-" * 70)
    from datetime import datetime
    mgr.set_last_sync_time()
    last = mgr.get_last_sync_time()
    check("set_last_sync_time() works",    last is not None)
    check("get_last_sync_time() returns datetime",
          isinstance(last, datetime))

    # ── TEST 5: Mark initial sync done ────────────────────────────────────────
    print("\n📋 TEST 5: Initial Sync Flag")
    print("-" * 70)
    mgr.mark_initial_sync_done()
    check("mark_initial_sync_done() works", mgr.is_initial_sync_done() is True)

    # ── TEST 6: Task helpers ──────────────────────────────────────────────────
    print("\n📋 TEST 6: Task Helpers")
    print("-" * 70)
    parents  = mgr.get_parent_task_ids()
    subtasks = mgr.get_subtask_ids()
    check("get_parent_task_ids() works",   isinstance(parents, list))
    check("get_subtask_ids() works",       isinstance(subtasks, list))
    check("Total = parents + subtasks",
          len(parents) + len(subtasks) == len(all_ids))

    # ── TEST 7: Conflict resolution ───────────────────────────────────────────
    print("\n📋 TEST 7: Conflict Resolution (Latest Wins)")
    print("-" * 70)

    from datetime import timedelta
    now     = datetime.utcnow()
    older   = now - timedelta(hours=2)
    newer   = now

    # Notion newer → Notion wins
    winner, value = mgr.resolve_conflict(
        field               = "title",
        todoist_value       = "Todoist Title",
        notion_value        = "Notion Title",
        todoist_updated_at  = older,
        notion_last_edited  = newer,
        todoist_id          = "test_123"
    )
    check("Notion wins when newer",        winner == "notion")
    check("Notion value returned",         value  == "Notion Title")

    # Todoist newer → Todoist wins
    winner, value = mgr.resolve_conflict(
        field               = "title",
        todoist_value       = "Todoist Title",
        notion_value        = "Notion Title",
        todoist_updated_at  = newer,
        notion_last_edited  = older,
        todoist_id          = "test_123"
    )
    check("Todoist wins when newer",       winner == "todoist")
    check("Todoist value returned",        value  == "Todoist Title")

    # No timestamps → Todoist wins (default)
    winner, value = mgr.resolve_conflict(
        field               = "title",
        todoist_value       = "Todoist Title",
        notion_value        = "Notion Title",
        todoist_updated_at  = None,
        notion_last_edited  = None,
        todoist_id          = "test_123"
    )
    check("Todoist wins when no timestamps", winner == "todoist")

    # ── TEST 8: update_state_notion_id ───────────────────────────────────────
    print("\n📋 TEST 8: Notion Page ID Tracking")
    print("-" * 70)
    if all_ids:
        first_id = all_ids[0]
        mgr.update_state_notion_id(first_id, "test-notion-page-id-abc")
        stored = mgr.get_notion_page_id(first_id)
        check("update_state_notion_id() works", stored == "test-notion-page-id-abc")
        check("get_notion_page_id() retrieves",  stored is not None)
    else:
        check("Notion ID test (skipped - no tasks)", True, "(no tasks in state)")

    # ── TEST 9: task_exists ───────────────────────────────────────────────────
    print("\n📋 TEST 9: Task Exists Check")
    print("-" * 70)
    if all_ids:
        check("task_exists() True for known ID",
              mgr.task_exists(all_ids[0]))
    check("task_exists() False for unknown ID",
          not mgr.task_exists("definitely_not_real_id_xyz"))
    check("Metadata key not counted as task",
          not mgr.task_exists(SyncStateManager.METADATA_KEY))

    # ── TEST 10: Backup ───────────────────────────────────────────────────────
    print("\n📋 TEST 10: Backup")
    print("-" * 70)
    mgr.save_state()   # Ensure state is saved first
    backup = mgr.backup_state()
    check("backup_state() creates file",   backup is not None)
    check("Backup file exists",
          backup is not None and backup.exists())
    backups = mgr.list_backups()
    check("list_backups() returns list",   isinstance(backups, list))
    check("At least 1 backup exists",      len(backups) >= 1)

    # ── FULL SUMMARY ──────────────────────────────────────────────────────────
    print("\n📋 STATE SUMMARY")
    print("-" * 70)
    mgr.print_summary()

    # ── RESULTS ──────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    total = passed + failed
    print(f"📊 RESULTS: {passed}/{total} tests passed")

    if failed == 0:
        print("✅ ALL TESTS PASSED - sync_state_manager.py is working correctly!")
        print("✅ Ready for File 2: sync_engine.py")
    else:
        print(f"❌ {failed} test(s) failed - check output above")

    print("=" * 70 + "\n")
    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
