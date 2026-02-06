# Notion MCP Integration Guide for Automation Project Planner

**Purpose:** Comprehensive guide to Notion Model Context Protocol (MCP) Server integration for automated project management.

**Audience:** AI agents (subagents), developers implementing Notion integration.

---

## Table of Contents

1. [Overview](#overview)
2. [Installation and Setup](#installation-and-setup)
3. [Available MCP Tools](#available-mcp-tools)
4. [Rate Limits and Best Practices](#rate-limits-and-best-practices)
5. [Database Schema Design Patterns](#database-schema-design-patterns)
6. [Database View Configurations](#database-view-configurations)
7. [Error Handling Strategies](#error-handling-strategies)

---

## Overview

The Notion MCP (Model Context Protocol) Server is an official implementation that enables AI agents to interact programmatically with Notion workspaces. It provides a hosted server architecture where Notion manages both the MCP Server and the Public API, while client applications connect remotely.

**Key Benefits:**
- Direct API integration from Claude Code
- No manual Notion UI interaction needed
- Batch operations for efficiency
- Relations and complex database structures
- Real-time project creation and updates

---

## Installation and Setup

### Prerequisites

1. **Create Notion Integration**
   - Visit https://www.notion.so/profile/integrations
   - Create an internal integration
   - Configure permissions (optionally restrict to read-only)
   - Generate integration token (format: `ntn_****`)

2. **Grant Workspace Access**
   - Connect integration to specific pages via Access tab
   - Or grant access to individual pages as needed

### Installation Methods

#### Method 1: npm (Recommended for Claude Desktop/Cursor)

Add to your MCP config file (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "notionApi": {
      "command": "npx",
      "args": ["-y", "@notionhq/notion-mcp-server"],
      "env": {
        "NOTION_TOKEN": "ntn_****"
      }
    }
  }
}
```

#### Method 2: Docker

```json
{
  "mcpServers": {
    "notionApi": {
      "command": "docker",
      "args": ["run", "--rm", "-i", "-e", "NOTION_TOKEN", "mcp/notion"],
      "env": {
        "NOTION_TOKEN": "ntn_****"
      }
    }
  }
}
```

#### Method 3: Smithery (Automated Setup)

```bash
npx -y @smithery/cli install @makenotion/notion-mcp-server --client claude
```

### Transport Options

#### STDIO Transport (Default)
For desktop clients using standard input/output:

```bash
npx @notionhq/notion-mcp-server --transport stdio
```

#### HTTP Transport
For web-based applications:

```bash
npx @notionhq/notion-mcp-server --transport http --port 8080
```

Authentication options for HTTP:
- Auto-generated token (development)
- Custom token via `--auth-token` flag
- Token via `AUTH_TOKEN` environment variable

All HTTP requests require bearer token in Authorization header.

---

## Available MCP Tools

The Notion MCP provides 14 primary tools for workspace interaction:

### Content Management Tools

#### 1. notion-search

Searches across Notion workspace and connected platforms (Slack, Google Drive, Jira).

**Use Cases:**
- Find pages by title or content
- Locate databases across workspace
- Search within connected integrations

**Rate Limit:** 30 requests per minute (stricter than general API)

**Example:**
```
"Search for all pages related to 'Project Planning'"
```

#### 2. notion-fetch

Retrieves content from specific pages or databases using URLs.

**Use Cases:**
- Extract page content by URL
- Retrieve database structure
- Get specific page properties

**Example:**
```
"Fetch content from https://notion.so/page-id"
```

#### 3. notion-create-pages

Generates one or multiple pages with specified properties and content.

**Key Features:**
- Creates private pages if no parent specified
- Supports bulk page creation
- Can set all page properties during creation

**Example:**
```
"Create a new task page titled 'Setup Database' under the Projects database with status 'To Do'"
```

#### 4. notion-update-page

Modifies existing page properties or content.

**Use Cases:**
- Update task status
- Change deadlines
- Modify page properties
- Update page content

**Example:**
```
"Update the page 'Setup Database' to status 'In Progress'"
```

#### 5. notion-move-pages

Relocates pages or databases to new parent locations.

**Use Cases:**
- Reorganize workspace structure
- Move pages between databases
- Archive completed projects

**Example:**
```
"Move 'Old Project' page to 'Archive' database"
```

#### 6. notion-duplicate-page

Creates copies of existing pages asynchronously.

**Key Features:**
- Asynchronous operation
- Copies all page content and properties
- Maintains original structure

**Example:**
```
"Duplicate the 'Project Template' page"
```

### Database Operations

#### 7. notion-create-database

Establishes new databases with specified properties, data sources, and views.

**Required Parameters:**
- Database title
- Title property (mandatory for every database)
- Parent page location (optional, creates private if not specified)

**Optional Parameters:**
- Property schema (Select, Number, Date, etc.)
- Initial views (Table, Board, Timeline, etc.)
- Database description

**Example:**
```
"Create a Tasks database with properties: Title, Status (Select), Assignee (Person), Due Date (Date), Priority (Select)"
```

**Best Practice:** Always include at least Title property in database creation to avoid API errors.

#### 8. notion-update-database

Modifies database attributes, adds fields, or updates descriptions.

**Use Cases:**
- Add new properties to existing database
- Modify property configurations
- Update database description
- Add new Select options

**Example:**
```
"Add a 'Estimated Hours' Number property to the Tasks database"
```

### Collaboration Features

#### 9. notion-create-comment

Adds comments to pages.

**Current Limitation:** Block-level comments not yet supported (page-level only).

**Use Cases:**
- Add feedback to pages
- Document decisions
- Collaborate asynchronously

**Example:**
```
"Add comment 'Approved for implementation' to the Requirements page"
```

#### 10. notion-get-comments

Retrieves all comments on specific pages, including threaded discussions.

**Use Cases:**
- Review feedback history
- Export discussion threads
- Audit page activity

**Example:**
```
"Get all comments from the Project Proposal page"
```

### User and Workspace Management

#### 11. notion-get-teams

Lists teams (teamspaces) in workspace with membership status.

**Use Cases:**
- Discover available teamspaces
- Check team membership
- Route content to appropriate teams

**Example:**
```
"List all teams in the workspace"
```

#### 12. notion-get-users

Displays all workspace users with their details.

**Use Cases:**
- Get user list for assignments
- Validate user IDs
- Build user directories

**Example:**
```
"Get all users in the workspace"
```

#### 13. notion-get-user

Retrieves information about a specific user by ID.

**Use Cases:**
- Get user details
- Verify user permissions
- Lookup user properties

**Example:**
```
"Get details for user ID abc123"
```

#### 14. notion-get-self

Returns information about the bot user and connected workspace.

**Use Cases:**
- Verify integration status
- Check workspace connection
- Get bot user ID

**Example:**
```
"Get my bot user information"
```

---

## Rate Limits and Best Practices

### Rate Limits

| Operation Type | Limit | Notes |
|---------------|-------|-------|
| General API requests | 180 requests/minute (3/second average) | Bursts allowed beyond average |
| Search operations | 30 requests/minute | Stricter limit |
| HTTP Response on limit | 429 (Rate Limited) | Includes Retry-After header |

### Best Practices for Rate Limit Handling

#### 1. Implement Retry Logic with Exponential Backoff

```javascript
async function requestWithRetry(apiCall, maxRetries = 3) {
  for (let attempt = 0; attempt < maxRetries; attempt++) {
    try {
      return await apiCall();
    } catch (error) {
      if (error.status !== 429) throw error;

      const retryAfter = parseInt(error.headers.get('retry-after'));
      await sleep(retryAfter * 1000);
    }
  }
  throw new Error('Max retries exceeded');
}
```

#### 2. Use Queue-Based Approaches

Implement queuing mechanisms for pending requests:
- Create request queue
- Consume queue at controlled rate
- Pause consumption on HTTP 429 responses
- Resume after Retry-After period

#### 3. Optimize API Usage

- **Batch operations** when possible (group related updates)
- **Cache frequently accessed data** to reduce requests
- **Use pagination efficiently** (100-record limit per request)
- **Minimize redundant calls** by storing results locally

#### 4. Handle Pagination

Most endpoints return maximum 100 records per request:

```javascript
async function getAllDatabaseItems(databaseId) {
  let allItems = [];
  let cursor = undefined;

  do {
    const response = await notion.databases.query({
      database_id: databaseId,
      start_cursor: cursor
    });

    allItems = allItems.concat(response.results);
    cursor = response.next_cursor;
  } while (cursor);

  return allItems;
}
```

### Payload Limits

- **Maximum block elements:** 1000 per request
- **Maximum payload size:** 500KB overall
- **Strategy:** Split large operations into multiple requests

---

## Database Schema Design Patterns

### Property Types Reference

| Property Type | Use Case | API Considerations |
|--------------|----------|-------------------|
| **Title** | Primary identifier | Required in every database, cannot be deleted |
| **Text** | Short notes, descriptions | Plain text only, no formatting |
| **Number** | Metrics, scores, quantities | Supports formats: integer, decimal, %, currency |
| **Checkbox** | Boolean states | True/false values |
| **Select** | Single-choice categories | Predefined options required |
| **Multi-Select** | Multiple-choice tags | Allows multiple selections |
| **Date** | Deadlines, milestones | Supports date ranges |
| **Person** | Assignees, owners | References workspace users |
| **Relation** | Database links | Requires shared integration access to related DB |
| **Rollup** | Aggregated data | Requires existing Relation property |
| **Formula** | Calculated values | Uses Notion formula syntax |
| **URL** | External links | Validates URL format |
| **Email** | Contact information | Validates email format |
| **Phone** | Phone numbers | String format |
| **Files & Media** | Attachments | Supports uploads and links |
| **Status** | Progress tracking | Predefined workflow states |
| **Created Time** | Auto timestamp | Auto-populated, read-only |
| **Created By** | Auto user tracking | Auto-populated, read-only |
| **Last Edited Time** | Auto timestamp | Auto-populated, read-only |
| **Last Edited By** | Auto user tracking | Auto-populated, read-only |

### Relation Property Setup

**Critical Requirement:** Related database MUST be shared with your integration.

#### Relation Types

1. **Dual Property (Two-Way Relation)**
   - Shows in both databases
   - Type: `dual_property`
   - Updates reflect in both directions

2. **Single Property (One-Way Relation)**
   - Shows in source database only
   - Type: `single_property`
   - Parent-child relationships

#### Relation Best Practices

- **Keep relations 1 level deep** - Avoid nested tables for relations and rollups
- **Use page IDs, not names** - Relations work with page IDs only
- **Share all related databases** - Integration must have access to both databases
- **Plan relation structure early** - Difficult to restructure later

### Rollup Property Patterns

Rollups aggregate data from related database entries through Relations.

**Common Rollup Functions:**
- `count_values` - Count of related items
- `sum` - Total of numeric values
- `average` - Mean of numeric values
- `min` / `max` - Extremes in range
- `percent_checked` - Percentage of completed checkboxes
- `percent_per_group` - Distribution by Select property

**Example: Project Task Completion**
```
Database: Projects
Relation: Tasks (to Tasks database)
Rollup Property: Task Completion
  - Relation: Tasks
  - Property: Status
  - Calculate: Percent per group → Complete
```

### Formula Property Patterns for PM

#### 1. Progress Percentage
```
prop("Completed Tasks") / prop("Total Tasks") * 100
```

#### 2. Days Until Deadline
```
dateBetween(prop("Due Date"), now(), "days")
```

#### 3. Status Indicator
```
if(prop("Progress") == 1, "✅ Complete",
   if(prop("Progress") >= 0.5, "🔄 In Progress",
      "⏳ Not Started"))
```

#### 4. Priority Score
```
if(prop("Priority") == "High", 3,
   if(prop("Priority") == "Medium", 2, 1))
* if(prop("Status") != "Complete", 1, 0)
```

#### 5. Project Health
```
if(dateBetween(prop("Due Date"), now(), "days") < 0, "🔴 Overdue",
   if(prop("Progress") >= 0.8, "🟢 On Track",
      if(prop("Progress") >= 0.5, "🟡 At Risk",
         "🔴 Behind")))
```

---

## Database View Configurations

### Available View Types

| View Type | Best For | Key Features |
|-----------|----------|--------------|
| **Table** | Detailed data management | Grid layout, sorting, filtering, inline editing |
| **Board (Kanban)** | Workflow visualization | Group by Select/Multi-Select/Person, drag-and-drop |
| **List** | Minimal space usage | Compact, clean layout, good for many items |
| **Calendar** | Event scheduling | Monthly/weekly views, date-based display |
| **Gallery** | Visual content | Image-focused, category organization |
| **Timeline (Gantt)** | Project scheduling | Horizontal bars, dependency visualization, date ranges |

### View Configuration Best Practices

#### For Project Management

1. **Projects Database Views:**
   - Table view: Overview with all properties
   - Board view: Grouped by Status
   - Timeline view: Project schedules
   - Calendar view: Milestones and deadlines

2. **Tasks Database Views:**
   - Table view: All task details
   - Board view: Grouped by Status (Kanban)
   - Timeline view: Task scheduling
   - Calendar view: Due dates
   - List view: Simple task list by assignee

3. **Timeline Database Views:**
   - Timeline view: Gantt chart visualization
   - Table view: Detailed timeline data

### Filters and Sorts

**Common Filter Patterns:**
- Active projects: `Status is not Complete`
- My tasks: `Assignee contains [Current User]`
- Overdue: `Due Date is before Today`
- High priority: `Priority is High`

**Common Sort Patterns:**
- By deadline: `Due Date ascending`
- By priority: `Priority descending, Due Date ascending`
- By status: `Status ascending, Created Time descending`

---

## Error Handling Strategies

### Error Categories

#### 1. Logical Errors (Don't Retry)
- 401 Unauthorized - Permission issues
- 404 Not Found - Invalid page/database ID
- 400 Bad Request - Invalid parameters
- 409 Conflict - Version conflicts

**Strategy:** Log error, notify user, don't retry

#### 2. Ephemeral Errors (Retry Recommended)
- 429 Rate Limited - Too many requests
- 500 Internal Server Error - Temporary server issue
- 502/503/504 Gateway errors - Network issues

**Strategy:** Implement retry with backoff

### Retry Implementation Pattern

```python
import time
from typing import Callable, Any

def retry_with_backoff(
    func: Callable,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0
) -> Any:
    """
    Retry function with exponential backoff.

    Args:
        func: Function to retry
        max_retries: Maximum retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds

    Returns:
        Function result if successful

    Raises:
        Last exception if all retries fail
    """
    for attempt in range(max_retries):
        try:
            return func()
        except APIError as e:
            if e.code == 429:  # Rate limited
                retry_after = int(e.headers.get('retry-after', base_delay * (2 ** attempt)))
                delay = min(retry_after, max_delay)
                time.sleep(delay)
            elif 500 <= e.status < 600:  # Server errors
                delay = min(base_delay * (2 ** attempt), max_delay)
                time.sleep(delay)
            else:
                raise  # Don't retry logical errors

    raise Exception(f"Failed after {max_retries} retries")
```

### Error Handling Checklist

- ✅ Categorize errors (logical vs ephemeral)
- ✅ Implement retry logic for ephemeral errors
- ✅ Respect Retry-After headers for 429 responses
- ✅ Use exponential backoff for server errors
- ✅ Log all errors with context
- ✅ Set maximum retry limits
- ✅ Provide user-friendly error messages
- ✅ Test error handling with edge cases

---

## Integration Workflow Patterns

### Pattern 1: Project Creation Workflow

**Goal:** Create complete hierarchical project structure.

**Steps:**
1. Create main project page in Projects database
2. Create subproject pages with parent relations
3. Create task pages with project relations
4. Setup dependency relations between tasks
5. Add detailed descriptions as page content
6. Validate all relations established

**Pseudo-code:**
```python
# 1. Create main project
project_id = notion_create_page(
    database_id=projects_db,
    properties={
        "Name": "Customer Portal Automation",
        "Status": "Planung",
        "Priority": "High",
        "Start Date": "2025-01-15",
        "End Date": "2025-06-30",
        "Risk Level": "Medium"
    }
)

# 2. Create subprojects with parent relation
subproject_id = notion_create_page(
    database_id=projects_db,
    properties={
        "Name": "Authentication System",
        "Parent Project": [project_id],
        "Status": "Planung",
        "Priority": "Critical"
    }
)

# 3. Create tasks with relations
task1_id = notion_create_page(
    database_id=tasks_db,
    properties={
        "Name": "API Design",
        "Project": [subproject_id],
        "Status": "Todo",
        "Estimated Hours": 16,
        "Complexity": "Medium"
    }
)

task2_id = notion_create_page(
    database_id=tasks_db,
    properties={
        "Name": "API Implementation",
        "Project": [subproject_id],
        "Dependencies": [task1_id],  # blocked by API Design
        "Estimated Hours": 40,
        "Complexity": "Complex"
    }
)
```

### Pattern 2: Batch Page Creation

**Goal:** Create multiple pages efficiently.

**Strategy:**
```python
# Collect all page definitions
pages_to_create = [
    {"database_id": tasks_db, "properties": {...}},
    {"database_id": tasks_db, "properties": {...}},
    # ... more pages
]

# Create in batches to respect rate limits
batch_size = 10
for i in range(0, len(pages_to_create), batch_size):
    batch = pages_to_create[i:i+batch_size]

    # Create pages
    for page_def in batch:
        page_id = notion_create_page(**page_def)
        # Store page_id for later relation setup

    # Small delay to avoid rate limits
    time.sleep(1)
```

### Pattern 3: Dependency Relation Setup

**Goal:** Setup task dependencies after all tasks are created.

**Strategy:**
```python
# First pass: Create all tasks without dependencies
task_ids = {}
for task in all_tasks:
    task_id = notion_create_page(
        database_id=tasks_db,
        properties={
            "Name": task['name'],
            "Project": [project_id],
            # ... other properties
        }
    )
    task_ids[task['name']] = task_id

# Second pass: Setup dependencies
for task in all_tasks:
    if task['dependencies']:
        dependency_ids = [task_ids[dep_name] for dep_name in task['dependencies']]

        notion_update_page(
            page_id=task_ids[task['name']],
            properties={
                "Dependencies": dependency_ids
            }
        )
```

### Pattern 4: Progress Sync

**Goal:** Update task statuses and progress.

**Strategy:**
```python
# Get local task updates
updated_tasks = get_local_task_updates()

# Batch update in Notion
for task in updated_tasks:
    notion_update_page(
        page_id=task['notion_id'],
        properties={
            "Status": task['new_status'],
            "Actual Hours": task['actual_hours'],
            "Progress": task['progress_pct']
        }
    )
```

---

## Validation Checklist

Before creating project in Notion:
- ✅ Notion MCP Server is configured and connected
- ✅ API token has required permissions
- ✅ All required databases are shared with integration
- ✅ Database schemas are properly defined
- ✅ All task data is validated (no missing fields)
- ✅ Dependency graph has no cycles
- ✅ Timeline is realistic and achievable

After creating project in Notion:
- ✅ All pages created successfully
- ✅ All parent-child relations established
- ✅ All dependency relations established
- ✅ Timeline view displays correctly
- ✅ Kanban board shows all tasks
- ✅ Progress calculations work
- ✅ No orphaned pages

---

## References

- **Notion MCP Server Documentation:** https://github.com/makenotion/notion-mcp-server
- **Notion API Reference:** https://developers.notion.com/reference
- **Notion Property Types:** https://developers.notion.com/reference/property-object
- **Notion Database Reference:** https://developers.notion.com/reference/database
- **MCP Specification:** https://modelcontextprotocol.io/

---

**Last Updated:** 2025-01-10
**Version:** 1.0.0
