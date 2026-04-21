# Automation Project PRP: {PROJECT_NAME}

**Generated:** {GENERATION_DATE}
**Project Component:** {COMPONENT_NAME}
**Overall Initiative:** {OVERALL_PROJECT}

---

## 📋 Executive Summary

### Project Overview
{HIGH_LEVEL_DESCRIPTION}

### Key Objectives
{LIST_OF_MAIN_OBJECTIVES}

### Success Criteria
{MEASURABLE_SUCCESS_CRITERIA}

### Estimated Effort
- **Timeline:** {START_DATE} to {END_DATE} ({TOTAL_DURATION})
- **Team Size:** {TEAM_SIZE} people
- **Total Effort:** {TOTAL_HOURS} hours
- **Critical Path:** {CRITICAL_PATH_DURATION} days

---

## 🏗️ Project Structure

### Hierarchical Breakdown

```
{PROJECT_NAME}
{WBS_STRUCTURE_TREE}
```

### Work Breakdown Structure (WBS)

#### WBS Dictionary

{FOR_EACH_WBS_ELEMENT}
**{WBS_CODE} - {ELEMENT_NAME}**
- **Description:** {DESCRIPTION}
- **Deliverable:** {DELIVERABLE}
- **Acceptance Criteria:** {ACCEPTANCE_CRITERIA}
- **Assigned To:** {RESOURCE}
- **Level:** {LEVEL}
{END_FOR_EACH}

---

## 📦 Detailed Task Breakdown

### Subproject: {SUBPROJECT_1_NAME}

#### Overview
{SUBPROJECT_DESCRIPTION}

#### Tasks

##### Task {TASK_ID}: {TASK_NAME}

**WBS Code:** {WBS_CODE}

**Description:**
{DETAILED_TASK_DESCRIPTION}

**Acceptance Criteria:**
- {CRITERION_1}
- {CRITERION_2}
- {CRITERION_3}

**Estimates:**
- **Optimistic:** {O_DAYS} days
- **Most Likely:** {M_DAYS} days
- **Pessimistic:** {P_DAYS} days
- **Expected (PERT):** {EXPECTED_DAYS} days
- **Standard Deviation:** {STD_DEV} days
- **Confidence 95%:** {CONFIDENCE_RANGE} days

**Dependencies:**
- **Predecessors:** {PREDECESSOR_TASKS} ({DEPENDENCY_TYPE})
- **Successors:** {SUCCESSOR_TASKS}

**Resources:**
- **Assigned To:** {PRIMARY_RESOURCE}
- **Supporting:** {SUPPORTING_RESOURCES}
- **Skills Required:** {REQUIRED_SKILLS}

**Technical Details:**
{TECHNICAL_IMPLEMENTATION_NOTES}

**Risks:**
- {RISK_1}: Mitigation: {MITIGATION_1}
- {RISK_2}: Mitigation: {MITIGATION_2}

**Notes:**
{ADDITIONAL_NOTES}

---

{REPEAT_FOR_ALL_TASKS}

---

## 🔗 Dependency Graph

### Dependency Matrix

| From Task | To Task | Type | Lag (days) | Category |
|-----------|---------|------|------------|----------|
{DEPENDENCY_ROWS}

### Dependency Visualization

```
{ASCII_OR_DESCRIPTION_OF_DEPENDENCY_GRAPH}
```

### Critical Path Analysis

**Critical Path Tasks:**
{LIST_CRITICAL_PATH_TASKS}

**Total Critical Path Duration:** {CRITICAL_PATH_DAYS} days

**Float Analysis:**
| Task | Total Float | Free Float | Critical? |
|------|-------------|------------|-----------|
{FLOAT_ANALYSIS_ROWS}

### Bottleneck Analysis

**Identified Bottlenecks:**
{LIST_BOTTLENECKS_WITH_ANALYSIS}

**Mitigation Strategies:**
{BOTTLENECK_MITIGATION_PLANS}

---

## ⏱️ Timeline & Schedule

### Project Timeline

**Start Date:** {PROJECT_START}
**End Date:** {PROJECT_END}
**Total Duration:** {TOTAL_DAYS} working days

### Milestone Schedule

| Milestone | Target Date | Deliverables | Status |
|-----------|-------------|--------------|--------|
{MILESTONE_ROWS}

### Detailed Schedule (Gantt Format)

```
{GANTT_CHART_REPRESENTATION}
```

### Phase Breakdown

#### Phase 1: {PHASE_NAME}
- **Duration:** {PHASE_DURATION}
- **Tasks:** {PHASE_TASKS}
- **Deliverables:** {PHASE_DELIVERABLES}

{REPEAT_FOR_ALL_PHASES}

### Buffer Planning

**Project Buffer:**
- **Size:** {BUFFER_DAYS} days ({BUFFER_PERCENTAGE}% of critical path)
- **Method:** {BUFFER_SIZING_METHOD}
- **Consumption Threshold:**
  - 🟢 Green: 0-33% consumed
  - 🟡 Yellow: 34-66% consumed
  - 🔴 Red: 67-100% consumed

**Feeding Buffers:**
{LIST_FEEDING_BUFFERS_WITH_SIZES}

