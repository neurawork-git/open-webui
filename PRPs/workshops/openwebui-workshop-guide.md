# Open WebUI Workshop Guide
## For Business Professionals | 2 x 1 Hour Sessions

**Presenter**: [Your Name]
**Audience**: Business professionals with AI understanding
**Format**: Demo-only (no hands-on)
**Backend Focus**: Azure OpenAI
**Tools**: Open WebUI interface, Mural for ideation

---

# PRE-WORKSHOP PREPARATION

## Environment Checklist

- [ ] Open WebUI instance running (URL: _______________)
- [ ] Azure OpenAI connection configured and tested
- [ ] At least 2 models deployed (GPT-4o, GPT-4.1-mini)
- [ ] Sample PDF documents uploaded to Knowledge Base (3-5 docs)
- [ ] Test user accounts created for RBAC demo (Admin, User, Guest)
- [ ] Mural board prepared with diagrams (templates below)
- [ ] Backup screenshots/recordings in case of connectivity issues
- [ ] Browser with Open WebUI open, logged in as Admin

## Demo Data Setup

### Documents for RAG Demo
- [ ] Company annual report or similar (public PDF)
- [ ] Technical documentation sample
- [ ] FAQ or policy document

### Test Prompts Ready
```
1. Simple chat: "Summarize the key points about [topic from uploaded doc]"
2. RAG query: "According to our documents, what is the policy on [X]?"
3. Multi-model: "Compare these two summaries" (switch models mid-conversation)
4. Web search: "What are the latest developments in [industry topic]?"
```

### Mural Board Elements
1. Architecture diagram (Day 1)
2. Competitor comparison matrix (Day 1)
3. Customization decision tree (Day 2)
4. Code architecture layers (Day 2)

---

# DAY 1: OPEN WEBUI FUNDAMENTALS
## Session Overview (60 minutes)

| Time | Section | Key Message |
|------|---------|-------------|
| 0:00-0:10 | Why Open WebUI? | Data sovereignty, cost control, flexibility |
| 0:10-0:20 | Architecture Overview | Simple but powerful, enterprise-ready |
| 0:20-0:35 | Core Features Demo | ChatGPT-like UX with enterprise power |
| 0:35-0:50 | Setup & Configuration | Azure OpenAI in 30 minutes |
| 0:50-1:00 | Q&A + Day 2 Preview | Custom code and enterprise scaling |

---

## 1.1 Why Open WebUI? (10 minutes)

### Opening Hook (30 seconds)
> *"Raise your hand if your legal team has ever blocked an AI tool due to data privacy concerns."*
>
> *"What if I told you there's a way to give your entire organization ChatGPT-like capabilities, with complete data sovereignty, at 1/10th the cost?"*

### The Three Pillars of AI Risk (3 minutes)

**Point 1: Data Privacy Risk**
- **Stat**: 69% of organizations cite AI-powered data leaks as their top concern (2025 survey)
- **Problem**: With cloud AI, your most strategic queries (M&A research, product ideas, competitive analysis) are visible to vendors
- **Real Example**: "Zombie data" in OpenAI's NYT lawsuit - ChatGPT Enterprise customer data from May-September 2025 was legally preserved
- **Transition**: "This is why data sovereignty matters..."

**Point 2: Compliance Risk**
- **Stat**: EU AI Act fines up to 35M or 7% of global revenue
- **Problem**: Cloud AI means vendor as "data processor" - complex GDPR, HIPAA negotiations
- **Real Example**: Healthcare org spent 6+ months negotiating ChatGPT Enterprise BAA. With Open WebUI: 2 weeks to HIPAA compliance.
- **Transition**: "And then there's the cost question..."

**Point 3: Cost Risk**
- **Stat**: ChatGPT Enterprise = $60/user/month = $72,000/year for 100 users
- **Problem**: Per-user licensing scales linearly - it's a trap at enterprise scale
- **Contrast**: Open WebUI = $6,000-24,000/year infrastructure (same 100 users)
- **Savings**: 67-97% cost reduction
- **Transition**: "Open WebUI solves all three..."

### Competitor Comparison (4 minutes)

**Show on Mural**: Competitor Matrix

| Platform | Annual Cost (100 users) | Data Sovereignty | Model Flexibility |
|----------|------------------------|------------------|-------------------|
| **Open WebUI** | $6K-24K | Complete (on-prem) | Any LLM |
| ChatGPT Enterprise | $72K | Cloud only (OpenAI) | OpenAI only |
| Claude Enterprise | $72K | Cloud only (Anthropic) | Claude only |
| Perplexity Enterprise | $40K-390K | Cloud only | Limited |

