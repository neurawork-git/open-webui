# Dependency Management Guide for Automation Projects

**Purpose:** Comprehensive guide to task dependencies, Critical Path Method (CPM), PERT analysis, and bottleneck detection.

**Audience:** AI agents (especially dependency-analyzer subagent), project managers.

---

## Table of Contents

1. [Dependency Types](#dependency-types)
2. [Critical Path Method (CPM)](#critical-path-method-cpm)
3. [Bottleneck Analysis](#bottleneck-analysis)
4. [Circular Dependency Detection](#circular-dependency-detection)

---

## Dependency Types

### Four Standard Dependency Relationships

#### 1. Finish-to-Start (FS) - Most Common (90%)

Predecessor must FINISH before successor can START.

**Example:** Code review must finish before deployment starts.

**Visual:**
```
Task A [======]
             Task B [======]
```

**When to Use:**
- Sequential processes
- Quality gates
- Approval workflows
- Standard task chains

**Notion Formula for Start Date:**
```
if(!empty(prop("Predecessor")),
   dateAdd(prop("Predecessor").prop("End Date"), 1, "days"),
   prop("Planned Start"))
```

#### 2. Start-to-Start (SS)

Predecessor must START before successor can START (can run in parallel).

**Example:** Writing and editing can start together, but editing can't start until writing begins.

**Visual:**
```
Task A [==============]
       Task B [===========]
```

**When to Use:**
- Parallel activities with sequence
- Just-in-time processes
- Overlapping phases

**Notion Formula:**
```
if(!empty(prop("Predecessor")),
   prop("Predecessor").prop("Start Date"),
   prop("Planned Start"))
```

#### 3. Finish-to-Finish (FF)

Predecessor must FINISH before successor can FINISH (often run concurrently).

**Example:** Testing cannot finish until development finishes.

**Visual:**
```
Task A [==============]
     Task B [===========]
```

**When to Use:**
- Quality control processes
- Documentation with implementation
- Concurrent delivery requirements

#### 4. Start-to-Finish (SF) - Rare (<1%)

Predecessor must START before successor can FINISH.

**Example:** Night shift cannot end until day shift starts.

**Caution:** Rarely used and often misunderstood. Verify it's truly needed.

### Lag and Lead Time

**Lag Time (Delay):** Waiting period between dependent tasks.
```
Example: Concrete must cure for 3 days after pouring
Notion: dateAdd(prop("Predecessor").prop("End Date"), prop("Lag Days"), "days")
```

**Lead Time (Overlap):** Allow successor to start before predecessor finishes.
```
Example: Start editing when document is 80% written
Notion: dateSubtract(prop("Predecessor").prop("End Date"), prop("Lead Days"), "days")
```

### Dependency Categories

| Category | Description | Can Change? |
|----------|-------------|-------------|
| **Mandatory** | Inherent in nature of work | No |
| **Discretionary** | Based on best practices | Yes |
| **External** | Outside project control | Limited |
| **Internal** | Within project team control | Yes |

---

## Critical Path Method (CPM)

### Definition

The Critical Path Method (CPM) identifies the longest sequence of dependent tasks from start to finish. Tasks on the critical path have zero float (slack) - any delay directly impacts the project end date.

### Core Concepts

#### Float (Slack)

Amount of time a task can be delayed without affecting project completion.

**Formulas:**
```
Total Float = Latest Start - Earliest Start
           = Latest Finish - Earliest Finish

Free Float = Earliest Start (Successor) - Earliest Finish (Current) - 1
```

**Zero Float = Critical Path Task**

#### Forward Pass

Calculate earliest start/finish dates moving forward.

**Algorithm:**
```
For each task:
  If no predecessors:
    Earliest Start = Project Start Date
  Else:
    Earliest Start = MAX(Predecessor Earliest Finish) + 1

  Earliest Finish = Earliest Start + Duration - 1
```

#### Backward Pass

Calculate latest start/finish dates moving backward.

**Algorithm:**
```
For each task (in reverse):
  If no successors:
    Latest Finish = Project End Date
  Else:
    Latest Finish = MIN(Successor Latest Start) - 1

  Latest Start = Latest Finish - Duration + 1
```

### CPM Implementation in Notion

**Database Schema:**
```
Database: CPM Tasks
Properties:
  - Title (Title)
  - Duration (Number): Working days
  - Predecessors (Relation): Multi-select tasks
  - Successors (Relation): Reverse of Predecessors
  - Earliest Start (Formula): Forward pass calculation
  - Earliest Finish (Formula): ES + Duration - 1
  - Latest Start (Number): From backward pass
  - Latest Finish (Number): From backward pass
  - Total Float (Formula): LS - ES
  - Is Critical (Formula): Total Float == 0
```

**Formulas:**

**Earliest Start:**
```
if(empty(prop("Predecessors")),
   0,  // Project start
   prop("Predecessors").map(prop("Earliest Finish")).max() + 1)
```

**Is Critical:**
```
if(prop("Total Float") == 0, "🔴 Critical", "⚪ Non-Critical")
```

### Using CPM for Project Control

**1. Focus Management Attention**
- Daily status checks for critical tasks
- Allocate best resources
- Remove obstacles immediately

**2. Schedule Compression Techniques**

**Fast Tracking:** Overlap sequential critical tasks
- Change FS to SS dependencies
- Risk: Increases chance of rework

**Crashing:** Add resources to shorten duration
- Overtime, additional workers
- Risk: Increases cost

**3. Monitor Critical Path Changes**
- Critical path can shift during execution
- Recalculate CPM regularly (weekly)
- Non-critical tasks may become critical if delayed

---

## Bottleneck Analysis

### Definition

A bottleneck is any point where work piles up faster than it can be processed, causing delays throughout the workflow.

### Identification Methods

#### 1. Process Mapping & Workflow Visualization

**Visual Indicators:**
- Work accumulation at specific stages
- Long wait times before execution
- Tasks stuck in status for extended periods

**Notion Implementation:**
```
Board View:
  - Group by: Status
  - Show count in each status column
  - Color code by age

Bottleneck if: Count > threshold for extended period
```

**Bottleneck Formula:**
```
if(prop("Days in Current Status") > prop("Expected Days"),
   "🔴 Bottleneck",
   if(prop("Days in Current Status") > prop("Expected Days") * 0.8,
      "🟡 Warning",
      "🟢 Normal"))
```

#### 2. Gantt Charts and Timeline Analysis

**Look for:**
- Tasks with extended waiting periods
- Dependencies causing long chains
- Resource conflicts creating delays

**Notion Timeline Indicators:**
```
Properties:
  - Planned Start vs Actual Start
  - Planned Duration vs Actual Duration
  - Wait Time (Formula): Days between predecessor finish and actual start
```

#### 3. Kanban Board Queue Analysis

**Metrics to Track:**
- Items per status column
- Average time in each status
- Throughput rate (items completed/day)
- Arrival rate (new items/day)

**Bottleneck Rule:** If arrival rate > throughput rate, queue grows indefinitely.

#### 4. Cycle Time Analysis

**Metrics:**
- **Lead Time:** Request to delivery
- **Cycle Time:** Start work to completion
- **Queue Time:** Waiting before work starts

**Formulas:**
```
Lead Time = Queue Time + Cycle Time

Notion:
Lead Time = dateBetween(prop("Completed Date"), prop("Created Date"), "days")
Cycle Time = dateBetween(prop("Completed Date"), prop("Started Date"), "days")
Queue Time = dateBetween(prop("Started Date"), prop("Created Date"), "days")
```

**Bottleneck Indicator:** Stage with highest cycle time.

### Warning Signs of Bottlenecks

1. **Consistent Deadline Misses** - Same stage repeatedly misses deadlines
2. **Work Accumulation** - Tasks pile up at particular stage
3. **Long Wait Times** - Extended periods before tasks start
4. **Resource Overallocation** - Same resource assigned to many concurrent tasks

### Bottleneck Resolution Strategies

1. **Add Capacity** - Increase resources at bottleneck stage
2. **Reduce Demand** - Lower incoming work to bottleneck
3. **Improve Efficiency** - Streamline bottleneck process
4. **Rebalance Work** - Redistribute tasks across team
5. **Accept and Buffer** - If can't eliminate, protect it with buffer

---

## Circular Dependency Detection

### Problem Definition

Circular dependencies (dependency cycles) occur when tasks form a closed loop, making it impossible to determine valid execution order.

**Example:**
```
Task A depends on Task B
Task B depends on Task C
Task C depends on Task A
→ Circular dependency!
```

**Impact:**
- Impossible scheduling
- Testing difficulty
- Debugging complexity
- System fragility

### Detection Algorithms

#### 1. Depth-First Search (DFS) with State Tracking

Track three states during graph traversal:
- **Unvisited (White):** Not yet seen
- **Visiting (Gray):** Currently in recursion stack
- **Visited (Black):** Completely processed

**Algorithm (Python):**
```python
def has_cycle(tasks, current_task, visited, rec_stack):
    """Detect circular dependency using DFS."""
    visited.add(current_task)
    rec_stack.add(current_task)

    for dependency in tasks[current_task].predecessors:
        if dependency not in visited:
            if has_cycle(tasks, dependency, visited, rec_stack):
                return True
        elif dependency in rec_stack:
            return True  # Found cycle!

    rec_stack.remove(current_task)
    return False
```

#### 2. Topological Sort (Kahn's Algorithm)

Attempt to create linear ordering - fails if cycle exists.

**Algorithm:**
```python
def topological_sort(tasks):
    """Returns None if cycle detected."""
    in_degree = {task: 0 for task in tasks}
    for task in tasks:
        for successor in tasks[task].successors:
            in_degree[successor] += 1

    queue = [task for task in tasks if in_degree[task] == 0]
    sorted_tasks = []

    while queue:
        current = queue.pop(0)
        sorted_tasks.append(current)

        for successor in tasks[current].successors:
            in_degree[successor] -= 1
            if in_degree[successor] == 0:
                queue.append(successor)

    if len(sorted_tasks) != len(tasks):
        return None  # Cycle detected!

    return sorted_tasks
```

### Prevention Strategies

#### 1. Dependency Validation Rules

**Rule 1: No Self-Dependencies**
```
Task A cannot depend on Task A
```

**Rule 2: No Immediate Cycles**
```
If Task A depends on Task B,
then Task B cannot depend on Task A
```

**Rule 3: Transitive Dependency Check**
```
If A depends on B, and B depends on C,
then A cannot depend on C (redundant)
and C cannot depend on A (cycle)
```

#### 2. Hierarchical Dependency Rules

Only allow dependencies within same level or to higher levels:
```
Level 1 tasks can depend on: Level 1 or Level 0
Level 2 tasks can depend on: Level 2, Level 1, or Level 0

Prohibited: Level 1 depending on Level 2
```

#### 3. Acyclic Graph Policy

Maintain task graph as Directed Acyclic Graph (DAG):
- Run cycle detection before saving new dependencies
- Reject dependency creation if cycle would form
- Provide alternative suggestions

### Circular Dependency Resolution

If cycle detected, resolve using:

**1. Remove Redundant Dependencies**
```
Before (cycle): A → B → C → A
After: A → B → C (linear)
```

**2. Split Tasks**
```
Before: Task A depends on Task B, Task B depends on Task A
After: Task A.1 → Task B.1 → Task A.2 → Task B.2
```

**3. Introduce Iteration**
```
Before (cycle): Design → Review → Design
After: Iteration 1: Design 1.0 → Review 1.0
       Iteration 2: Design 2.0 → Review 2.0
```

**4. Redefine Dependencies**
```
Before: UI depends on API spec, API depends on UI design
After: UI Mockup → API Spec → API Impl → UI Impl
```

---

## Notion Dependency Dashboard

**Components:**

1. **Critical Path Gantt (Timeline view)**
   - Group by: Critical Path Group
   - Color code: Red for Critical, Gray for Non-Critical
   - Show dependency lines

2. **Critical Task List (Table)**
   - Filter: Is Critical = True
   - Sort by: Earliest Start ascending

3. **Bottleneck Analysis (Board)**
   - Group by: Status
   - Show count and average age per status
   - Alert if count > threshold

4. **Float Analysis (Table)**
   - Show: Task, Total Float, Free Float
   - Sort by: Total Float ascending
   - Filter: Float < 3 days (near-critical)

5. **Dependency Matrix (Table)**
   - Show: From Task, To Task, Type, Lag
   - Filter: Dependency Type (for specific analysis)

6. **Cycle Detection Status**
   - Last scan date
   - Cycles found count
   - Resolution status

---

## Validation Checklist

Before finalizing dependencies:
- ✅ All dependencies have valid type (FS, SS, FF, SF)
- ✅ No self-dependencies
- ✅ No circular dependencies (run DFS check)
- ✅ All predecessor tasks exist
- ✅ Lag/lead times are realistic
- ✅ Critical path is identified
- ✅ Bottlenecks are documented
- ✅ Resource conflicts resolved

---

## References

- **Project Management Institute:** Critical Path Method (CPM)
- **Wrike:** "What is the Critical Path Method?"
- **Lucidchart:** "PERT vs. CPM: What's the Difference?"
- **Wikipedia:** Topological Sorting, Directed Acyclic Graph

---

**Last Updated:** 2025-01-10
**Version:** 1.0.0