**Resource Buffers:**
{LIST_RESOURCE_BUFFER_ALERTS}

---

## 👥 Resource Plan

### Team Composition

| Role | Count | Names | Allocation % |
|------|-------|-------|--------------|
{TEAM_COMPOSITION_ROWS}

### Resource Allocation by Phase

#### Phase 1: {PHASE_NAME}
| Resource | Tasks | Hours | Utilization % |
|----------|-------|-------|---------------|
{RESOURCE_ALLOCATION_ROWS}

{REPEAT_FOR_ALL_PHASES}

### Skills Matrix

| Skill | Required Level | Available Resources | Gap |
|-------|----------------|---------------------|-----|
{SKILLS_MATRIX_ROWS}

### Resource Leveling

**Over-allocated Resources:**
{LIST_OVERALLOCATED_RESOURCES}

**Leveling Recommendations:**
{RESOURCE_LEVELING_SUGGESTIONS}

---

## 🎯 Risk Management

### Risk Register

#### Risk #{RISK_ID}: {RISK_NAME}

**Category:** {RISK_CATEGORY}
**Probability:** {PROBABILITY} (Low/Medium/High)
**Impact:** {IMPACT} (Low/Medium/High)
**Risk Score:** {RISK_SCORE} (Probability × Impact)
**Status:** {STATUS}

**Description:**
{RISK_DESCRIPTION}

**Mitigation Strategy:**
{MITIGATION_STRATEGY}

**Contingency Plan:**
{CONTINGENCY_PLAN}

**Owner:** {RISK_OWNER}

---

{REPEAT_FOR_ALL_RISKS}

### Risk Summary

**Risk Heat Map:**
```
High Impact    | R3, R7  | R1, R4  | R2     |
Medium Impact  | R9      | R5, R8  | R6     |
Low Impact     |         | R10     |        |
               Low Prob   Medium    High Prob
```

**Top 5 Risks by Score:**
{TOP_RISKS_LIST}

---

## 🔬 Technical Research Findings

### Technology Stack Analysis

#### {TECHNOLOGY_1}

**Purpose:** {WHY_USING_THIS_TECH}

**Advantages:**
- {ADVANTAGE_1}
- {ADVANTAGE_2}
- {ADVANTAGE_3}

**Disadvantages / Gotchas:**
- {GOTCHA_1}: {WORKAROUND}
- {GOTCHA_2}: {WORKAROUND}

**Integration Patterns:**
{INTEGRATION_APPROACH}

**References:**
- {DOCUMENTATION_LINK_1}
- {DOCUMENTATION_LINK_2}

---

{REPEAT_FOR_ALL_TECHNOLOGIES}

### Architecture Decisions

#### ADR #{NUMBER}: {DECISION_TITLE}

**Status:** {PROPOSED/ACCEPTED/DEPRECATED}
**Date:** {DECISION_DATE}

**Context:**
{WHAT_SITUATION_LED_TO_THIS_DECISION}

**Decision:**
{WHAT_WAS_DECIDED}

**Consequences:**
- **Positive:** {POSITIVE_CONSEQUENCES}
- **Negative:** {NEGATIVE_CONSEQUENCES}

---

{REPEAT_FOR_ALL_ADRS}

---

## 📊 Notion Integration Plan

### Database Structure

#### Projects Database

**Database Name:** {PROJECTS_DB_NAME}
**Database ID:** {WILL_BE_CREATED}

**Properties:**
```json
{
  "Name": {"type": "title"},
  "Status": {"type": "select", "options": ["Planung", "In Arbeit", "Review", "Fertig", "Blockiert"]},
  "Priority": {"type": "select", "options": ["Critical", "High", "Medium", "Low"]},
  "Start Date": {"type": "date"},
  "End Date": {"type": "date"},
  "Progress": {"type": "number", "format": "percent"},
  "Owner": {"type": "person"},
  "Description": {"type": "rich_text"},
  "Parent Project": {"type": "relation", "database": "Projects"},
  "Sub Projects": {"type": "relation", "database": "Projects"},
  "Tasks": {"type": "relation", "database": "Tasks"},
  "Risk Level": {"type": "select", "options": ["Low", "Medium", "High", "Critical"]}
}
```

#### Tasks Database

**Database Name:** {TASKS_DB_NAME}
**Database ID:** {WILL_BE_CREATED}

**Properties:**
```json
{
  "Name": {"type": "title"},
  "Project": {"type": "relation", "database": "Projects"},
  "Status": {"type": "select", "options": ["Todo", "In Progress", "Review", "Done", "Blocked"]},
  "Priority": {"type": "select", "options": ["Critical", "High", "Medium", "Low"]},
  "Assigned To": {"type": "person"},
  "Start Date": {"type": "date"},
  "Due Date": {"type": "date"},
  "Estimated Hours": {"type": "number"},
  "Actual Hours": {"type": "number"},
  "Description": {"type": "rich_text"},
  "Dependencies": {"type": "relation", "database": "Tasks"},
  "Dependents": {"type": "relation", "database": "Tasks"},
  "Complexity": {"type": "select", "options": ["Simple", "Medium", "Complex", "Very Complex"]},
  "Category": {"type": "select", "options": ["Research", "Development", "Testing", "Documentation", "Deployment"]}
}
```