**Key Talking Points**:
- "Notice the pricing gap - that's not a typo"
- "Cloud-only means you're renting, not owning"
- "Model lock-in means you're at the vendor's mercy"

**Self-Hosted Alternatives** (brief mention):
- LibreChat: Security-focused, no Ollama support
- LobeChat: Beautiful UI, weak enterprise features
- AnythingLLM: Great RAG, limited collaboration
- **Open WebUI**: Combines best of all, proven at 35,000 users

### The Open WebUI Value Proposition (2 minutes)

**One-Liner**: *"Enterprise-grade AI at 1/10th the cost with 10x the control."*

**Six Differentiators**:
1. **Cost**: 67-97% savings, no per-user trap
2. **Data Sovereignty**: Deploy anywhere - on-prem, air-gapped, private cloud
3. **Model Freedom**: GPT-4, Claude, Llama, Gemini, custom - your choice
4. **Compliance**: Self-hosted = sole data controller = simpler GDPR/HIPAA
5. **Advanced RAG**: 9 vector databases, hybrid search, custom pipelines
6. **No Lock-In**: Open source (MIT License), hire any developer

**Transition to Architecture**: "Let me show you how this is possible..."

---

## 1.2 Architecture Overview (10 minutes)

### High-Level Architecture (Show on Mural)

```
+------------------+     +------------------+     +-------------------+
|    Frontend      |     |     Backend      |     |   LLM Providers   |
|   (SvelteKit)    | --> |    (FastAPI)     | --> |                   |
|                  |     |                  |     | - Azure OpenAI    |
|  - Chat UI       |     | - API Routes     |     | - OpenAI API      |
|  - Admin Panel   |     | - RAG Pipeline   |     | - Ollama (local)  |
|  - Settings      |     | - Auth/RBAC      |     | - Anthropic       |
+------------------+     +------------------+     | - Custom models   |
                               |                  +-------------------+
                               v
                    +------------------+
                    |    Database      |
                    | (SQLite/Postgres)|
                    |                  |
                    | - Users/Auth     |
                    | - Conversations  |
                    | - Knowledge Base |
                    +------------------+
```

**Key Talking Points**:
- "Frontend is what you see - clean, familiar, ChatGPT-like"
- "Backend is Python FastAPI - industry standard, enterprise proven"
- "The magic: it speaks to ANY LLM provider through a single interface"
- "Database stores everything locally - your data never leaves"

### Deployment Options (3 minutes)

**Show on Mural**: Deployment Comparison

| Option | Best For | Complexity | Cost/Month |
|--------|----------|------------|------------|
| **Docker Local** | Dev/Testing, POC | Low | Free |
| **Cloud VPS** | Small Teams (10-50) | Medium | $50-200 |
| **Azure Container Apps** | Medium (50-500) | Medium | $200-1,000 |
| **On-Premise + Azure OpenAI** | Enterprise (500+) | High | $1,000-5,000 |
| **Air-Gapped** | Regulated/Classified | High | Variable |

**Key Talking Point**:
> "You can start with Docker on a laptop for free, and scale to 35,000 users like Johannes Gutenberg University did - same platform, same interface."

### Azure OpenAI Integration (4 minutes)

**Why Azure OpenAI for Enterprise**:
1. **Data Sovereignty**: Choose exact region (EU, Canada, Australia, etc.)
2. **Pre-Certified**: HIPAA, SOC 2, GDPR, FedRAMP - 100+ certifications
3. **Network Isolation**: Private endpoints, never touches public internet
4. **Cost Control**: PTU reservations save 40-70% vs. pay-per-token
5. **Single Vendor**: Microsoft agreements already in place for most enterprises

**Talking Point**:
> "A Fortune 500 financial services firm told us: 'We spent 18 months getting OpenAI direct API through legal. With Azure OpenAI, legal approved it in 6 weeks because our Microsoft agreements were already in place.'"

**Transition to Demo**: "Enough theory - let me show you how this works..."

---

## 1.3 Core Features Demo (15 minutes)

### Demo Script

#### Scene 1: First Impression (2 minutes)

**Action**: Open browser, show Open WebUI login page

**Say**:
> "This is Open WebUI. If you've used ChatGPT, this will feel instantly familiar. That's intentional - minimal retraining for your team."

**Action**: Log in, show main chat interface

