# Document Processing Dashboard - Requirements Specification

## Overview

A real-time admin panel feature to monitor, manage, and troubleshoot document processing operations including file uploads, embeddings, and web scraping.

## Current Codebase Analysis

### Existing Patterns

| Component | Current Implementation | Location |
|-----------|----------------------|----------|
| **Background Tasks** | FastAPI `BackgroundTasks` | `routers/retrieval.py:process_file()` |
| **Real-time Updates** | SSE via `/api/v1/files/{id}/data/content/update` | `routers/files.py` |
| **File State** | Status field: `pending` → `completed`/`failed` | `models/files.py` |
| **Admin Panel** | Svelte components at `/admin/*` routes | `src/lib/components/admin/` |
| **WebSocket** | Existing infrastructure for chat streaming | `socket/main.py` |

### Current Limitations

1. **No global processing view** - Cannot see all documents being processed
2. **No cancellation mechanism** - Stuck processes require manual intervention
3. **No progress granularity** - Only `pending`/`completed`/`failed` states
4. **No user attribution** - Cannot see which user/chat triggered processing
5. **No web scraping visibility** - Web loader operations are invisible

## Feature Requirements

### FR-1: Real-time Processing Queue View

**Description:** Display all active document processing operations in a unified dashboard.

**Data Points per Document:**
- Document name and type (file upload vs web scrape)
- User who initiated the operation
- Associated chat/conversation (if applicable)
- Current processing stage
- Progress percentage
- Start time and elapsed duration
- Estimated time remaining (if calculable)

**UI Elements:**
- Sortable/filterable table view
- Visual progress bars for each document
- Color-coded status indicators
- Auto-refresh with SSE/WebSocket updates

### FR-2: Processing State Machine

**Description:** Implement granular state tracking for document processing.

**States:**
```
QUEUED → EXTRACTING → CHUNKING → EMBEDDING → INDEXING → COMPLETED
                  ↓         ↓          ↓           ↓
               FAILED    FAILED     FAILED      FAILED
                  ↓         ↓          ↓           ↓
              CANCELLED  CANCELLED  CANCELLED  CANCELLED
```

**State Details:**
| State | Description | Progress Range |
|-------|-------------|----------------|
| `QUEUED` | Waiting in processing queue | 0% |
| `EXTRACTING` | Extracting text from file | 0-20% |
| `CHUNKING` | Splitting into chunks | 20-30% |
| `EMBEDDING` | Generating embeddings | 30-95% |
| `INDEXING` | Saving to vector DB | 95-100% |
| `COMPLETED` | Successfully processed | 100% |
| `FAILED` | Error during processing | - |
| `CANCELLED` | User cancelled operation | - |

### FR-3: Progress Tracking for Embeddings

**Description:** Track embedding progress at chunk level.

**Required Data:**
- Total chunks in document
- Chunks embedded so far
- Current batch being processed
- Retry attempts (if any)
- Rate limit status

**Integration Point:**
Extend the logging added in `embedding_function()` to emit progress events:
```python
# Already added in utils.py
log.info(f"[Embedding] {doc_label}: {embedded_count}/{total_items} chunks")
# → Convert to event emission for dashboard
```

### FR-4: Cancellation Mechanism

**Description:** Allow admins to cancel stuck or problematic processing operations.

**Requirements:**
- Cancel button per document in dashboard
- Graceful cancellation (complete current batch, skip remaining)
- Immediate cancellation option (interrupt current operation)
- Cleanup of partial data on cancellation
- Audit log of cancellation (who, when, why)

**Implementation Approach:**
```python
# Add cancellation token pattern
class ProcessingTask:
    cancel_requested: bool = False

    async def process_with_cancellation(self):
        for batch in batches:
            if self.cancel_requested:
                raise ProcessingCancelled()
            await process_batch(batch)
```

### FR-5: Web Scraping Visibility

