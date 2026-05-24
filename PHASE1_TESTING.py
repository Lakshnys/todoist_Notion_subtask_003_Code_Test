# PHASE 1 TESTING INSTRUCTIONS
# Backup System: config.py + backup_manager.py + main.py
# ════════════════════════════════════════════════════════

# ── FILES TO INSTALL ─────────────────────────────────────
#
#  Download and replace in your project folder:
#
#  1. config.py           ← Replace existing
#  2. backup_manager.py   ← NEW file (add to project)
#  3. main.py             ← Replace existing
#
# ── .env UPDATES NEEDED ──────────────────────────────────
#
#  Add these lines to your .env file:
#
#  SYNC_INTERVAL_SECONDS=900
#  BACKUP_PRE_SYNC_ENABLED=true
#  BACKUP_PRE_SYNC_KEEP=5
#  BACKUP_FULL_ENABLED=true
#  BACKUP_FULL_EVERY_DAYS=3
#  BACKUP_FULL_KEEP=4
#  BACKUP_WEEKLY_ENABLED=true
#  BACKUP_WEEKLY_KEEP=4
#  BACKUP_DIR=backups
#
# ════════════════════════════════════════════════════════
# TEST SEQUENCE - Run in this exact order
# ════════════════════════════════════════════════════════

TESTS = {

    # ────────────────────────────────────────────────────
    # TEST 1: Config loads correctly
    # ────────────────────────────────────────────────────
    "TEST_1": {
        "name": "Config Loads Correctly",
        "command": "python -c \"from config import settings; print('Sync interval:', settings.sync_interval_seconds, 'seconds'); print('Backup dir:', settings.backup_dir); print('Full backup every:', settings.backup_full_every_days, 'days'); print('✅ Config OK')\"",
        "expected_output": """
Sync interval: 900 seconds
Backup dir: backups
Full backup every: 3 days
✅ Config OK
        """,
        "if_fails": "Check .env file has all backup settings added"
    },

    # ────────────────────────────────────────────────────
    # TEST 2: backup_manager.py imports correctly
    # ────────────────────────────────────────────────────
    "TEST_2": {
        "name": "backup_manager.py Imports Correctly",
        "command": "python -c \"from backup_manager import BackupManager; mgr = BackupManager(); print('✅ BackupManager OK')\"",
        "expected_output": "✅ BackupManager OK",
        "if_fails": "Check backup_manager.py is in project folder"
    },

    # ────────────────────────────────────────────────────
    # TEST 3: main.py imports correctly
    # ────────────────────────────────────────────────────
    "TEST_3": {
        "name": "main.py Imports Correctly",
        "command": "python -c \"import main; print('✅ main.py OK')\"",
        "expected_output": "✅ main.py OK",
        "if_fails": "Check main.py is in project folder and all imports resolve"
    },

    # ────────────────────────────────────────────────────
    # TEST 4: Help command shows all options
    # ────────────────────────────────────────────────────
    "TEST_4": {
        "name": "Help Command Shows All Options",
        "command": "python main.py --help",
        "expected_output": """
Should show:
  --continuous
  --dry-run
  --backup
  --list-backups
  --validate-backup
  --restore-state
  --restore-notion
  --restore-todoist
  --restore-all
  --snapshot
        """,
        "if_fails": "main.py not updated correctly - recheck file"
    },

    # ────────────────────────────────────────────────────
    # TEST 5: Create first full snapshot (CRITICAL)
    # ────────────────────────────────────────────────────
    "TEST_5": {
        "name": "Create First Full Snapshot",
        "command": "python main.py --backup",
        "expected_output": """
======================================================================
📦 CREATING FULL SNAPSHOT
======================================================================

🔄 Creating manual snapshot...
   📥 Fetching Todoist tasks...
   ✅ Todoist: XX tasks (XX parents, XX subtasks)
   📥 Fetching Notion tasks...
   ✅ Notion: XX tasks (XX parents, XX subtasks)
   ✅ Sync state: XX entries

   ✅ Snapshot saved: YYYYMMDD_HHMMSS

✅ Snapshot created: YYYYMMDD_HHMMSS
   Location: /path/to/backups/snapshots/YYYYMMDD_HHMMSS
        """,
        "if_fails": "Check API credentials in .env are correct",
        "after_test": "Check backups/ folder was created with snapshot"
    },

    # ────────────────────────────────────────────────────
    # TEST 6: Verify backup folder structure
    # ────────────────────────────────────────────────────
    "TEST_6": {
        "name": "Verify Backup Folder Structure",
        "command": "dir backups\\snapshots  (Windows) OR  ls -la backups/snapshots/ (Mac/Linux)",
        "expected_output": """
backups/
  snapshots/
    YYYYMMDD_HHMMSS/
      metadata.json
      todoist_tasks.json
      notion_tasks.json
      sync_state.json
  weekly/
    (empty for now)
  pre_sync/
    (empty for now)
        """,
        "if_fails": "Snapshot creation failed in Test 5"
    },

    # ────────────────────────────────────────────────────
    # TEST 7: List all backups
    # ────────────────────────────────────────────────────
    "TEST_7": {
        "name": "List All Backups",
        "command": "python main.py --list-backups",
        "expected_output": """
======================================================================
📦 AVAILABLE SNAPSHOTS
======================================================================

📁 Full Snapshots:
----------------------------------------------------------------------

   ✅ YYYYMMDD_HHMMSS
      Type:     manual
      Created:  YYYY-MM-DD HH:MM:SS
      Todoist:  XX parents + XX subtasks
      Notion:   XX parents + XX subtasks
      State:    XX entries
      Last sync:YYYY-MM-DD HH:MM:SS

📁 Weekly Archives:
----------------------------------------------------------------------
   (none)

📁 Pre-Sync Backups:
----------------------------------------------------------------------
   (none)
======================================================================
        """,
        "if_fails": "No snapshots exist - run Test 5 first"
    },

    # ────────────────────────────────────────────────────
    # TEST 8: Validate latest snapshot
    # ────────────────────────────────────────────────────
    "TEST_8": {
        "name": "Validate Latest Snapshot",
        "command": "python main.py --validate-backup",
        "expected_output": """
======================================================================
🔍 VALIDATING LATEST SNAPSHOT
======================================================================

Snapshot: YYYYMMDD_HHMMSS
✅ Snapshot is valid!
        """,
        "if_fails": "Snapshot files may be corrupted - recreate with --backup"
    },

    # ────────────────────────────────────────────────────
    # TEST 9: Run normal sync (with pre-sync backup)
    # ────────────────────────────────────────────────────
    "TEST_9": {
        "name": "Normal Sync with Pre-Sync Backup",
        "command": "python main.py",
        "expected_output": """
============================================================
Todoist ↔ Notion Sync Engine
============================================================
Todoist Project:    XXXXXXXXXX
Notion Database:    XXXXXXXXXX
Timezone Offset:    UTC+4
Sync Interval:      900s (15 min)
Log Level:          INFO
Dry Run:            False
------------------------------------------------------------
Backup Dir:         backups/
Pre-sync backup:    Enabled
Full snapshot:      Every 3 days (keep 4)
Weekly archive:     Enabled (keep 4)
============================================================

INFO - Pre-sync backup: sync_state_YYYYMMDD_HHMMSS.json
INFO - Starting sync cycle
...
INFO - Sync cycle completed
        """,
        "after_test": """
Check backups/pre_sync/ folder:
  Should contain: sync_state_YYYYMMDD_HHMMSS.json
        """,
        "if_fails": "Check sync_engine.py is calling backup_mgr.pre_sync_backup()"
    },

    # ────────────────────────────────────────────────────
    # TEST 10: Dry run restore (SAFE - no changes made)
    # ────────────────────────────────────────────────────
    "TEST_10": {
        "name": "Dry Run Restore (Safe Preview)",
        "command": "python main.py --restore-state --dry-run",
        "expected_output": """
======================================================================
🔄 RESTORE: Sync State Only
======================================================================

   Snapshot:  YYYYMMDD_HHMMSS
   Created:   YYYY-MM-DD HH:MM:SS
   Entries:   XX

   This will ONLY restore sync tracking.
   Todoist and Notion data will NOT be changed.

[DRY RUN] Would: Restore sync_state.json?
        """,
        "if_fails": "No snapshots found - run Test 5 first"
    },

    # ────────────────────────────────────────────────────
    # TEST 11: Restore sync state (REAL restore)
    # ────────────────────────────────────────────────────
    "TEST_11": {
        "name": "Restore Sync State (Real)",
        "command": "python main.py --restore-state",
        "expected_output": """
======================================================================
🔄 RESTORE: Sync State Only
======================================================================

   Snapshot:  YYYYMMDD_HHMMSS
   Created:   YYYY-MM-DD HH:MM:SS
   Entries:   XX

   This will ONLY restore sync tracking.
   Todoist and Notion data will NOT be changed.

⚠️  Restore sync_state.json?
Continue? (yes/no): yes

   Emergency backup: sync_state_BEFORE_RESTORE_YYYYMMDD_HHMMSS.json
   ✅ sync_state.json restored from YYYYMMDD_HHMMSS
        """,
        "notes": "Type 'yes' when prompted. An emergency backup is created first.",
        "if_fails": "Check snapshot contains sync_state.json"
    },

    # ────────────────────────────────────────────────────
    # TEST 12: Continuous mode (test for 2 cycles then stop)
    # ────────────────────────────────────────────────────
    "TEST_12": {
        "name": "Continuous Sync Mode",
        "command": "python main.py --continuous --interval 30",
        "expected_output": """
INFO - Starting continuous sync
INFO - Interval: 30s (0 min)

INFO - ── Sync #1 at YYYY-MM-DD HH:MM:SS ──
INFO - Pre-sync backup: sync_state_YYYYMMDD_HHMMSS.json
...
INFO - ✅ Sync #1 completed (1/1 successful)
INFO - Next sync at HH:MM:SS (in 0 min)

(Wait 30 seconds...)

INFO - ── Sync #2 at YYYY-MM-DD HH:MM:SS ──
...

Press Ctrl+C to stop
        """,
        "notes": """
Uses 30s interval for quick testing.
Watch for:
  ✅ Pre-sync backup created each cycle
  ✅ Sync runs successfully
  ✅ Next sync time shown
Stop with Ctrl+C after 2 cycles.
        """,
        "if_fails": "Check API credentials and sync_engine.py"
    },

    # ────────────────────────────────────────────────────
    # TEST 13: Backup manager standalone
    # ────────────────────────────────────────────────────
    "TEST_13": {
        "name": "Backup Manager Standalone",
        "command": "python backup_manager.py --list",
        "expected_output": "Same as --list-backups output above",
        "notes": "backup_manager.py can be run independently from main.py"
    },

    # ────────────────────────────────────────────────────
    # TEST 14: Specific snapshot restore
    # ────────────────────────────────────────────────────
    "TEST_14": {
        "name": "Restore from Specific Snapshot",
        "command": "python main.py --restore-state --snapshot YYYYMMDD_HHMMSS",
        "notes": "Replace YYYYMMDD_HHMMSS with actual snapshot ID from --list-backups",
        "expected_output": "Same as Test 11 but uses specified snapshot"
    },
}