**Point Out**:
- Clean chat interface
- Model selector dropdown (top)
- Settings gear (bottom left)
- "New Chat" button

**Say**:
> "Notice the model selector here - that's your first superpower. Unlike ChatGPT, you're not locked to one vendor."

#### Scene 2: Multi-Model Chat (3 minutes)

**Action**: Start a chat with GPT-4o

**Say**:
> "Let me ask a question using Azure OpenAI's GPT-4o..."

**Demo Prompt**: "Explain the difference between vector search and keyword search for document retrieval in 3 sentences."

**Wait for response**

**Action**: Switch to GPT-4.1-mini in model selector

**Say**:
> "Now watch this - I can switch models mid-conversation. Let me try a smaller, faster model..."

**Demo Prompt**: "Now explain it in simpler terms, as if to a non-technical executive."

**Wow Moment**:
> "Both responses, same conversation, different models. You can route simple queries to cheap models, complex ones to powerful models. That's how you save 50%+ on costs."

#### Scene 3: Knowledge Base / RAG (5 minutes)

**Action**: Navigate to Knowledge section (sidebar)

**Say**:
> "This is where Open WebUI really shines for enterprises - the Knowledge Base. This is RAG: Retrieval Augmented Generation."

**Action**: Show existing knowledge base with uploaded documents

**Say**:
> "I've already uploaded some sample documents. Let me show you how to query them."

**Action**: Start new chat, toggle "Use Knowledge Base" or select specific KB

**Demo Prompt**: "According to our uploaded documents, what is the [specific topic from your demo docs]?"

**Wait for response with citations**

**Wow Moment**: Point to citations
> "See these citations? Open WebUI shows you exactly where the information came from, with relevance scores. This is transparency you won't get from ChatGPT."

**Additional Point**:
> "Under the hood, Open WebUI supports 9 different vector databases - ChromaDB, PostgreSQL with pgvector, Elasticsearch, Qdrant, and more. It uses hybrid search: combining keyword matching with semantic understanding, then re-ranking for best results."

#### Scene 4: Web Search Integration (2 minutes)

**Action**: Toggle web search on

**Say**:
> "What if you need real-time information? Open WebUI integrates with 15+ web search providers."

**Demo Prompt**: "What are the latest AI regulations announced in the EU this month?"

**Wait for response with web sources**

**Point Out**:
> "Live web results, with sources cited. You choose the search provider - Google, Brave, Bing, or privacy-focused options like SearXNG."

#### Scene 5: User Management & RBAC (3 minutes)

**Action**: Navigate to Admin Panel

**Say**:
> "For IT administrators, here's the Admin Panel. Let me show you user management."

**Show**:
- User list with roles (Admin, User, Guest)
- Permission settings
- Usage analytics

**Say**:
> "You have full role-based access control. Assign users to groups, control which models they can access, set usage limits."

**Show**: Settings page briefly
- SSO/LDAP configuration section
- API key management
- Model configuration

**Say**:
> "LDAP, SAML, OAuth, SCIM 2.0 - all the enterprise auth you'd expect. This integrates with your existing identity provider."

**Transition**: "Now let's talk about how to set this up..."

---

## 1.4 Setup & Configuration (15 minutes)

### Deployment Options Walkthrough (5 minutes)

**Say**:
> "Let me walk you through the deployment options. The simplest is Docker."

**Show on screen (or slide)**:
```bash
# One-liner deployment
docker run -d -p 3000:8080 ghcr.io/open-webui/open-webui:main

# Access at http://localhost:3000
```

**Say**:
> "That's it. One command, and you have Open WebUI running. For production, you'd add persistence and environment variables."

**For Azure Container Apps**:
> "For Azure users, deploy to Azure Container Apps for automatic scaling, managed infrastructure, and native integration with Azure OpenAI via private endpoints."

### Azure OpenAI Connection Setup (5 minutes)

**Action**: Navigate to Admin Panel > Connections

**Say**:
> "Let me show you how to connect Azure OpenAI. This takes about 5 minutes."

**Show Configuration**:
1. Click "+" to add new connection
2. Enter:
   - **API Base URL**: `https://your-resource.openai.azure.com/`
   - **API Key**: From Azure Portal
   - **API Version**: `2024-12-01-preview`
3. Test connection

**Say**:
> "That's all the credentials needed. Open WebUI now speaks Azure OpenAI natively - no middleware, no proxies."

