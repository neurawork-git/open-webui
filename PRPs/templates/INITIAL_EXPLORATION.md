# INITIAL: {Codebase Name} Exploration

> Template for creating exploration plans for large open-source codebases.
> Delete this instruction block after filling in.

## EXPLORATION GOALS

What do you want to understand? Be specific about your end goals.

- [ ] Understand the overall architecture and design patterns
- [ ] Learn how {specific_feature} is implemented
- [ ] Identify extension points for {planned_addition}
- [ ] Understand the data model and storage approach
- [ ] Map the API surface and integration points
- [ ] Learn the testing and development workflow

**Primary Goal:**
{One sentence describing your main objective}

**Success Criteria:**
- I can explain how {component} works to someone else
- I know where to add code for {feature}
- I understand the {pattern} used for {purpose}

## FOCUS AREAS

Specific modules, features, or areas to explore in depth.

### High Priority
1. **{Module/Feature Name}**
   - Why: {reason for interest}
   - Questions: {specific questions}
   - Related files (if known): {files}

2. **{Module/Feature Name}**
   - Why: {reason}
   - Questions: {questions}

### Medium Priority
3. **{Area}** - {brief reason}
4. **{Area}** - {brief reason}

### Low Priority (if time permits)
5. **{Area}** - {brief reason}

## KNOWN CONTEXT

What you already know about the codebase (helps avoid redundant exploration).

### From Documentation
- {fact_1}
- {fact_2}

### From Previous Experience
- {similar_project_experience}
- {framework_familiarity}

### From Initial Browsing
- {observation_1}
- {observation_2}

### Serena Memories (if onboarded)
- tech_stack.md: {summary}
- codebase_structure.md: {summary}

## QUESTIONS TO ANSWER

Specific technical questions you need answered. These drive exploration.

### Architecture Questions
1. How is the application structured? (monolith, microservices, modular?)
2. What design patterns are used? (MVC, repository, CQRS?)
3. How does data flow from {input} to {output}?

### Implementation Questions
4. How is {feature} implemented?
5. Where is {functionality} handled?
6. What is the lifecycle of {entity}?

### Integration Questions
7. How do {component_a} and {component_b} communicate?
8. How are external services integrated?
9. What events/hooks are available?

### Development Questions
10. How do I run tests for {area}?
11. What's the development workflow?
12. How do I add a new {feature_type}?

## TARGET ADDITIONS

Features or modifications you're planning (helps focus exploration).

### Planned Feature: {Feature Name}
- **Description:** {what it does}
- **Integration Points:** {where it connects}
- **Modules to Understand:** {relevant modules}
- **Similar Existing Feature:** {if any}

### Alternative Approaches to Evaluate
- Option A: {approach}
- Option B: {approach}
- Need to understand: {what determines choice}

## CONSTRAINTS & PREFERENCES

Any constraints on the exploration process.

### Time Budget
- Available time: {hours/days}
- Priority: Depth vs Breadth (choose one)

### Output Preferences
- [ ] Create detailed Serena memories for each module
- [ ] Create Notion documentation
- [ ] Just update Archon tasks with findings
- [ ] Create architecture diagrams (text-based)

### Exploration Style
- [ ] Follow the code path (trace execution)
- [ ] Start from entry points and work inward
- [ ] Focus on tests to understand behavior
- [ ] Read documentation first, then code

---

## Example (Delete this section after reading)

```markdown
# INITIAL: Open WebUI Exploration

## EXPLORATION GOALS
- Understand how the chat interface works with different LLM providers
- Learn the plugin/extension architecture
- Identify where to add custom authentication

**Primary Goal:**
Understand enough to add a custom SSO provider.

**Success Criteria:**
- I can explain the auth flow to someone else
- I know where to add my SSO integration code
- I understand how user sessions work

## FOCUS AREAS

### High Priority
1. **Authentication System**
   - Why: Need to add custom SSO
   - Questions: How are providers registered? Where's the auth middleware?
   - Related files: backend/open_webui/routers/auths.py (guessed)

2. **API Layer**
   - Why: Need to understand how frontend talks to backend
   - Questions: REST or WebSocket? How are routes organized?

### Medium Priority
3. **User Model** - Need to understand user data structure
4. **Session Management** - How are sessions stored?

## QUESTIONS TO ANSWER

1. How is authentication middleware applied?
2. Where are auth providers configured?
3. How does the frontend handle auth tokens?
4. What's the user model schema?
5. How do I add a new OAuth provider?

## TARGET ADDITIONS

### Planned Feature: Custom SAML SSO
- **Description:** Add SAML-based SSO for enterprise customers
- **Integration Points:** Auth middleware, user creation
- **Modules to Understand:** Auth routers, user models, config
- **Similar Existing Feature:** Existing OAuth providers
```