# ════════════════════════════════════════════════════════
# EXPECTED FOLDER STRUCTURE AFTER ALL TESTS
# ════════════════════════════════════════════════════════

EXPECTED_STRUCTURE = """
your-project/
├── main.py                    ← Updated ✅
├── config.py                  ← Updated ✅
├── backup_manager.py          ← NEW ✅
├── sync_engine.py             (existing)
├── sync_state_manager.py      (existing)
├── todoist_api.py             (existing)
├── notion_api.py              (existing)
├── models.py                  (existing)
├── retry_utils.py             (existing)
├── sync_summary.py            (existing)
├── .env                       ← Updated with backup settings
├── sync_state.json            (auto-created by sync)
└── backups/
    ├── snapshots/
    │   └── YYYYMMDD_HHMMSS/
    │       ├── metadata.json
    │       ├── todoist_tasks.json
    │       ├── notion_tasks.json
    │       └── sync_state.json
    ├── weekly/
    │   └── (created automatically every Sunday)
    └── pre_sync/
        └── sync_state_YYYYMMDD_HHMMSS.json
"""


# ════════════════════════════════════════════════════════
# QUICK TEST CHECKLIST
# ════════════════════════════════════════════════════════

CHECKLIST = """
PHASE 1 TESTING CHECKLIST
══════════════════════════

INSTALLATION:
  [ ] config.py replaced
  [ ] backup_manager.py added to project
  [ ] main.py replaced
  [ ] .env updated with backup settings

BASIC TESTS:
  [ ] TEST 1:  Config loads correctly
  [ ] TEST 2:  backup_manager imports OK
  [ ] TEST 3:  main.py imports OK
  [ ] TEST 4:  --help shows all options

BACKUP TESTS:
  [ ] TEST 5:  First snapshot created ← MOST IMPORTANT
  [ ] TEST 6:  backups/ folder structure correct
  [ ] TEST 7:  --list-backups shows snapshot
  [ ] TEST 8:  --validate-backup shows ✅ valid

SYNC TESTS:
  [ ] TEST 9:  Normal sync creates pre-sync backup
  [ ] TEST 12: Continuous mode works (30s interval)

RESTORE TESTS:
  [ ] TEST 10: Dry run restore shows preview
  [ ] TEST 11: Real restore works with confirmation

ADVANCED:
  [ ] TEST 13: backup_manager.py standalone works
  [ ] TEST 14: Specific snapshot restore works

ALL PASSED? ✅ Phase 1 Complete! Ready for Phase 2.
"""