**Key Settings to Highlight**:
| Setting | Recommendation | Why |
|---------|---------------|-----|
| **Default Model** | GPT-4o | Best balance of capability/cost |
| **Temperature** | 0.7 for chat, 0.2 for analysis | Consistency vs. creativity |
| **Max Tokens** | Right-size per use case | Don't waste tokens |

### Security Configuration (3 minutes)

**Show Settings Page**:

**Authentication**:
> "Enable SSO here. We support SAML 2.0, OAuth, OpenID Connect. Most enterprises connect to Azure AD / Entra ID."

**API Keys**:
> "If you're using Azure OpenAI, I recommend Entra ID authentication (keyless) over API keys. Tokens rotate automatically, no secrets in environment variables."

**Network**:
> "For maximum security, deploy in your Azure VNet with private endpoints. Traffic never touches public internet."

### Environment Variables Overview (2 minutes)

**Show Key Variables**:
```bash
# Required
OPENAI_API_BASE_URL=https://your-resource.openai.azure.com/
OPENAI_API_KEY=your-key-here

# Security
WEBUI_SECRET_KEY=your-secret-key
ENABLE_SIGNUP=false  # Disable public registration

# Performance
CHUNK_SIZE=1500
CHUNK_OVERLAP=100
```

**Say**:
> "These are the critical environment variables. For production, store secrets in Azure Key Vault, not in plain text."

---

## 1.5 Q&A + Day 2 Preview (10 minutes)

### Prepared Q&A

**Q: "How does this compare cost-wise to ChatGPT Enterprise?"**
> "For 100 users: ChatGPT Enterprise is $72,000/year. Open WebUI with Azure OpenAI infrastructure is $10,000-24,000/year - that's 67-86% savings. At 1,000 users, you save over $600,000 annually. The key difference: ChatGPT has per-user licensing that scales linearly. Open WebUI has infrastructure costs that scale sub-linearly - more users = lower per-user cost."

**Q: "What about GDPR compliance?"**
> "Self-hosting actually simplifies GDPR. With ChatGPT, OpenAI is a 'data processor' and you need Data Processing Agreements, complex cross-border transfer mechanisms. With Open WebUI + Azure in EU region, you're the sole data controller. Data never leaves your Azure environment. A healthcare client achieved HIPAA compliance in 2 weeks with Open WebUI versus 6+ months negotiating a ChatGPT Enterprise BAA."

**Q: "Can we integrate with our existing systems?"**
> "Absolutely - and that's what we'll cover tomorrow. Open WebUI has a Pipelines framework for custom Python functions, API integrations, and agentic workflows. You can connect to Salesforce, SAP, internal databases - whatever your business needs."

**Q: "What if we already use ChatGPT?"**
> "Gradual migration. Open WebUI's interface is intentionally ChatGPT-like - minimal retraining. Run both in parallel, migrate teams incrementally. Typical migration: 90 days. Switching cost: maybe $4-8K of IT effort. Annual savings: $48-66K. That's a 6-18 day payback period."

**Q: "What about model quality? Is local as good as GPT-4?"**
> "Two answers. First, you can use GPT-4 API through Open WebUI - same model, same quality. Second, local models like Llama 3.3 70B perform at 85-90% of GPT-4 for most tasks. The smart strategy: route 80% of queries to local/cheap models, 20% to GPT-4 for complex reasoning. Same quality, fraction of the cost."

### Day 2 Teaser (2 minutes)

**Say**:
> "Today we covered the fundamentals - what Open WebUI does out of the box."
>
> "Tomorrow, we go custom:"
> - **Tools & Functions**: Build AI-powered workflows without code
> - **Pipelines**: Connect to your internal systems
> - **Forking the Code**: When you need complete control
> - **Enterprise at Scale**: Auth, scaling, observability
>
> "If today answered 'Why Open WebUI?' - tomorrow answers 'What can we build with it?'"

---

# DAY 2: CUSTOMIZATION & ENTERPRISE
## Session Overview (60 minutes)

| Time | Section | Key Message |
|------|---------|-------------|
| 0:00-0:10 | Recap + Custom Vision | From consumer to competitive advantage |
| 0:10-0:25 | Tools & Functions | AI workflows without code |
| 0:25-0:40 | Forking & Code Customization | When you need complete control |
| 0:40-0:55 | Enterprise Considerations | Scaling to 35,000 users |
| 0:55-1:00 | Wrap-up & Resources | Next steps and community |

---

## 2.1 Recap + Custom Vision (10 minutes)

### Quick Day 1 Recap (3 minutes)