### Creation Sequence

**Step 1: Create Main Project**
```
mcp__notion__create_page(
  database_id: projects_db,
  properties: {
    "Name": "{PROJECT_NAME}",
    "Status": "Planung",
    "Priority": "{PRIORITY}",
    "Start Date": "{START_DATE}",
    "End Date": "{END_DATE}",
    "Risk Level": "{RISK_LEVEL}"
  }
)
```

**Step 2: Create Subprojects**
{LIST_SUBPROJECT_CREATION_CALLS}

**Step 3: Create Tasks**
{LIST_TASK_CREATION_CALLS}

**Step 4: Setup Dependencies**
{LIST_DEPENDENCY_RELATION_CALLS}

**Step 5: Add Descriptions**
{LIST_CONTENT_ADDITION_CALLS}

### Views to Create

**Timeline View (Gantt):**
- Group by: Project
- Show: All tasks
- Dependencies: Enabled

**Kanban Board:**
- Group by: Status
- Filter: Current sprint tasks

**Table View:**
- Show: All properties
- Sort by: Priority (desc), Due Date (asc)

---

## ✅ Validation & Testing Plan

### Validation Gates

**Gate 1: Structure Validation**
- [ ] All WBS elements have clear acceptance criteria
- [ ] All tasks have assignments
- [ ] All dependencies are valid (no cycles)
- [ ] Task estimates are realistic (8-80 hours)

**Gate 2: Timeline Validation**
- [ ] Critical path identified correctly
- [ ] Schedule fits within deadline
- [ ] Buffers are appropriately sized
- [ ] Milestones align with phases

**Gate 3: Resource Validation**
- [ ] No resource over-allocated (>100%)
- [ ] Required skills available in team
- [ ] External dependencies have lead time buffers

**Gate 4: Notion Integration Validation**
- [ ] All database schemas defined
- [ ] All pages created successfully
- [ ] All relations established correctly
- [ ] Timeline view displays properly
- [ ] Progress tracking functional

### Testing Strategy

**Unit Testing:**
{UNIT_TEST_APPROACH}

**Integration Testing:**
{INTEGRATION_TEST_APPROACH}

**System Testing:**
{SYSTEM_TEST_APPROACH}

**Acceptance Testing:**
{ACCEPTANCE_TEST_APPROACH}

---

## 📈 Progress Tracking

### KPIs & Metrics

| Metric | Target | Current | Status |
|--------|--------|---------|--------|
| Tasks Completed | {TARGET}% | {CURRENT}% | {STATUS} |
| On-Time Delivery | {TARGET}% | {CURRENT}% | {STATUS} |
| Budget Utilization | {TARGET}% | {CURRENT}% | {STATUS} |
| Buffer Consumption | <33% | {CURRENT}% | {STATUS} |
| Velocity | {TARGET} pts/sprint | {CURRENT} | {STATUS} |

### Reporting Schedule

- **Daily Standups:** Task status, blockers
- **Weekly Status Reports:** Progress, risks, issues
- **Bi-Weekly Reviews:** Demo, retrospective
- **Monthly Stakeholder Updates:** High-level progress, major decisions

---

## 🎓 Lessons Learned & Best Practices

### Key Learnings from Similar Projects

{RELEVANT_LESSONS_FROM_HISTORY}

### Recommended Approaches

{BEST_PRACTICES_FOR_THIS_PROJECT}

### Common Pitfalls to Avoid

{KNOWN_GOTCHAS_AND_HOW_TO_AVOID}

---

## 📚 References & Documentation

### External Documentation
{LIST_OF_REFERENCE_DOCS}

### Internal Resources
{LIST_OF_INTERNAL_DOCS}

### Tools & Templates
{LIST_OF_TOOLS_AND_TEMPLATES}

---

## 🚀 Next Steps

### Immediate Actions
1. {ACTION_1}
2. {ACTION_2}
3. {ACTION_3}

### Pre-Kickoff Checklist
- [ ] Team assembled and briefed
- [ ] Notion workspace configured
- [ ] Development environment setup
- [ ] Access to required tools and services
- [ ] Initial backlog groomed
- [ ] Sprint 1 planned

### Kickoff Meeting Agenda
1. Project overview and objectives
2. Team introductions and roles
3. Technical architecture walkthrough
4. Timeline and milestones review
5. Communication and reporting protocols
6. Q&A

---

**Generated by:** Claude Code Automation Project Planner
**Subagents Used:** project-manager, technical-researcher, dependency-analyzer, timeline-estimator
**Confidence Level:** {CONFIDENCE_SCORE}/10

---

## Appendix A: Complete Task List

{COMPREHENSIVE_FLAT_LIST_OF_ALL_TASKS}

## Appendix B: Dependency List

{COMPREHENSIVE_LIST_OF_ALL_DEPENDENCIES}

## Appendix C: Resource Calendar

{RESOURCE_ALLOCATION_CALENDAR}

## Appendix D: Risk Details

{EXTENDED_RISK_INFORMATION}
