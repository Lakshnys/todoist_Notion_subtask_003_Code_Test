# Setup Guide

This guide will walk you through setting up the Todoist ↔ Notion sync integration.

## Prerequisites

- Python 3.8 or higher
- A Todoist account
- A Notion workspace

---

## Step 1: Todoist Setup

### 1.1 Get API Token

1. Log in to Todoist
2. Go to [Settings > Integrations](https://todoist.com/prefs/integrations)
3. Scroll to "API token"
4. Copy your API token (keep it secure!)

### 1.2 Find Project ID

**Method 1: From URL**
1. Open the project in Todoist web app
2. Look at the URL: `https://todoist.com/app/project/2345678901`
3. The number at the end is your project ID

**Method 2: Using API**
```bash
curl -X GET \
  https://api.todoist.com/rest/v2/projects \
  -H "Authorization: Bearer YOUR_TODOIST_TOKEN"
```

Find your project in the JSON response and copy the `id` field.

---

## Step 2: Notion Setup

### 2.1 Create Integration

1. Go to [Notion Integrations](https://www.notion.so/my-integrations)
2. Click "+ New integration"
3. Name it (e.g., "Todoist Sync")
4. Select your workspace
5. Click "Submit"
6. Copy the "Internal Integration Token" (keep it secure!)

### 2.2 Create Database

1. Create a new page in Notion
2. Add a database (Table view recommended)
3. Add these properties **exactly as specified**:

| Property Name | Type | Configuration |
|--------------|------|---------------|
| **Title** | Title | (Default) |
| **Todoist Task ID** | Text | Plain text |
| **Priority** | Number | Format: Number |
| **Due Date** | Date | Include time: Yes |
| **Completed** | Checkbox | (Default) |
| **Parent Task** | Relation | Database: Same database, Limit: 1 |
| **Sync Enabled** | Checkbox | (Default) |
| **Source** | Select | Options: "Todoist", "Notion" |
| **Last Modified Source** | Select | Options: "Todoist", "Notion" |
| **Last Modified Time** | Date | Include time: Yes |

**CRITICAL:** 
- Use a custom "Last Modified Time" property, NOT Notion's built-in "Last edited time"
- Parent Task must be a Relation to the same database
- Property names must match exactly (case-sensitive)

### 2.3 Share Database with Integration

1. Open your database in Notion
2. Click "..." (top right) → "Add connections"
3. Search for your integration name
4. Click to connect

### 2.4 Get Database ID

**From URL:**
1. Open the database as a full page
2. Look at the URL: `https://notion.so/workspace/abc123def456?v=...`
3. Copy the part before the `?` (32 characters)
4. Remove any hyphens

**Example:**
- URL: `https://notion.so/myworkspace/a1b2c3d4e5f6-789?v=...`
- Database ID: `a1b2c3d4e5f6789`

---

## Step 3: Install Application

### 3.1 Clone Repository

```bash
git clone <repository-url>
cd todoist-notion-sync
```

### 3.2 Create Virtual Environment (Recommended)

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3.3 Install Dependencies

```bash
pip install -r requirements.txt
```

---

## Step 4: Configure

### 4.1 Create Configuration File

```bash
cp .env.example .env
```

### 4.2 Edit `.env` File

Open `.env` in a text editor and add your credentials:

```env
# Todoist Configuration
TODOIST_API_TOKEN=your_actual_todoist_token_here
TODOIST_PROJECT_ID=2345678901

# Notion Configuration
NOTION_API_TOKEN=secret_your_actual_notion_token_here
NOTION_DATABASE_ID=a1b2c3d4e5f6789

# Sync Configuration
SYNC_INTERVAL_SECONDS=300
LOG_LEVEL=INFO
DRY_RUN=false
```

**Replace:**
- `your_actual_todoist_token_here` with your Todoist API token
- `2345678901` with your actual project ID
- `secret_your_actual_notion_token_here` with your Notion integration token
- `a1b2c3d4e5f6789` with your actual database ID

---

## Step 5: Test

### 5.1 Dry Run (Safe Test)

```bash
python main.py --dry-run
```

This will:
- Connect to both APIs
- Fetch all tasks
- Show what would be synced
- Make NO changes

Check the output for any errors.

### 5.2 First Real Sync

```bash
python main.py
```

This will perform an actual sync. Monitor the output carefully.

### 5.3 Verify

1. Check your Notion database
2. Verify that Todoist tasks appear
3. Check that hierarchy is preserved
4. Confirm metadata fields are populated

---

## Step 6: Usage

### One-Time Sync
```bash
python main.py
```

### Continuous Sync (Recommended)
```bash
python main.py --continuous
```

This will:
- Run sync every 5 minutes (default)
- Continue until you stop it (Ctrl+C)
- Log all operations

### Custom Interval
```bash
python main.py --continuous --interval 600  # Every 10 minutes
```

### Run as Background Service

**Linux/Mac (using nohup):**
```bash
nohup python main.py --continuous > sync.log 2>&1 &
```

**Linux (using systemd):**
Create `/etc/systemd/system/todoist-notion-sync.service`:
```ini
[Unit]
Description=Todoist Notion Sync
After=network.target

[Service]
Type=simple
User=your-username
WorkingDirectory=/path/to/todoist-notion-sync
Environment="PATH=/path/to/venv/bin"
ExecStart=/path/to/venv/bin/python main.py --continuous
Restart=always

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl enable todoist-notion-sync
sudo systemctl start todoist-notion-sync
```

---

## Troubleshooting

### Error: "TODOIST_API_TOKEN not set"
- Check that `.env` file exists
- Verify the variable name is correct
- Ensure no spaces around `=`

### Error: "Failed to fetch tasks"
- Verify API tokens are correct
- Check internet connection
- Ensure tokens haven't expired

### Tasks not syncing
1. Check `Sync Enabled` is checked in Notion
2. Verify `Source` field is set correctly
3. Review logs for skip reasons
4. Run with `--log-level DEBUG` for details

### Duplicate tasks appearing
- Never manually delete `Todoist Task ID` from Notion
- Don't run multiple sync instances simultaneously
- Check that you're using the correct database

### Loop detection issues
- Verify you created a custom "Last Modified Time" property
- Do NOT use Notion's built-in "Last edited time"
- Check sync logs for ping-pong updates

---

## Security Notes

- Never commit `.env` file to version control
- Keep API tokens secure
- Regularly rotate tokens if compromised
- Use read-only tokens if available

---

## Next Steps

After successful setup:

1. **Test workflow:**
   - Create a task in Todoist → verify it appears in Notion
   - Create a task in Notion (with `Source = Notion`, `Sync Enabled = true`) → verify it appears in Todoist
   - Update a task in either system → verify sync

2. **Monitor logs:**
   - Check for any errors or warnings
   - Review skip reasons
   - Validate field updates

3. **Customize:**
   - Adjust sync interval
   - Configure log level
   - Set up automation (cron, systemd, etc.)

---

## Support

For issues or questions:
1. Check logs with `--log-level DEBUG`
2. Review troubleshooting section
3. Check repository issues
4. Refer to API documentation:
   - [Todoist API](https://developer.todoist.com/rest/v2/)
   - [Notion API](https://developers.notion.com/)