**Say**:
> "Quick recap of yesterday:"

**Three Bullets**:
1. **Data Sovereignty**: Open WebUI runs in YOUR infrastructure - data never leaves
2. **Cost Control**: 67-97% savings vs. ChatGPT Enterprise
3. **Model Freedom**: Any LLM - GPT-4, Claude, Llama, or custom fine-tuned

**Say**:
> "Those are the fundamentals. But here's the thing: fundamentals are table stakes. Your competitors can deploy Open WebUI too."
>
> "The question today: How do you turn AI into a competitive advantage?"

### Why Customize? (4 minutes)

**The Commodity Problem**:
> "ChatGPT Enterprise gives everyone the same tool. Same features, same capabilities. There's no differentiation."
>
> "Open WebUI gives you the foundation. What you build on top is unique to your business."

**Customization Categories**:

**Show on Mural**: Customization Decision Tree

```
What do you need to customize?
├── Branding/UI → Simple: CSS, logos, themes
├── Workflows → Tools & Functions (no-code)
├── Integrations → Pipelines (low-code Python)
├── Core Features → Fork & Modify (full code)
└── Model Behavior → Fine-tuning (advanced)
```

**Real Examples**:
1. **Financial Services**: Custom compliance-checking agent that references internal policies before every response
2. **Healthcare**: Medical terminology RAG pipeline with HIPAA-compliant logging
3. **Legal**: Contract analysis tool that compares clauses against template library
4. **Manufacturing**: Equipment maintenance assistant connected to IoT sensor data

**Talking Point**:
> "These aren't hypotheticals. Organizations are building these right now. The question is: what will you build?"

### Today's Journey (3 minutes)

**Say**:
> "We'll cover three levels of customization today:"

**Three Levels**:
1. **Tools & Functions**: No code required. Build in the UI. Great for 80% of use cases.
2. **Pipelines**: Low-code Python. Connect to external systems. When you need integrations.
3. **Fork & Modify**: Full code access. When you need complete control over the platform.

**Transition**: "Let's start with the most accessible: Tools & Functions..."

---

## 2.2 Tools & Functions (15 minutes)

### Built-in Tools Demo (5 minutes)

**Action**: Navigate to Tools section in Open WebUI

**Say**:
> "Open WebUI comes with several built-in tools that extend AI capabilities beyond just chat."

**Demo: Web Search Tool**
- Toggle web search on
- Ask a current events question
- Show sources

**Demo: Code Execution Tool**
- Ask AI to write and run Python code
- "Calculate the compound interest on $10,000 at 5% for 10 years"
- Show the code being executed and result

**Say**:
> "These tools let the AI take actions, not just talk. Search the web, run code, analyze data."

### Custom Functions (5 minutes)

**Action**: Show Functions section

**Say**:
> "Here's where it gets interesting. You can define custom functions - no external code required."

**Show Example Function** (pre-created):
```python
# Example: Currency Converter Function
def convert_currency(amount: float, from_currency: str, to_currency: str) -> str:
    """Convert between currencies using live rates."""
    # API call to exchange rate service
    rate = get_exchange_rate(from_currency, to_currency)
    result = amount * rate
    return f"{amount} {from_currency} = {result:.2f} {to_currency}"
```

**Say**:
> "This function lets the AI convert currencies. You write Python, define the inputs, and the AI can call it when needed."

**Key Points**:
- Functions run in sandboxed Python
- Define input parameters with types
- Return structured data
- AI decides when to call based on context

**Use Cases**:
- Query internal databases
- Call company APIs
- Process uploaded files
- Generate reports

### Pipelines Concept (5 minutes)

**Show on Mural**: Pipeline Architecture

```
User Query
    │
    v
┌─────────────┐
│  Pipeline   │  ← Pre-processing, routing, validation
│   Inlet     │
└─────────────┘
    │
    v
┌─────────────┐
│    LLM      │  ← Model inference
│  Processing │
└─────────────┘
    │
    v
┌─────────────┐
│  Pipeline   │  ← Post-processing, logging, actions
│   Outlet    │
└─────────────┘
    │
    v
Response to User
```

**Say**:
> "Pipelines are middleware. They intercept requests before the LLM and responses after. This is how you build enterprise workflows."

**Pipeline Examples**:
1. **Compliance Filter**: Check every prompt against prohibited topics before sending to LLM
2. **Cost Router**: Route simple queries to cheap models, complex to expensive
3. **Audit Logger**: Log every interaction to your SIEM system
4. **PII Redactor**: Strip personal data before it reaches the model
5. **Response Formatter**: Ensure all outputs follow your brand voice