**Description:** Include web scraping operations in the dashboard.

**Web Loader Sources (from `RAG_WEB_LOADER_URLS`):**
- Firecrawl
- Playwright
- Jina Reader
- Tavily
- SearchApi
- SearXNG
- YouTube transcripts
- Any configured external URL loaders

**Data Points:**
- Source URL being scraped
- Scraper being used
- Extraction status
- Content size extracted
- Follow-up processing status

### FR-6: Filtering and Search

**Description:** Powerful filtering to quickly find specific operations.

**Filter Options:**
- By status (queued, processing, completed, failed, cancelled)
- By document type (PDF, DOCX, web scrape, etc.)
- By user who initiated
- By associated chat
- By date range
- By processing time (show long-running)

**Search:**
- Search by document name
- Search by URL (for web scrapes)
- Search by error message (for failed)

### FR-7: Error Details and Debugging

**Description:** Detailed error information for failed operations.

**Display:**
- Error message and type
- Stack trace (expandable)
- Last successful state before failure
- Retry history
- Rate limit encounters

**Actions:**
- Retry failed operation
- View full processing log
- Download debug bundle

### FR-8: Performance Metrics

**Description:** Aggregate statistics for monitoring system health.

**Metrics:**
- Documents processed per hour/day
- Average processing time by document type
- Embedding throughput (chunks/second)
- Queue depth over time
- Failure rate trending
- Rate limit frequency

**Visualization:**
- Line charts for trends
- Bar charts for comparisons
- Current queue depth gauge

## Technical Architecture

### Backend Changes

#### New Models (`models/processing.py`)

```python
class ProcessingTask(Base):
    __tablename__ = "processing_tasks"

    id: str  # UUID
    document_id: str  # FK to files
    user_id: str  # Who initiated
    chat_id: Optional[str]  # Associated chat

    # State
    status: ProcessingStatus  # Enum
    stage: ProcessingStage  # Current stage enum
    progress: float  # 0.0 - 1.0

    # Timing
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]

    # Progress details
    total_chunks: Optional[int]
    processed_chunks: int = 0
    current_batch: int = 0
    retry_count: int = 0

    # Error tracking
    error_message: Optional[str]
    error_details: Optional[JSON]

    # Cancellation
    cancel_requested: bool = False
    cancelled_by: Optional[str]
    cancelled_at: Optional[datetime]
```

#### New Router (`routers/admin/processing.py`)

```python
@router.get("/processing/tasks")
async def list_processing_tasks(
    status: Optional[ProcessingStatus] = None,
    user_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
) -> List[ProcessingTaskResponse]:
    """List all processing tasks with filtering."""

@router.get("/processing/tasks/{task_id}")
async def get_processing_task(task_id: str) -> ProcessingTaskResponse:
    """Get detailed info for a specific task."""

@router.post("/processing/tasks/{task_id}/cancel")
async def cancel_processing_task(task_id: str, immediate: bool = False):
    """Cancel a processing task."""

@router.post("/processing/tasks/{task_id}/retry")
async def retry_processing_task(task_id: str):
    """Retry a failed task."""

@router.get("/processing/metrics")
async def get_processing_metrics() -> ProcessingMetrics:
    """Get aggregate processing metrics."""

@router.get("/processing/stream")
async def stream_processing_updates():
    """SSE endpoint for real-time updates."""
```

#### Event Emission System

```python
# Add to retrieval/utils.py
class ProcessingEventEmitter:
    async def emit_progress(self, task_id: str, stage: str, progress: float, details: dict):
        """Emit progress event to connected dashboards."""

    async def emit_state_change(self, task_id: str, new_state: str, error: Optional[str] = None):
        """Emit state change event."""
```

### Frontend Changes

#### New Admin Component (`src/lib/components/admin/Documents/ProcessingDashboard.svelte`)

