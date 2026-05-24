python -c
import json
from notion_client import Client
from config import settings

client  = Client(auth=settings.notion_api_token)
page_id = '6gRh8xg3QpmVHpXh'

# Find Notion page ID first
from notion_api import NotionClient
from todoist_api import TodoistClient

notion  = NotionClient(settings.notion_api_token)
todoist = TodoistClient(settings.todoist_api_token)

n_tasks = notion.get_all_tasks()
n_task  = next(
    (t for t in n_tasks if t.todoist_task_id == '6gRh8xg3QpmVHpXh'),
    None
)

if n_task:
    print(f'Notion page ID: {n_task.id}')
    
    # Fetch raw page from API
    raw = client.pages.retrieve(page_id=n_task.id)
    props = raw.get('properties', {})
    
    # Check Description field raw
    print(f'Description raw:')
    desc = props.get('Description', {})
    print(json.dumps(desc, indent=2)[:300])
    
    # Check Due Date raw  
    print(f'Due Date raw:')
    due = props.get('Due Date', {})
    print(json.dumps(due, indent=2)[:200])
    
    print(f'Last edited: {raw.get(\"last_edited_time\")}')