**Talking Point**:
> "Pipelines are what separate a toy from an enterprise system. With 10 lines of Python, you can enforce compliance, optimize costs, and integrate with existing infrastructure."

### MCP Integration Overview (2 minutes)

**Say**:
> "One more thing: Model Context Protocol, or MCP. This is an emerging standard for AI tool integration."

**Key Points**:
- MCP lets AI connect to external tools via a standard protocol
- Databases, APIs, file systems, custom services
- Open WebUI supports MCP natively
- Example: Connect to Notion, Slack, GitHub, your CRM

**Talking Point**:
> "MCP is the future of AI integrations. Instead of custom code for every service, one protocol connects them all. Open WebUI is already there."

---

## 2.3 Forking & Code Customization (15 minutes)

### Architecture Deep-Dive (5 minutes)

**Show on Mural**: Code Architecture

```
open-webui/
├── backend/                    ← Python (FastAPI)
│   └── open_webui/
│       ├── main.py            ← App entry point
│       ├── config.py          ← Configuration
│       ├── routers/           ← API endpoints
│       │   ├── chats.py       ← Chat endpoints
│       │   ├── retrieval.py   ← RAG endpoints
│       │   └── users.py       ← User management
│       ├── retrieval/         ← RAG pipeline
│       │   ├── main.py        ← RAG orchestration
│       │   ├── vector/        ← Vector DB adapters
│       │   └── web/           ← Web search
│       └── models/            ← Database models
│
├── src/                        ← TypeScript (SvelteKit)
│   ├── lib/
│   │   ├── components/        ← UI components
│   │   └── stores/            ← State management
│   └── routes/                ← Pages
│
└── docker-compose.yaml         ← Deployment config
```

**Key Talking Points**:
- "Backend is Python FastAPI - if your team knows Python, they know this"
- "Frontend is SvelteKit - modern, fast, component-based"
- "Clean separation: change the UI without touching the backend, or vice versa"
- "Standard patterns throughout - no proprietary magic"

### Key Files to Modify (3 minutes)

**For Business Logic**:
- `backend/open_webui/routers/` - Add new API endpoints
- `backend/open_webui/retrieval/` - Customize RAG behavior
- `backend/open_webui/config.py` - Add configuration options

**For UI Changes**:
- `src/lib/components/` - Modify or add UI components
- `src/routes/` - Add new pages
- `tailwind.config.js` - Branding and theming

**For Integration**:
- `backend/open_webui/utils/` - Add utility functions
- Environment variables in `config.py`

**Say**:
> "You don't need to understand the whole codebase. Most customizations touch just a few files. The architecture is designed for extensibility."

### RAG Improvements Case Study (5 minutes)

**Say**:
> "Let me show you a real example. We customized Open WebUI's RAG pipeline for a client project."

**What We Changed**:

1. **Per-Knowledge-Base Settings**:
   - Default: One RAG configuration for all knowledge bases
   - Custom: Each KB can have different settings (chunk size, search depth, re-ranking)
   - Why: Different documents need different treatment (legal vs. technical)

2. **Improved BM25 Tokenization**:
   - Default: Basic word splitting
   - Custom: Strip punctuation from word boundaries, better handling of technical terms
   - Why: More accurate keyword matching

3. **Reindex Functionality**:
   - Default: Delete and re-upload to update vectors
   - Custom: One-click reindex per knowledge base
   - Why: Easier maintenance as documents change

**Show**: Our recent git commits implementing these features

**Talking Point**:
> "Total development time: about 2 weeks. These changes are now part of our fork. We could upstream them to the community, keep them proprietary, or both."

### Development Workflow (2 minutes)

**High-Level Process**:

1. **Fork the Repository**: `git clone https://github.com/open-webui/open-webui`
2. **Set Up Dev Environment**: Docker or local Python/Node
3. **Make Changes**: Standard dev workflow (branch, code, test)
4. **Test**: Local Docker deployment
5. **Deploy**: Push to your container registry, update production
6. **Stay Updated**: Merge upstream changes periodically

**Say**:
> "The workflow is standard software development. Fork, customize, deploy. You're not locked into a vendor's roadmap - you control the code."

**Time Investment**:
- Simple UI changes: 1-2 days
- New API endpoints: 1-2 weeks
- Major feature additions: 2-4 weeks
- Full custom fork maintenance: 1-2 days/month for upstream sync