```svelte
<script>
  import { onMount, onDestroy } from 'svelte';
  import { processingTasks, processingMetrics } from '$lib/stores/processing';

  let eventSource;

  onMount(() => {
    // Connect to SSE stream
    eventSource = new EventSource('/api/v1/admin/processing/stream');
    eventSource.onmessage = (event) => {
      const update = JSON.parse(event.data);
      processingTasks.update(tasks => /* merge update */);
    };
  });

  onDestroy(() => {
    eventSource?.close();
  });
</script>

<div class="processing-dashboard">
  <MetricsPanel {$processingMetrics} />
  <FilterBar bind:filters on:change={applyFilters} />
  <TaskTable tasks={$processingTasks} on:cancel={handleCancel} on:retry={handleRetry} />
</div>
```

#### Progress Bar Component

```svelte
<script>
  export let task;

  $: stageProgress = getStageProgress(task.stage, task.progress);
  $: statusColor = getStatusColor(task.status);
</script>

<div class="progress-container">
  <div class="progress-bar" style="width: {task.progress * 100}%; background: {statusColor}">
    <span class="progress-label">{task.stage}: {Math.round(task.progress * 100)}%</span>
  </div>
  {#if task.total_chunks}
    <span class="chunk-progress">{task.processed_chunks}/{task.total_chunks} chunks</span>
  {/if}
</div>
```

### Integration Points

1. **retrieval/utils.py** - Emit progress events during embedding
2. **routers/retrieval.py** - Create ProcessingTask on file upload
3. **routers/files.py** - Link file processing to task tracking
4. **Web loaders** - Add task tracking for URL scraping

## Database Migration

```sql
CREATE TABLE processing_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES files(id),
    user_id UUID NOT NULL,
    chat_id UUID,

    status VARCHAR(20) NOT NULL DEFAULT 'queued',
    stage VARCHAR(20) NOT NULL DEFAULT 'queued',
    progress FLOAT NOT NULL DEFAULT 0.0,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,

    total_chunks INTEGER,
    processed_chunks INTEGER DEFAULT 0,
    current_batch INTEGER DEFAULT 0,
    retry_count INTEGER DEFAULT 0,

    error_message TEXT,
    error_details JSONB,

    cancel_requested BOOLEAN DEFAULT FALSE,
    cancelled_by UUID,
    cancelled_at TIMESTAMP WITH TIME ZONE,

    metadata JSONB DEFAULT '{}'
);

CREATE INDEX idx_processing_tasks_status ON processing_tasks(status);
CREATE INDEX idx_processing_tasks_user ON processing_tasks(user_id);
CREATE INDEX idx_processing_tasks_created ON processing_tasks(created_at DESC);
```

## Implementation Phases

### Phase 1: Core Infrastructure (Week 1-2)
- ProcessingTask model and migration
- Basic CRUD API endpoints
- State machine implementation
- Progress tracking integration in embedding code

### Phase 2: Real-time Updates (Week 2-3)
- SSE endpoint for live updates
- Event emission from processing code
- Frontend Svelte store for task state

### Phase 3: Dashboard UI (Week 3-4)
- Task table with progress bars
- Filtering and search
- Status indicators
- Basic metrics display

### Phase 4: Operations (Week 4-5)
- Cancellation mechanism
- Retry functionality
- Error details view
- Debug log access

### Phase 5: Web Scraping Integration (Week 5-6)
- Add task tracking to web loaders
- URL-specific progress tracking
- Scraper status visibility

### Phase 6: Advanced Features (Week 6-8)
- Performance metrics and charts
- Historical data and trends
- Bulk operations
- Export/reporting

## Success Criteria

1. **Visibility**: All processing operations visible in real-time
2. **Control**: Ability to cancel any stuck operation within 5 seconds
3. **Debugging**: Root cause identifiable for any failure within 1 minute
4. **Performance**: Dashboard loads in < 2 seconds with 100+ active tasks
5. **Reliability**: No missed updates or stale data