# ════════════════════════════════════════════════════════
# TROUBLESHOOTING
# ════════════════════════════════════════════════════════

TROUBLESHOOTING = """
COMMON ISSUES & FIXES
══════════════════════

Issue: "Extra inputs are not permitted" (pydantic error)
Fix:   config.py not updated - replace with new version

Issue: "No module named backup_manager"
Fix:   backup_manager.py not in project folder

Issue: "No snapshots found"
Fix:   Run: python main.py --backup (creates first snapshot)

Issue: Snapshot shows 0 tasks
Fix:   Check API credentials in .env file

Issue: "Pre-sync backup" not showing in logs
Fix:   sync_engine.py not calling backup_mgr.pre_sync_backup()
       Check main.py passes backup_mgr to run_single_sync()

Issue: backups/ folder not created
Fix:   BackupManager.__init__ creates it automatically
       Check write permissions in project folder

Issue: Validate shows ❌ invalid
Fix:   Recreate snapshot: python main.py --backup

Issue: "Continue? (yes/no)" prompt not accepting input
Fix:   Type exactly: yes  (lowercase, no spaces)
"""


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("PHASE 1 TESTING GUIDE")
    print("Backup System: config.py + backup_manager.py + main.py")
    print("=" * 70)

    print("\n📋 QUICK CHECKLIST:")
    print(CHECKLIST)

    print("\n📁 EXPECTED STRUCTURE AFTER TESTS:")
    print(EXPECTED_STRUCTURE)

    print("\n🔧 TROUBLESHOOTING:")
    print(TROUBLESHOOTING)

    print("\n" + "=" * 70)
    print("Run tests in order: TEST_1 → TEST_2 → ... → TEST_14")
    print("Share results if any test fails!")
    print("=" * 70 + "\n")