---

## 2.4 Enterprise Considerations (15 minutes)

### Authentication Options (4 minutes)

**Show on Mural**: Auth Architecture

**Supported Methods**:
| Method | Use Case | Complexity |
|--------|----------|------------|
| **Local Auth** | Small teams, POC | Low |
| **OAuth 2.0** | Google, GitHub, social | Low |
| **SAML 2.0** | Enterprise SSO (Okta, Azure AD) | Medium |
| **LDAP/AD** | On-premise directories | Medium |
| **SCIM 2.0** | Automated provisioning | High |
| **Trusted Headers** | Reverse proxy auth | Low |

**Key Talking Points**:
- "Most enterprises use SAML with their existing IdP"
- "SCIM automates user lifecycle - user joins company, gets access; leaves, loses access"
- "You can combine methods: SAML for internal users, OAuth for contractors"

**Demo**: Show LDAP configuration in Admin Panel (if time)

### Horizontal Scaling with Redis (4 minutes)

**Show on Mural**: Scaling Architecture

```
                    ┌─────────────┐
                    │   Load      │
                    │  Balancer   │
                    └─────────────┘
                          │
         ┌────────────────┼────────────────┐
         │                │                │
         v                v                v
   ┌──────────┐     ┌──────────┐     ┌──────────┐
   │ Open     │     │ Open     │     │ Open     │
   │ WebUI    │     │ WebUI    │     │ WebUI    │
   │ Node 1   │     │ Node 2   │     │ Node 3   │
   └──────────┘     └──────────┘     └──────────┘
         │                │                │
         └────────────────┼────────────────┘
                          │
                    ┌─────────────┐
                    │   Redis     │  ← Session state
                    │   Cluster   │  ← WebSocket routing
                    └─────────────┘
                          │
                    ┌─────────────┐
                    │  PostgreSQL │  ← Persistent data
                    │    (HA)     │
                    └─────────────┘
```

**Key Points**:
- "Single node handles 100-500 concurrent users"
- "Redis enables horizontal scaling - add nodes as needed"
- "Proven at 35,000 users (Johannes Gutenberg University)"
- "WebSockets route correctly across nodes"
- "Kubernetes or Docker Swarm for orchestration"

**Talking Point**:
> "This is the same architecture patterns as any modern web application. If your team can scale a web app, they can scale Open WebUI."

### Observability (OpenTelemetry) (3 minutes)

**Say**:
> "For enterprise operations, you need visibility. Open WebUI has built-in OpenTelemetry support."

**What You Can Monitor**:
- **Traces**: Follow a request from user to LLM and back
- **Metrics**: Token usage, response times, error rates, user activity
- **Logs**: Structured logging for every interaction

**Integration Points**:
- Prometheus + Grafana (open source)
- Azure Monitor / Application Insights
- Datadog, New Relic, Splunk
- Your existing SIEM

**Show**: Sample Grafana dashboard (if available)

**Key Metrics to Track**:
| Metric | Why It Matters |
|--------|---------------|
| Tokens per user/day | Cost allocation |
| P95 response time | User experience |
| Error rate by model | Quality monitoring |
| RAG hit rate | Knowledge base effectiveness |
| Active users | Adoption tracking |

### Update Strategy & Maintenance (4 minutes)

**The Challenge**:
> "Open source moves fast. Open WebUI releases updates frequently. How do you stay current without breaking production?"

**Recommended Strategy**:

1. **Track Upstream**: Watch releases, read changelogs
2. **Quarterly Major Updates**: Merge upstream changes every 3 months
3. **Security Patches**: Apply immediately (within 48 hours)
4. **Test Before Production**: Staging environment with real data
5. **Rollback Plan**: Always have previous version ready

**Maintenance Time Investment**:
- Weekly: Monitor for security advisories (15 min)
- Monthly: Review new releases (1 hour)
- Quarterly: Major upgrade cycle (1-2 days)

**Talking Point**:
> "Compare this to SaaS: updates happen to you, whether you want them or not. With self-hosted, you control the timing. Production stability is in your hands."

**LTS Option**:
> "Enterprise support includes Long-Term Support versions if you need extended stability."

---

## 2.5 Wrap-up & Resources (5 minutes)

### Key Takeaways (2 minutes)

**Day 1 Recap**:
1. **Why**: Data sovereignty, cost savings, model freedom
2. **What**: Full-featured AI platform, enterprise-ready
3. **How**: Azure OpenAI integration in 30 minutes

