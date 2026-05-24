"""
Main entry point for Todoist-Notion sync engine.

Usage:
  python main.py                        # Run sync once
  python main.py --continuous           # Run continuously (every 15 min)
  python main.py --dry-run              # Preview only, no changes
  python main.py --interval 600         # Custom interval in seconds

  # Backup commands (no API clients needed):
  python main.py --backup               # Create full snapshot now
  python main.py --list-backups         # List all snapshots
  python main.py --validate-backup      # Validate latest snapshot
  python main.py --restore-state        # Restore sync state only (safest)
  python main.py --restore-notion       # Restore Notion from Todoist snapshot
  python main.py --restore-todoist      # Restore Todoist from Notion snapshot
  python main.py --restore-all          # Full restore from snapshot
  python main.py --restore-all --dry-run            # Preview restore
  python main.py --restore-all --snapshot 20260223_143000  # Specific snapshot
"""

import logging
import argparse
import time
import sys
from datetime import datetime

from config import settings
from todoist_api import TodoistClient
from notion_api import NotionClient
from sync_engine import SyncEngine
from sync_state_manager import SyncStateManager
from backup_manager import BackupManager


logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# ARGUMENT PARSING
# ─────────────────────────────────────────────────────────────────────────────

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Todoist ↔ Notion Sync Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
SYNC COMMANDS:
  python main.py                        Run sync once
  python main.py --continuous           Run continuously
  python main.py --dry-run              Preview changes only
  python main.py --interval 600         Custom interval (seconds)
  python main.py --log-level DEBUG      Verbose logging

BACKUP COMMANDS:
  python main.py --backup               Create full snapshot now
  python main.py --list-backups         List all available snapshots
  python main.py --validate-backup      Validate latest snapshot

RESTORE COMMANDS (use with caution):
  python main.py --restore-state        Restore sync state only (safest)
  python main.py --restore-notion       Restore Notion from Todoist snapshot
  python main.py --restore-todoist      Restore Todoist from Notion snapshot
  python main.py --restore-all          Full restore (state + both systems)

RESTORE OPTIONS:
  --dry-run                             Preview restore without making changes
  --snapshot 20260223_143000            Use specific snapshot ID

