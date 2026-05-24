"""
Manual state restoration utility.
Use this to restore sync state from a backup after corruption or failed sync.

Usage:
    python restore_state.py
    
The script will show available backups and let you choose which to restore.
"""

import sys
from pathlib import Path
from datetime import datetime

def main():
    """Main restoration interface."""
    try:
        from sync_state_manager import SyncStateManager
    except ImportError:
        print("❌ Error: Cannot import SyncStateManager")
        print("Make sure sync_state_manager.py is in the same directory")
        return 1
    
    print("=" * 70)
    print("🔄 Sync State Restoration Utility")
    print("=" * 70)
    
    manager = SyncStateManager()
    
    # List available backups
    backups = manager.list_backups()
    
    if not backups:
        print("\n❌ No backup files found")
        print("\nBackup files should be named: sync_state_backup_YYYYMMDD_HHMMSS.json")
        return 1
    
    print(f"\n📋 Found {len(backups)} backup(s):\n")
    
    # Display backups with details
    for i, backup in enumerate(backups, 1):
        size_kb = backup.stat().st_size / 1024
        mtime = backup.stat().st_mtime
        timestamp = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
        
        # Parse backup timestamp from filename
        try:
            parts = backup.stem.split('_')
            if len(parts) >= 4:
                backup_date = parts[2]
                backup_time = parts[3]
                formatted_date = f"{backup_date[:4]}-{backup_date[4:6]}-{backup_date[6:]}"
                formatted_time = f"{backup_time[:2]}:{backup_time[2:4]}:{backup_time[4:]}"
                backup_label = f"{formatted_date} {formatted_time}"
            else:
                backup_label = "Unknown date"
        except:
            backup_label = "Unknown date"
        
        print(f"  [{i}] {backup.name}")
        print(f"      Created: {backup_label}")
        print(f"      File size: {size_kb:.1f} KB")
        print(f"      Modified: {timestamp}")
        print()
    
    # Current state info
    state_file = manager.state_file
    if state_file.exists():
        size_kb = state_file.stat().st_size / 1024
        mtime = state_file.stat().st_mtime
        timestamp = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
        print(f"📄 Current state file: {state_file.name}")
        print(f"   Size: {size_kb:.1f} KB, Modified: {timestamp}\n")
    else:
        print(f"📄 No current state file exists\n")
    
    # Prompt user for selection
    print("=" * 70)
    choice = input("\nEnter backup number to restore (or 'q' to quit): ").strip()
    
    if choice.lower() in ('q', 'quit', 'exit'):
        print("\n✋ Restoration cancelled")
        return 0
    
    try:
        idx = int(choice) - 1
        if idx < 0 or idx >= len(backups):
            print(f"\n❌ Invalid backup number: {choice}")
            print(f"   Please enter a number between 1 and {len(backups)}")
            return 1
        
        backup_file = backups[idx]
        
        # Confirm restoration
        print("\n" + "=" * 70)
        print("⚠️  WARNING: State Restoration")
        print("=" * 70)
        print(f"\nYou are about to restore state from:")
        print(f"  📁 {backup_file.name}")
        print(f"\nThis will:")
        print(f"  • Replace your current sync state")
        print(f"  • Create an emergency backup of current state")
        print(f"  • Reload the state from the selected backup")
        print("\n" + "=" * 70)
        
        confirm = input("\nType 'yes' to proceed, anything else to cancel: ").strip()
        
        if confirm.lower() != 'yes':
            print("\n✋ Restoration cancelled")
            return 0
        
        # Perform restoration
        print("\n🔄 Restoring state...")
        
        if manager.restore_from_backup(backup_file):
            print("\n" + "=" * 70)
            print("✅ SUCCESS: State restored successfully!")
            print("=" * 70)
            print(f"\n✓ Restored from: {backup_file.name}")
            print(f"✓ Emergency backup created: sync_state_before_restore.json")
            print(f"✓ Loaded {len(manager.state)} tasks into memory")
            print("\nYou can now run sync normally:")
            print("  python main.py")
            return 0
        else:
            print("\n" + "=" * 70)
            print("❌ ERROR: Failed to restore state")
            print("=" * 70)
            print("\nCheck the logs for details")
            return 1
            
    except ValueError:
        print(f"\n❌ Invalid input: '{choice}'")
        print("   Please enter a number")
        return 1
    except KeyboardInterrupt:
        print("\n\n✋ Restoration cancelled by user")
        return 0
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