**Day 2 Recap**:
1. **Tools & Functions**: Extend AI without code
2. **Pipelines**: Enterprise workflows with light Python
3. **Forking**: Complete control when you need it
4. **Scaling**: Proven architecture to 35,000 users

### Resource Links (1 minute)

**Essential Links**:
- **Documentation**: https://docs.openwebui.com/
- **GitHub**: https://github.com/open-webui/open-webui (50K+ stars)
- **Enterprise**: https://docs.openwebui.com/enterprise/
- **Discord**: Community support (10K+ members)

**Azure OpenAI**:
- **Portal**: https://oai.azure.com/
- **Pricing**: https://azure.microsoft.com/pricing/details/cognitive-services/openai-service/
- **PTU Calculator**: https://www.ptucalc.com/

### Next Steps for Your Organization (2 minutes)

**Week 1**: Pilot Deployment
- [ ] Deploy Open WebUI (2-4 hours)
- [ ] Connect to Azure OpenAI (30 minutes)
- [ ] Invite 5-10 pilot users
- [ ] Calculate cost savings for your org

**Month 1**: Validation
- [ ] Expand to 20-50 users
- [ ] Configure SSO integration
- [ ] Set up RAG with internal documents
- [ ] Gather user feedback

**Month 2-3**: Production
- [ ] Production infrastructure (HA, monitoring)
- [ ] Full user migration
- [ ] Custom workflows/integrations
- [ ] Training for power users

**Month 4+**: Optimization
- [ ] Fine-tune models on your data
- [ ] Build competitive advantage features
- [ ] Measure and report ROI

### Final Thought

> "In 2025, AI is infrastructure - not a service. Organizations that own their AI infrastructure will control their destiny. Those who rent from vendors will be at their mercy."
>
> "Open WebUI puts you in control. What you build with it is up to you."

### Q&A

**Open for questions...**

---

# APPENDIX

## Mural Board Templates

### Template 1: Competitor Comparison Matrix
Create a 4x6 grid with:
- Rows: Open WebUI, ChatGPT Enterprise, Claude Enterprise, Perplexity
- Columns: Cost, Data Sovereignty, Model Flexibility, RAG, Enterprise Auth, Customization
- Use color coding: Green (advantage), Yellow (partial), Red (limitation)

### Template 2: Architecture Diagram
Use the ASCII diagrams from sections 1.2 and 2.4 as reference. Create visual boxes with:
- Frontend (blue)
- Backend (green)
- LLM Providers (orange)
- Database (purple)
- External integrations (gray)

### Template 3: Customization Decision Tree
Flowchart starting with "What do you need?" branching to:
- Branding → CSS/Themes
- Workflows → Tools & Functions
- Integrations → Pipelines
- Core Features → Fork & Modify

### Template 4: Scaling Architecture
Multi-node diagram showing:
- Load balancer at top
- 3 Open WebUI nodes
- Redis cluster
- PostgreSQL HA

## Backup Plans

### If Azure OpenAI is slow/unavailable:
- Have screenshots/recordings of demos ready
- Pre-recorded video of RAG demo
- Fallback to local Ollama if configured

### If Live Demo Fails:
- "Let me show you a recording of this..."
- Switch to slides/screenshots
- Focus on architecture explanation

### If Questions Go Off-Topic:
- "Great question - let's take that offline. Here's my contact..."
- "That's a Day 2 topic - we'll cover it tomorrow"
- Park complex questions for end of session

## Glossary

| Term | Definition |
|------|------------|
| **RAG** | Retrieval Augmented Generation - enhancing AI responses with retrieved documents |
| **LLM** | Large Language Model - the AI that generates responses (GPT-4, Claude, Llama) |
| **Vector Database** | Database optimized for similarity search using embeddings |
| **Embeddings** | Numerical representations of text for semantic similarity |
| **PTU** | Provisioned Throughput Unit - Azure OpenAI's reserved capacity |
| **Pipeline** | Middleware that processes requests before/after the LLM |
| **SSO** | Single Sign-On - authenticate once, access multiple services |
| **SCIM** | System for Cross-domain Identity Management - automate user provisioning |
| **MCP** | Model Context Protocol - standard for AI tool integrations |

---

**Document Version**: 1.0
**Created**: December 2025
**Last Updated**: December 2025
**Author**: Workshop Development Team

---

*Workshop materials based on research from Open WebUI documentation, Azure OpenAI documentation, and competitive analysis conducted December 2025.*