EXAMPLES:
  python main.py --restore-all --dry-run
  python main.py --restore-state --snapshot 20260223_143000
  python main.py --continuous --log-level DEBUG
        """
    )

    # ── Sync arguments ───────────────────────────────────────────────────────
    sync_group = parser.add_argument_group('Sync Options')

    sync_group.add_argument(
        '--continuous',
        action='store_true',
        help='Run sync continuously at specified interval'
    )
    sync_group.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without applying them'
    )
    sync_group.add_argument(
        '--full-sync',
        action='store_true',
        help='Force a full sync (ignore delta, fetch all tasks)'
    )
    sync_group.add_argument(
        '--interval',
        type=int,
        default=settings.sync_interval_seconds,
        help=f'Sync interval in seconds (default: {settings.sync_interval_seconds}s = '
             f'{settings.sync_interval_seconds // 60} min)'
    )
    sync_group.add_argument(
        '--log-level',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        default=settings.log_level,
        help=f'Logging level (default: {settings.log_level})'
    )

    # ── Backup arguments ─────────────────────────────────────────────────────
    backup_group = parser.add_argument_group('Backup Options')

    backup_group.add_argument(
        '--backup',
        action='store_true',
        help='Create a full snapshot backup now'
    )
    backup_group.add_argument(
        '--list-backups',
        action='store_true',
        help='List all available snapshots'
    )
    backup_group.add_argument(
        '--validate-backup',
        action='store_true',
        help='Validate the latest snapshot'
    )

    # ── Conflict log arguments ────────────────────────────────────────────────
    conflict_group = parser.add_argument_group('Conflict Log Options')

    conflict_group.add_argument(
        '--conflicts',
        action='store_true',
        help='Show conflict log summary'
    )
    conflict_group.add_argument(
        '--conflicts-full',
        action='store_true',
        help='Show full conflict log'
    )
    conflict_group.add_argument(
        '--conflicts-days',
        type=int,
        default=7,
        metavar='DAYS',
        help='Number of days to show in conflict log (default: 7)'
    )
    conflict_group.add_argument(
        '--conflicts-clear',
        action='store_true',
        help='Clear the conflict log'
    )

    # ── Restore arguments ────────────────────────────────────────────────────
    restore_group = parser.add_argument_group('Restore Options')

    restore_group.add_argument(
        '--restore-state',
        action='store_true',
        help='Restore sync_state.json only (safest - no API changes)'
    )
    restore_group.add_argument(
        '--restore-notion',
        action='store_true',
        help='Restore Notion tasks from Todoist snapshot'
    )
    restore_group.add_argument(
        '--restore-todoist',
        action='store_true',
        help='Restore Todoist tasks from Notion snapshot'
    )
    restore_group.add_argument(
        '--restore-all',
        action='store_true',
        help='Full restore: sync state + Notion + Todoist'
    )
    restore_group.add_argument(
        '--snapshot',
        type=str,
        default=None,
        metavar='SNAPSHOT_ID',
        help='Specific snapshot ID to restore from (e.g. 20260223_143000)'
    )

    return parser.parse_args()


# ─────────────────────────────────────────────────────────────────────────────
# BACKUP COMMANDS
# ─────────────────────────────────────────────────────────────────────────────

def handle_backup_commands(args) -> bool:
    """
    Handle backup/restore commands.

    Returns:
        True if a backup command was handled (main should exit after)
        False if no backup command given (main should continue to sync)
    """
    mgr = BackupManager()

    # ── --backup ─────────────────────────────────────────────────────────────
    if args.backup:
        print("\n" + "=" * 70)
        print("📦 CREATING FULL SNAPSHOT")
        print("=" * 70)
        result = mgr.create_snapshot(snapshot_type="manual")
        if result:
            print(f"\n✅ Snapshot created: {result.name}")
            print(f"   Location: {result.absolute()}")
        else:
            print("\n❌ Snapshot creation failed. Check logs.")
            sys.exit(1)
        return True

    # ── --list-backups ────────────────────────────────────────────────────────
    if args.list_backups:
        mgr.list_all_snapshots()
        return True

    # ── --validate-backup ─────────────────────────────────────────────────────
    if args.validate_backup:
        mgr.validate_latest()
        return True

    # ── --restore-state ───────────────────────────────────────────────────────
    if args.restore_state:
        print("\n" + "=" * 70)
        print("🔄 RESTORE: Sync State Only")
        print("=" * 70)
        ok = mgr.restore_state_only(
            snapshot_id=args.snapshot,
            dry_run=args.dry_run
        )
        sys.exit(0 if ok else 1)

    # ── --restore-notion ──────────────────────────────────────────────────────
    if args.restore_notion:
        print("\n" + "=" * 70)
        print("🔄 RESTORE: Notion from Todoist Snapshot")
        print("=" * 70)
        if args.dry_run:
            print("\n[DRY RUN] Would restore Notion tasks from Todoist snapshot.")
            print("No changes will be made.")
        ok = mgr.restore_notion_from_todoist(
            snapshot_id=args.snapshot,
            dry_run=args.dry_run
        )
        sys.exit(0 if ok else 1)

    # ── --restore-todoist ─────────────────────────────────────────────────────
    if args.restore_todoist:
        print("\n" + "=" * 70)
        print("🔄 RESTORE: Todoist from Notion Snapshot")
        print("=" * 70)
        if args.dry_run:
            print("\n[DRY RUN] Would restore Todoist tasks from Notion snapshot.")
            print("No changes will be made.")
        ok = mgr.restore_todoist_from_notion(
            snapshot_id=args.snapshot,
            dry_run=args.dry_run
        )
        sys.exit(0 if ok else 1)

    # ── --restore-all ─────────────────────────────────────────────────────────
    if args.restore_all:
        if args.dry_run:
            print("\n[DRY RUN] Would perform full restore:")
            print("  1. Restore sync_state.json")
            print("  2. Restore Notion tasks from snapshot")
            print("  3. Restore Todoist tasks from snapshot")
            print("\nNo changes will be made.")
        ok = mgr.restore_all(
            snapshot_id=args.snapshot,
            dry_run=args.dry_run
        )
        sys.exit(0 if ok else 1)

    return False  # No backup command handled


# ─────────────────────────────────────────────────────────────────────────────
# SYNC FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def run_single_sync(
    todoist_client: TodoistClient,
    notion_client: NotionClient,
    backup_mgr: BackupManager,
    force_full_sync: bool = False
) -> bool:
    """
    Run a single sync cycle.

    Steps:
      1. Pre-sync backup (sync_state.json)
      2. Check scheduled backups (every 3 days / weekly)
      3. Run sync engine
      4. Log summary

    Returns:
        True if successful, False otherwise
    """
    try:
        # Step 1: Pre-sync backup
        backup_file = backup_mgr.pre_sync_backup()
        if backup_file:
            logger.info(f"Pre-sync backup: {backup_file.name}")
        else:
            logger.debug("Pre-sync backup skipped (disabled or no state file)")

        # Step 2: Check scheduled backups
        backup_mgr.check_scheduled_backups()

        # Step 3: Run sync
        engine = SyncEngine(
            todoist_client,
            notion_client,
            force_full_sync=force_full_sync
        )
        stats  = engine.run_sync()

        # Step 4: Log summary
        logger.info("")
        logger.info("Sync Summary:")
        logger.info("-" * 40)
        for line in str(stats).split('\n'):
            if line.strip():
                logger.info(line)
        logger.info("-" * 40)

        return stats.errors == 0

    except Exception as e:
        logger.error(f"Sync failed: {e}", exc_info=True)
        return False


def run_continuous_sync(
    todoist_client: TodoistClient,
    notion_client: NotionClient,
    backup_mgr: BackupManager,
    interval: int,
    force_full_sync: bool = False
):
    """
    Run sync continuously at specified interval.

    Args:
        todoist_client: Todoist API client
        notion_client:  Notion API client
        backup_mgr:     Backup manager instance
        interval:       Seconds between sync runs
    """
    interval_min = interval // 60
    logger.info(f"Starting continuous sync")
    logger.info(f"Interval: {interval}s ({interval_min} min)")
    logger.info(f"Backup: every {settings.backup_full_every_days} days")
    logger.info("Press Ctrl+C to stop")
    logger.info("")

    run_count     = 0
    success_count = 0

    try:
        while True:
            run_count += 1
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            logger.info(f"── Sync #{run_count} at {now} ──")

            success = run_single_sync(
                todoist_client,
                notion_client,
                backup_mgr,
                force_full_sync=force_full_sync
            )

            if success:
                success_count += 1
                logger.info(f"✅ Sync #{run_count} completed "
                            f"({success_count}/{run_count} successful)")
            else:
                logger.warning(f"⚠️  Sync #{run_count} failed "
                               f"({success_count}/{run_count} successful)")

            next_time = datetime.fromtimestamp(
                datetime.now().timestamp() + interval
            ).strftime('%H:%M:%S')

            logger.info(f"Next sync at {next_time} (in {interval_min} min)")
            logger.info("")

            time.sleep(interval)

    except KeyboardInterrupt:
        logger.info("")
        logger.info("=" * 60)
        logger.info("Sync stopped by user (Ctrl+C)")
        logger.info(f"Total runs:      {run_count}")
        logger.info(f"Successful runs: {success_count}")
        logger.info(f"Failed runs:     {run_count - success_count}")
        logger.info("=" * 60)


# ─────────────────────────────────────────────────────────────────────────────
# STARTUP BANNER
# ─────────────────────────────────────────────────────────────────────────────

def print_startup_banner(args):
    """Print startup information."""
    logger.info("=" * 60)
    logger.info("Todoist ↔ Notion Sync Engine")
    logger.info("=" * 60)
    logger.info(f"Todoist Project:    {settings.todoist_project_id}")
    logger.info(f"Notion Database:    {settings.notion_database_id}")
    logger.info(f"Timezone Offset:    UTC+{settings.notion_timezone_offset}")
    logger.info(f"Sync Interval:      {settings.sync_interval_seconds}s "
                f"({settings.sync_interval_seconds // 60} min)")
    logger.info(f"Log Level:          {settings.log_level}")
    logger.info(f"Dry Run:            {settings.dry_run}")
    logger.info("-" * 60)
    logger.info(f"Backup Dir:         {settings.backup_dir}/")
    logger.info(f"Pre-sync backup:    {'Enabled' if settings.backup_pre_sync_enabled else 'Disabled'}")
    logger.info(f"Full snapshot:      Every {settings.backup_full_every_days} days "
                f"(keep {settings.backup_full_keep})")
    logger.info(f"Weekly archive:     {'Enabled' if settings.backup_weekly_enabled else 'Disabled'} "
                f"(keep {settings.backup_weekly_keep})")
    logger.info("=" * 60)
    logger.info("")


# ─────────────────────────────────────────────────────────────────────────────
# VALIDATE CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

def validate_config() -> bool:
    """Validate all required configuration is present."""
    required = {
        'TODOIST_API_TOKEN':  settings.todoist_api_token,
        'TODOIST_PROJECT_ID': settings.todoist_project_id,
        'NOTION_API_TOKEN':   settings.notion_api_token,
        'NOTION_DATABASE_ID': settings.notion_database_id,
    }

    missing = [key for key, val in required.items() if not val]

    if missing:
        for key in missing:
            logger.error(f"Missing required config: {key}")
        logger.error("Please check your .env file")
        return False

    return True


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    """Main entry point."""
    args = parse_arguments()

    # Apply CLI overrides to settings BEFORE configure_logging
    if args.log_level:
        settings.log_level = args.log_level

    if args.dry_run:
        settings.dry_run = True

    # Configure logging
    settings.configure_logging()

    # ── Handle backup/restore commands (no API clients needed) ────────────────
    # These run before the startup banner for clean output
    backup_command_handled = handle_backup_commands(args)
    if backup_command_handled:
        return

    # ── Handle conflict log commands ──────────────────────────────────────────
    if args.conflicts or args.conflicts_full or args.conflicts_clear:
        from conflict_logger import ConflictLogger
        cl = ConflictLogger()
        print(f"\n  Log file: {cl.log_file.absolute()}")
        print(f"  Log size: {cl.get_log_size()}")
        print(f"  Conflicts (last {args.conflicts_days} days): "
              f"{cl.get_conflict_count(args.conflicts_days)}")

        if args.conflicts_clear:
            confirm = input("\n⚠️  Clear all conflict logs? (yes/no): ")
            if confirm.lower() == "yes":
                cl.clear_log(confirm=True)
            else:
                print("Cancelled.")
        elif args.conflicts_full:
            cl.print_full_log(days=args.conflicts_days)
        else:
            cl.print_summary(days=args.conflicts_days)
        return

    # ── Print startup banner ──────────────────────────────────────────────────
    print_startup_banner(args)

    if settings.dry_run:
        logger.warning("⚠️  DRY RUN MODE - No changes will be made")
        logger.warning("")

    # ── Validate configuration ────────────────────────────────────────────────
    if not validate_config():
        sys.exit(1)

    # ── Initialize clients ────────────────────────────────────────────────────
    try:
        logger.info("Initializing API clients...")
        todoist_client = TodoistClient(settings.todoist_api_token)
        notion_client  = NotionClient(settings.notion_api_token)
        backup_mgr     = BackupManager()
        logger.info("✅ API clients initialized")
        logger.info("")
    except Exception as e:
        logger.error(f"Failed to initialize API clients: {e}")
        sys.exit(1)

    # ── Run sync ──────────────────────────────────────────────────────────────
    try:
        if args.continuous:
            run_continuous_sync(
                todoist_client,
                notion_client,
                backup_mgr,
                args.interval,
                force_full_sync=getattr(args, 'full_sync', False)
            )
        else:
            # Single sync run
            logger.info("Running single sync...")
            success = run_single_sync(
                todoist_client,
                notion_client,
                backup_mgr,
                force_full_sync=getattr(args, 'full_sync', False)
            )
            sys.exit(0 if success else 1)

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
