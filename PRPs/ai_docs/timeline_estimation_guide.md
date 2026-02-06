# Timeline Estimation Guide for Automation Projects

**Purpose:** Comprehensive guide to effort estimation, timeline planning, buffer management, and velocity-based forecasting.

**Audience:** AI agents (especially timeline-estimator subagent), project planners.

---

## Table of Contents

1. [Three-Point Estimation Method](#three-point-estimation-method)
2. [PERT (Program Evaluation and Review Technique)](#pert-program-evaluation-and-review-technique)
3. [Buffer Planning Strategies](#buffer-planning-strategies)
4. [Velocity-Based Forecasting](#velocity-based-forecasting)

---

## Three-Point Estimation Method

### Overview

Three-point estimation accounts for uncertainty by using three estimates instead of one:
1. **Optimistic (O):** Best-case scenario (everything goes perfectly)
2. **Most Likely (M):** Realistic scenario (normal conditions)
3. **Pessimistic (P):** Worst-case scenario (everything goes wrong)

### Estimation Formulas

#### Simple Average (Triangular Distribution)

All three estimates weighted equally.

```
Expected Duration (TE) = (O + M + P) / 3
```

**When to Use:** Equal likelihood of all scenarios, low complexity tasks.

**Example:**
```
Task: Implement user login
Optimistic: 2 days
Most Likely: 4 days
Pessimistic: 8 days

Expected = (2 + 4 + 8) / 3 = 4.67 ≈ 5 days
```

#### Weighted Average (Beta/PERT Distribution)

Most Likely estimate weighted 4x more heavily.

```
Expected Duration (TE) = (O + 4M + P) / 6
```

**When to Use:** Most Likely scenario is most probable (normal distribution).

**Example:**
```
Task: Implement user login
Optimistic: 2 days
Most Likely: 4 days
Pessimistic: 8 days

Expected = (2 + 4×4 + 8) / 6 = 26/6 = 4.33 ≈ 4 days
```

### Standard Deviation and Confidence

#### Standard Deviation (σ)

Measures variability/uncertainty in estimate.

```
σ = (P - O) / 6
```

**Interpretation:**
- Small σ → Low uncertainty, high confidence
- Large σ → High uncertainty, low confidence

**Example:**
```
Optimistic: 2 days, Pessimistic: 8 days
σ = (8 - 2) / 6 = 1 day
```

#### Confidence Intervals

Based on normal distribution:

| Confidence Level | Range | Formula |
|------------------|-------|---------|
| 68.3% (1σ) | ±1 standard deviation | TE ± σ |
| 95.4% (2σ) | ±2 standard deviations | TE ± 2σ |
| 99.7% (3σ) | ±3 standard deviations | TE ± 3σ |

**Example:**
```
Expected Duration (TE) = 4.33 days
Standard Deviation (σ) = 1 day

68.3% confidence: 4.33 ± 1 = 3.33 to 5.33 days
95.4% confidence: 4.33 ± 2 = 2.33 to 6.33 days

Interpretation: 95% confident task will take 2-6 days
```

### Notion Implementation

**Database Schema:**
```
Database: Tasks with Three-Point Estimates
Properties:
  - Title (Title)
  - Optimistic Days (Number)
  - Most Likely Days (Number)
  - Pessimistic Days (Number)
  - Expected Duration PERT (Formula): (O + 4M + P) / 6
  - Standard Deviation (Formula): (P - O) / 6
  - Confidence 95% Low (Formula): TE - 2σ
  - Confidence 95% High (Formula): TE + 2σ
  - Uncertainty Level (Formula): σ categorization
```

**Formulas:**

**Expected Duration (PERT):**
```
round((prop("Optimistic Days") + 4 * prop("Most Likely Days") + prop("Pessimistic Days")) / 6 * 100) / 100
```

**Standard Deviation:**
```
round((prop("Pessimistic Days") - prop("Optimistic Days")) / 6 * 100) / 100
```

**Uncertainty Level:**
```
if(prop("Standard Deviation") < 0.5, "🟢 Low",
   if(prop("Standard Deviation") < 1.5, "🟡 Medium",
      "🔴 High"))
```

### Best Practices

#### 1. Define Scenarios Clearly

**Optimistic:** Everything goes perfectly
- No blockers, resources available, no rework

**Most Likely:** What usually happens
- Normal blockers, typical resources, some minor rework

**Pessimistic:** Things go wrong
- Major blockers, resource constraints, significant rework

#### 2. Use Historical Data

Review similar past tasks:
- Fastest completion → Informs Optimistic
- Average completion → Informs Most Likely
- Slowest completion → Informs Pessimistic

#### 3. Involve Team in Estimation

Use techniques like:
- **Planning Poker:** Independent estimates, then discuss
- **Delphi Method:** Anonymous rounds with feedback
- **Wide-band Delphi:** Combine poker with group discussion

#### 4. Document Assumptions

Record what assumptions underlie each estimate.

#### 5. Update Based on Actuals

Track actual vs estimated to improve future estimates:
```
Properties:
  - Estimated Duration (Number)
  - Actual Duration (Number)
  - Variance (Formula): Actual - Estimated
  - Variance % (Formula): (Variance / Estimated) * 100
```

---

## PERT (Program Evaluation and Review Technique)

### Overview

PERT combines three-point estimation with network analysis to manage uncertainty in complex projects.

### PERT vs CPM

| Aspect | PERT | CPM |
|--------|------|-----|
| **Focus** | Time uncertainty | Resource optimization |
| **Estimates** | Three-point (O, M, P) | Single-point |
| **Best For** | R&D, unknown territories | Construction, repetitive work |
| **Durations** | Probabilistic | Deterministic |
| **Primary Goal** | Estimate completion time | Find critical path |

### PERT Process

#### Step 1: Identify Activities

List all tasks with three-point estimates and dependencies.

#### Step 2: Calculate Expected Durations

Use PERT formula for each task:
```
TE = (O + 4M + P) / 6
σ = (P - O) / 6
```

#### Step 3: Build PERT Network

Create network diagram showing tasks, dependencies, and expected durations.

#### Step 4: Calculate Project Duration

**Approach A: Sum Critical Path**
```
Project Duration = Sum of TE for all critical path tasks
```

**Approach B: Probabilistic**
```
Project Duration (Expected) = Sum of TE for critical path
Project σ = sqrt(Sum of σ² for critical path tasks)
```

#### Step 5: Calculate Probability

Determine probability of completing by deadline using Z-score.

**Z-Score Formula:**
```
Z = (Deadline - Expected Duration) / Project σ
```

**Example:**
```
Critical Path Tasks:
  Task A: TE = 5 days, σ = 1
  Task B: TE = 10 days, σ = 2
  Task C: TE = 3 days, σ = 0.5

Project Expected Duration = 5 + 10 + 3 = 18 days
Project σ = sqrt(1² + 2² + 0.5²) = sqrt(5.25) = 2.29 days

Deadline: 20 days

Z = (20 - 18) / 2.29 = 0.87

From Z-table: 0.87 ≈ 80.8% probability

Interpretation: 80.8% chance of completing by day 20
```

### Z-Score to Probability Reference

| Z-Score | Probability of Meeting Deadline |
|---------|--------------------------------|
| -3.0 | 0.1% (virtually impossible) |
| -2.0 | 2.3% (very unlikely) |
| -1.0 | 15.9% (unlikely) |
| 0.0 | 50.0% (coin flip) |
| +1.0 | 84.1% (likely) |
| +2.0 | 97.7% (very likely) |
| +3.0 | 99.9% (virtually certain) |

**Rule of Thumb:**
- Z > 0: Better than 50% chance
- Z > 1: Good chance (>84%)
- Z > 2: Excellent chance (>97%)
- Z < 0: Less than 50% chance (risky)

### Notion PERT Implementation

**Database Schema:**
```
Database: PERT Analysis
Properties:
  - Task (Relation): Link to Tasks
  - Optimistic (Number)
  - Most Likely (Number)
  - Pessimistic (Number)
  - Expected Duration (Formula): (O + 4M + P) / 6
  - Variance (Formula): ((P - O) / 6)²
  - Is Critical Path (Checkbox)
  - Critical Path Order (Number)

Project-Level:
  - Project Expected Duration (Rollup): Sum of Expected Duration
  - Project Variance (Rollup): Sum of Variance
  - Project Std Dev (Formula): sqrt(Project Variance)
  - Target Deadline (Number)
  - Z-Score (Formula): (Deadline - Expected) / Std Dev
```

---

## Buffer Planning Strategies

### Critical Chain Method Overview

Critical Chain Project Management (CCPM):
- Focuses on resource constraints
- Removes safety margins from individual tasks
- Aggregates buffers at strategic points
- Monitors buffer consumption

### Types of Buffers

#### 1. Project Buffer

Placed at end of critical chain to protect project deadline.

**Sizing Methods:**

**Method A: 50% of Removed Safety**
```
Project Buffer = 50% of (Sum of safety removed)

Example:
  Task A: 8 days → 4 days (4 days safety removed)
  Task B: 6 days → 3 days (3 days safety removed)
  Task C: 10 days → 5 days (5 days safety removed)

  Total safety removed = 12 days
  Project Buffer = 50% × 12 = 6 days
```

**Method B: Root Square Error Method (RSEM)**
```
Project Buffer = sqrt(Sum of (task durations)²) / 2

Example:
  Critical Chain Tasks: 4, 3, 5 days
  Project Buffer = sqrt(4² + 3² + 5²) / 2 = sqrt(50) / 2 = 3.5 days
```

**Method C: Percentage of Critical Chain**
```
Project Buffer = 25-50% of critical chain duration

Example:
  Critical Chain = 20 days
  Project Buffer = 30% × 20 = 6 days
```

#### 2. Feeding Buffer

Placed where non-critical chains feed into critical chain.

**Sizing:**
```
Feeding Buffer = 50% of feeding chain duration
```

**Example:**
```
Non-Critical Chain: Task X (3 days) + Task Y (5 days) = 8 days
Feeding Buffer = 50% × 8 = 4 days
```

#### 3. Resource Buffer

Alert/warning before critical task requiring specific resource.

**Not a time buffer** - it's a notification mechanism.

**Implementation:**
```
Properties:
  - Is Critical Task (Checkbox)
  - Required Resource (Person)
  - Resource Buffer Days (Number): Alert lead time
  - Resource Alert Date (Formula): Start Date - Buffer Days
```

### Buffer Management

#### Buffer Consumption Monitoring

**Buffer Status Zones:**

| Zone | Buffer Consumed | Action Required |
|------|----------------|-----------------|
| 🟢 Green | 0-33% | No action |
| 🟡 Yellow | 34-66% | Monitor closely |
| 🔴 Red | 67-100% | Immediate action |

**Buffer Health Formula:**
```
If % Buffer Consumed < % Complete: Ahead of plan (Green)
If % Buffer Consumed ≈ % Complete: On plan (Yellow)
If % Buffer Consumed > % Complete: Behind plan (Red)
```

**Notion Formula:**
```
let consumed = prop("Buffer Consumed %")
let complete = prop("Project Complete %")
let ratio = consumed / complete

if(ratio < 0.8, "🟢 Ahead",
   if(ratio < 1.2, "🟡 On Track",
      "🔴 Behind"))
```

#### Buffer Recovery Actions

**Yellow Zone:**
1. Root cause analysis
2. Mitigation strategies (fast-track, add resources)
3. Update stakeholders

**Red Zone:**
1. Emergency measures (crash critical path, overtime)
2. Replanning (extend deadline, renegotiate scope)
3. Lessons learned

### Buffer Sizing Guidelines

**Factors Affecting Buffer Size:**
1. **Project Complexity** - High complexity → Larger buffers (40-50%)
2. **Team Experience** - Inexperienced → Larger buffers
3. **Technology Maturity** - New tech → Larger buffers
4. **Risk Level** - High risk → Larger buffers

**Optimal Sizing:**
- **Too small:** Frequent depletion, crisis mode
- **Too large:** Uncompetitive, wasted time
- **Just right:** Absorbs normal variation, rarely depleted

**Calibration:**
- Start with 30% buffers
- Track actual consumption
- Adjust based on data (±5-10%)

---

## Velocity-Based Forecasting

### Overview

Velocity-based forecasting uses historical team performance to predict future delivery dates. Primarily used in Agile/Scrum but applicable to any iterative project.

### Key Concepts

#### Velocity

Amount of work a team completes in a fixed time period (sprint).

**Measurement Units:**
- Story points (most common)
- Task count
- Ideal days/hours
- Features delivered

**Example:**
```
Sprint 1: 25 story points
Sprint 2: 30 story points
Sprint 3: 28 story points

Average Velocity = (25 + 30 + 28) / 3 = 27.67 ≈ 28 points/sprint
```

#### Velocity Stabilization

Teams need 3-5 sprints to establish reliable velocity baseline.

**Notion Tracking:**
```
Database: Sprint History
Properties:
  - Sprint Number (Number)
  - Completed Points (Number)
  - Team Size (Number)
  - Velocity Per Person (Formula): Velocity / Team Size

Metrics:
  - Average Velocity (Rollup): Average of last 3-5 sprints
  - Velocity Std Dev (Rollup)
  - Velocity Stability (Formula): CV < 15% = Stable
```

### Forecasting Methods

#### Method 1: Single-Point Velocity

Use average velocity to forecast.

```
Remaining Sprints = Remaining Work / Average Velocity
Expected Completion = Today + (Remaining Sprints × Sprint Length)
```

**Example:**
```
Backlog: 200 story points
Average Velocity: 25 points/sprint
Sprint Length: 2 weeks

Remaining Sprints = 200 / 25 = 8 sprints
Expected Completion = Today + 16 weeks
```

#### Method 2: Velocity Range

Use velocity range for confidence intervals.

```
Best Case = Remaining Work / High Velocity
Worst Case = Remaining Work / Low Velocity
Most Likely = Remaining Work / Average Velocity
```

**Example:**
```
Remaining: 200 points
Velocity Range: 20-30 points
Average: 25 points

Best Case: 200 / 30 = 7 sprints = 14 weeks
Most Likely: 200 / 25 = 8 sprints = 16 weeks
Worst Case: 200 / 20 = 10 sprints = 20 weeks

Forecast: "14-20 weeks, most likely 16 weeks"
```

#### Method 3: Yesterday's Weather

Use last sprint's velocity to plan next sprint.

```
Next Sprint Capacity = Last Sprint Velocity
```

**Advantages:**
- Simple and transparent
- Self-correcting
- Prevents over-commitment

#### Method 4: Three-Point Velocity Forecast

Apply three-point estimation to velocity.

```
Optimistic Velocity = Historical Max
Most Likely Velocity = Average Velocity
Pessimistic Velocity = Historical Min

Expected Velocity = (O + 4M + P) / 6
Forecast = Remaining Work / Expected Velocity
```

### Factors Affecting Velocity

1. **Team Composition Changes**
   - New members: Temporary velocity drop (20% in sprint 1)
   - Adjustment period: 2-3 sprints to return to baseline

2. **Technical Debt**
   - More time on bugs/refactoring → Less for features
   - Track debt ratio: (Bugs + Refactor) / Capacity

3. **External Dependencies**
   - Blocked stories don't count toward velocity
   - Build buffer for external dependencies

4. **Sprint Length**
   - Shorter sprints: Lower velocity (fixed overhead)
   - Normalize: Velocity per week for comparison

### Velocity Best Practices

1. **Never use velocity for performance reviews** - Teams will game the system
2. **Use velocity ranges, not single numbers** - Communicates uncertainty
3. **Recalculate regularly** - Update after each sprint (sliding window)
4. **Normalize for team changes** - Adjust for team size changes
5. **Account for holidays/PTO** - Adjust capacity for reduced availability

**Capacity Adjustment:**
```
Adjusted Capacity = Base Velocity × (Available Person-Days / Normal Person-Days)

Example:
  Base Velocity: 30 points
  Team: 6 people, 10-day sprint = 60 person-days
  Holiday: 2 days off for everyone = 48 person-days

  Adjusted Capacity = 30 × (48/60) = 24 points
```

---

## Notion Timeline Dashboard

**Components:**

1. **Three-Point Estimates Table**
   - Show: Task, O, M, P, Expected, σ, Uncertainty Level
   - Sort by: Expected Duration descending

2. **PERT Analysis Summary**
   - Project Expected Duration
   - Project Standard Deviation
   - Target Deadline
   - Z-Score
   - Completion Probability

3. **Buffer Status**
   - Project Buffer: Total, Consumed, Remaining, Health
   - Feeding Buffers: List with status
   - Buffer Consumption Chart

4. **Velocity Tracking**
   - Sprint History Chart
   - Average Velocity
   - Velocity Range (min-max)
   - Stability Rating

5. **Forecast Calculator**
   - Input: Remaining work
   - Output: Best/Likely/Worst case completion

---

## Validation Checklist

Before finalizing timeline:
- ✅ All tasks have three-point estimates
- ✅ Estimates are realistic (involve team)
- ✅ Historical data considered
- ✅ Critical path identified
- ✅ Buffers appropriately sized
- ✅ Resource availability accounted for
- ✅ Dependencies factored into schedule
- ✅ Milestones align with timeline

---

## References

- **Project Management Institute:** PERT Technique
- **Critical Chain Project Management:** Eliyahu M. Goldratt
- **Agile Estimating and Planning:** Mike Cohn
- **Scrum Guide:** Velocity and Forecasting

---

**Last Updated:** 2025-01-10
**Version:** 1.0.0
