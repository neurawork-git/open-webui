# OAuth Token Flow to Tool Calling Contexts

## Overview

Open WebUI has two OAuth systems that can provide tokens to tool calling contexts:

1. **System OAuth (OAuthManager)** - User login authentication tokens
2. **MCP OAuth (OAuthClientManager)** - Per-MCP-server OAuth 2.1 tokens

## Token Storage

### System OAuth Sessions

Tokens from user login (Google, Microsoft, GitHub, OIDC) are stored in the `oauth_session` table:

```
oauth_session
├── id (UUID)
├── user_id
├── provider (e.g., "google", "microsoft", "oidc")
├── token (encrypted JSON: access_token, id_token, refresh_token, expires_at)
├── expires_at
├── created_at
└── updated_at
```

**Location:** `backend/open_webui/models/oauth_sessions.py`

### MCP OAuth Sessions

MCP servers using OAuth 2.1 store tokens with provider = `mcp:{server_id}`:

```python
OAuthSessions.create_session(
    user_id=user.id,
    provider=f"mcp:{server_id}",
    token=token,
)
```

## Token Flow to Tool Contexts

### Step 1: Building extra_params

When a chat completion request is processed, `extra_params` is built with the OAuth token:

**Location:** `backend/open_webui/utils/middleware.py:1596-1611` and `backend/open_webui/functions.py:244-265`

```python
oauth_token = None
try:
    if request.cookies.get("oauth_session_id", None):
        oauth_token = await request.app.state.oauth_manager.get_oauth_token(
            user.id,
            request.cookies.get("oauth_session_id", None),
        )
except Exception as e:
    pass

extra_params = {
    "__event_emitter__": event_emitter,
    "__event_call__": event_caller,
    "__user__": user.model_dump(),
    "__metadata__": metadata,
    "__oauth_token__": oauth_token,    # <-- OAuth token injected here
    "__request__": request,
    "__model__": model,
    ...
}
```

### Step 2: Token Used by Tool Servers

Tool servers (OpenAPI and MCP) use different auth types configured per-server:

**Location:** `backend/open_webui/utils/tools.py:312-330` (OpenAPI) and `backend/open_webui/utils/middleware.py:1879-1913` (MCP)

| Auth Type | Source | Description |
|-----------|--------|-------------|
| `bearer` | Server config | Static API key: `tool_server_connection.get('key')` |
| `none` | - | No authentication header |
| `session` | Request state | User's JWT: `request.state.token.credentials` |
| `system_oauth` | extra_params | Login OAuth token: `extra_params.get("__oauth_token__")` |
| `oauth_2.1` | OAuth client manager | MCP-specific: `oauth_client_manager.get_oauth_token(user.id, f"mcp:{server_id}")` |

### Code Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           User Chat Request                                  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Middleware: process_chat_payload() / process_chat_response()               │
│                                                                             │
│  1. Check for oauth_session_id cookie                                       │
│  2. Call oauth_manager.get_oauth_token(user_id, session_id)                 │
│  3. Build extra_params with __oauth_token__                                 │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Tool Server Connection (based on auth_type)                                │
│                                                                             │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────────┐  │
│  │ auth_type:      │  │ auth_type:      │  │ auth_type:                  │  │
│  │ "system_oauth"  │  │ "oauth_2.1"     │  │ "session" / "bearer"        │  │
│  │                 │  │ (MCP only)      │  │                             │  │
│  │ Uses:           │  │ Uses:           │  │ Uses:                       │  │
│  │ __oauth_token__ │  │ oauth_client_   │  │ JWT token or                │  │
│  │ from login      │  │ manager for     │  │ static API key              │  │
│  │                 │  │ per-server auth │  │                             │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  HTTP Request to Tool Server                                                │
│                                                                             │
│  headers["Authorization"] = f"Bearer {oauth_token.get('access_token')}"     │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Environment Variables

### Token Encryption (Required for OAuth)

| Variable | Default | Description |
|----------|---------|-------------|
| `OAUTH_SESSION_TOKEN_ENCRYPTION_KEY` | `WEBUI_SECRET_KEY` | Encrypts OAuth tokens stored in DB |
| `OAUTH_CLIENT_INFO_ENCRYPTION_KEY` | `WEBUI_SECRET_KEY` | Encrypts MCP OAuth client info |

