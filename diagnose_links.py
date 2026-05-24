"""
Diagnostic script to check how Todoist tasks with links are returned.
Run this to see the raw data from Todoist API.
"""

import json
from config import settings
from todoist_api import TodoistClient

def diagnose_todoist_links():
    """Check how Todoist returns tasks with links."""
    
    print("\n" + "=" * 70)
    print("🔍 TODOIST LINK DIAGNOSTIC")
    print("=" * 70)
    print()
    
    # Initialize client
    client = TodoistClient(settings.todoist_api_token)
    
    # Fetch all tasks
    print("Fetching tasks from Todoist...")
    tasks = client.get_all_tasks()
    
    print(f"Found {len(tasks)} total tasks\n")
    
    # Look for tasks with links
    tasks_with_links = []
    
    for task in tasks:
        # Check content for links
        content_has_link = 'http://' in task.content or 'https://' in task.content
        desc_has_link = task.description and ('http://' in task.description or 'https://' in task.description)
        
        if content_has_link or desc_has_link:
            tasks_with_links.append(task)
    
    if not tasks_with_links:
        print("❌ No tasks with links found!")
        print()
        print("To test:")
        print("  1. Create a task in Todoist")
        print("  2. Add a link in the title: 'Check https://example.com'")
        print("  3. Or add a link in description")
        print("  4. Run this script again")
        print()
        return
    
    print(f"✅ Found {len(tasks_with_links)} task(s) with links\n")
    print("=" * 70)
    
    # Show detailed info for each task with links
    for i, task in enumerate(tasks_with_links, 1):
        print(f"\n📋 TASK {i}: {task.content}")
        print("-" * 70)
        
        print(f"\nTask ID: {task.id}")
        
        print(f"\n📝 Content (Title):")
        print(f"  Raw: {repr(task.content)}")
        print(f"  Length: {len(task.content)} chars")
        
        if 'http' in task.content.lower():
            print(f"  ✅ Contains link in CONTENT")
        else:
            print(f"  ❌ No link in content")
        
        print(f"\n📄 Description:")
        if task.description:
            print(f"  Raw: {repr(task.description)}")
            print(f"  Length: {len(task.description)} chars")
            
            if 'http' in task.description.lower():
                print(f"  ✅ Contains link in DESCRIPTION")
            else:
                print(f"  ❌ No link in description")
        else:
            print(f"  (empty)")
        
        # Check for markdown/formatted links
        if '[' in task.content or '[' in (task.description or ''):
            print(f"\n  ℹ️  Contains markdown formatting: [text](url)")
        
        # Show what will be synced
        print(f"\n🔄 What will sync to Notion:")
        print(f"  Title: {task.content}")
        print(f"  Description: {task.description or '(empty)'}")
        
        print("\n" + "=" * 70)
    
    # Summary
    print(f"\n📊 SUMMARY")
    print("-" * 70)
    print(f"Total tasks: {len(tasks)}")
    print(f"Tasks with links: {len(tasks_with_links)}")
    print(f"Project: {settings.todoist_project_id}")
    print()


if __name__ == "__main__":
    diagnose_todoist_links()