### OAuth Login Behavior

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_OAUTH_ID_TOKEN_COOKIE` | `True` | Store ID token in cookie |
| `ENABLE_OAUTH_EMAIL_FALLBACK` | `False` | Generate fallback email if not provided |

### Generic OIDC Provider

| Variable | Default | Description |
|----------|---------|-------------|
| `OAUTH_CLIENT_ID` | - | OAuth client ID |
| `OAUTH_CLIENT_SECRET` | - | OAuth client secret |
| `OPENID_PROVIDER_URL` | - | OIDC discovery URL (`.well-known/openid-configuration`) |
| `OAUTH_SCOPES` | `openid email profile` | OAuth scopes to request |
| `OAUTH_PROVIDER_NAME` | `SSO` | Display name for login button |
| `OAUTH_CODE_CHALLENGE_METHOD` | - | PKCE method (`S256` or none) |
| `OAUTH_TOKEN_ENDPOINT_AUTH_METHOD` | - | Token endpoint auth method |
| `OAUTH_TIMEOUT` | - | Request timeout in seconds |
| `OAUTH_AUDIENCE` | - | OAuth audience parameter |

### Google OAuth

| Variable | Default | Description |
|----------|---------|-------------|
| `GOOGLE_CLIENT_ID` | - | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | - | Google OAuth client secret |
| `GOOGLE_OAUTH_SCOPE` | `openid email profile` | Google OAuth scopes |

### Microsoft OAuth

| Variable | Default | Description |
|----------|---------|-------------|
| `MICROSOFT_CLIENT_ID` | - | Microsoft OAuth client ID |
| `MICROSOFT_CLIENT_SECRET` | - | Microsoft OAuth client secret |
| `MICROSOFT_OAUTH_SCOPE` | `openid email profile` | Microsoft OAuth scopes |

### GitHub OAuth

| Variable | Default | Description |
|----------|---------|-------------|
| `GITHUB_CLIENT_ID` | - | GitHub OAuth client ID |
| `GITHUB_CLIENT_SECRET` | - | GitHub OAuth client secret |

### Feishu OAuth

| Variable | Default | Description |
|----------|---------|-------------|
| `FEISHU_APP_ID` | - | Feishu app ID |
| `FEISHU_APP_SECRET` | - | Feishu app secret |
| `FEISHU_OAUTH_SCOPE` | `contact:user.base:readonly` | Feishu OAuth scopes |

### Claims Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `OAUTH_SUB_CLAIM` | `sub` | Claim for user identifier |
| `OAUTH_EMAIL_CLAIM` | `email` | Claim for user email |
| `OAUTH_USERNAME_CLAIM` | `name` | Claim for user display name |
| `OAUTH_PICTURE_CLAIM` | `picture` | Claim for profile picture URL |
| `OAUTH_GROUPS_CLAIM` | `groups` | Claim for group membership |
| `OAUTH_ROLES_CLAIM` | `roles` | Claim for role assignment |

### Role & Group Management

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_OAUTH_ROLE_MANAGEMENT` | `False` | Enable role assignment from OAuth claims |
| `ENABLE_OAUTH_GROUP_MANAGEMENT` | `False` | Enable group sync from OAuth claims |
| `ENABLE_OAUTH_GROUP_CREATION` | `False` | Auto-create groups from OAuth claims |
| `OAUTH_ALLOWED_ROLES` | `user,admin` | Roles that grant "user" access |
| `OAUTH_ADMIN_ROLES` | `admin` | Roles that grant "admin" access |
| `OAUTH_ALLOWED_DOMAINS` | `*` | Allowed email domains |
| `OAUTH_BLOCKED_GROUPS` | `[]` | Groups to exclude from sync |
| `OAUTH_MERGE_ACCOUNTS_BY_EMAIL` | `False` | Merge accounts with same email |
| `OAUTH_UPDATE_PICTURE_ON_LOGIN` | `False` | Update profile picture on each login |

### Signup Control

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_OAUTH_SIGNUP` | `False` | Allow new user registration via OAuth |
| `ENABLE_OAUTH_PERSISTENT_CONFIG` | `False` | Persist OAuth config changes to DB |

## Configuring Tool Servers for OAuth

### Using System OAuth Token (auth_type: system_oauth)

To use the user's login OAuth token with a tool server:

1. Configure the tool server with `auth_type: "system_oauth"`
2. User must be logged in via OAuth (not local auth)
3. The `oauth_session_id` cookie must be present
4. Token auto-refreshes if within 5 minutes of expiration

**Use case:** Tool servers that accept the same OAuth token as the login provider (e.g., Microsoft Graph API when logged in via Microsoft).

### Using MCP OAuth 2.1 (auth_type: oauth_2.1)

For MCP servers requiring their own OAuth flow:

1. Configure the MCP server with `auth_type: "oauth_2.1"`
2. Provide `oauth_server_url` for the OAuth server
3. Open WebUI performs dynamic client registration
4. User authorizes via `/oauth/clients/{client_id}/authorize`
5. Token stored per-user per-MCP-server

**Use case:** MCP servers with their own OAuth requirements independent of login.

## Token Refresh

Both OAuth managers implement automatic token refresh:

1. Check if token expires within 5 minutes
2. Use `refresh_token` to get new `access_token`
3. Update stored session with new token
4. Delete session if refresh fails

**Location:** `backend/open_webui/utils/oauth.py:660-824` (OAuthClientManager) and `955-1118` (OAuthManager)

## Troubleshooting

### Token Not Available to Tools

1. **Check auth_type** - Ensure tool server uses `system_oauth` or `oauth_2.1`
2. **Check login method** - User must login via OAuth, not local auth
3. **Check cookie** - `oauth_session_id` cookie must be present
4. **Check session** - Session must exist in `oauth_session` table
5. **Check expiration** - Token must not be expired (auto-refresh should handle)

### Token Refresh Failing

1. **Check refresh_token** - Some providers don't issue refresh tokens
2. **Check token_endpoint** - Must be discoverable from OIDC metadata
3. **Check client_secret** - May be required for refresh
4. **Check logs** - Look for "Token refresh failed" errors

## Key Files

| File | Purpose |
|------|---------|
| `backend/open_webui/utils/oauth.py` | OAuthManager and OAuthClientManager classes |
| `backend/open_webui/models/oauth_sessions.py` | OAuth session storage and encryption |
| `backend/open_webui/utils/middleware.py:1596-1611` | Building extra_params with __oauth_token__ |
| `backend/open_webui/utils/tools.py:312-330` | Tool server auth handling |
| `backend/open_webui/functions.py:244-265` | Pipeline extra_params building |
| `backend/open_webui/config.py:330-800` | OAuth configuration variables |
| `backend/open_webui/env.py:509-524` | OAuth environment variables |
