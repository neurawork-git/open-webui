# Microsoft Entra ID (Azure AD) OAuth Setup for Open WebUI

## Executive Summary

This guide provides comprehensive instructions for configuring Microsoft Entra ID (formerly Azure AD) as an OAuth provider for Open WebUI. It covers Azure app registration, environment variable configuration, common pitfalls, and Kubernetes-specific deployment patterns.

**Key Findings:**
- Open WebUI has native Microsoft OAuth support (separate from generic OIDC)
- Requires specific environment variables (`MICROSOFT_*` prefix)
- Email claim must be explicitly configured in Azure AD
- PKCE support is required for modern Azure AD deployments
- Single-tenant limitation (one organization or personal accounts)

---

## Table of Contents

1. [Azure AD App Registration](#azure-ad-app-registration)
2. [Environment Variables](#environment-variables)
3. [Optional Claims Configuration](#optional-claims-configuration)
4. [Kubernetes Deployment](#kubernetes-deployment)
5. [Common Gotchas](#common-gotchas)
6. [Troubleshooting](#troubleshooting)
7. [Security Best Practices](#security-best-practices)
8. [References](#references)

---

## Azure AD App Registration

### Step 1: Create App Registration

1. Navigate to **Azure Portal** > **Microsoft Entra ID** > **App registrations**
2. Click **+ New registration**
3. Configure:
   - **Name**: `Open WebUI` (or your preferred name)
   - **Supported account types**:
     - **Single tenant**: `Accounts in this organizational directory only` (most common)
     - **Personal accounts**: `Personal Microsoft accounts only` (use tenant ID `9188040d-6c67-4c5b-b112-36a304b66dad`)
   - **Redirect URI**:
     - Platform: **Web** (NOT Single-Page Application)
     - URI: `https://your-domain.com/oauth/microsoft/callback`

**Important:** The redirect URI format is **critical**:
```
https://<your-open-webui-domain>/oauth/microsoft/callback
```

### Step 2: Generate Client Secret

1. Go to **Certificates & secrets** > **Client secrets**
2. Click **+ New client secret**
3. Configure:
   - **Description**: `Open WebUI OAuth`
   - **Expires**: 24 months (recommended) or custom
4. Click **Add**
5. **Copy the secret value immediately** (it won't be shown again)
6. Store securely for the `MICROSOFT_CLIENT_SECRET` environment variable

### Step 3: Configure API Permissions

1. Go to **API permissions**
2. Click **+ Add a permission**
3. Select **Microsoft Graph**
4. Choose **Delegated permissions**
5. Add the following permissions:
   - `openid` - Sign users in
   - `email` - View users' email address
   - `profile` - View users' basic profile
6. Click **Add permissions**
7. **Optional but recommended**: Click **Grant admin consent** for your organization

### Step 4: Configure Optional Claims (CRITICAL)

**Why this is needed:** Azure AD keeps tokens lean by default. The `email` claim is **NOT included** in ID tokens for managed accounts unless explicitly requested.

1. Go to **Token configuration**
2. Click **+ Add optional claim**
3. Select **ID** token type
4. Check the **email** claim
5. Click **Add**
6. If prompted about Microsoft Graph permissions, click **Add**

**Without this step, authentication will fail** because Open WebUI requires the email claim.

### Step 5: Note Your Configuration Values

Collect these values for environment variable configuration:

- **Application (client) ID**: Found on the Overview page
- **Directory (tenant) ID**: Found on the Overview page
- **Client secret**: The value you copied in Step 2

---

## Environment Variables

### Required Variables

```bash
# Microsoft OAuth Configuration
MICROSOFT_CLIENT_ID=<your-application-client-id>
MICROSOFT_CLIENT_SECRET=<your-client-secret>
MICROSOFT_CLIENT_TENANT_ID=<your-directory-tenant-id>

# OAuth Settings
ENABLE_OAUTH_SIGNUP=true
OAUTH_MERGE_ACCOUNTS_BY_EMAIL=true

# OpenID Provider URL (required for logout to work)
OPENID_PROVIDER_URL=https://login.microsoftonline.com/<your-tenant-id>/v2.0/.well-known/openid-configuration
```

### Optional Variables

```bash
# Redirect URI (auto-detected if not set)
MICROSOFT_REDIRECT_URI=https://your-domain.com/oauth/microsoft/callback

# Scope (default is sufficient)
MICROSOFT_OAUTH_SCOPE=openid email profile

# Login base URL (for sovereign clouds)
MICROSOFT_CLIENT_LOGIN_BASE_URL=https://login.microsoftonline.com

# Profile picture URL
MICROSOFT_CLIENT_PICTURE_URL=https://graph.microsoft.com/v1.0/me/photo/$value

# OAuth timeout (in seconds)
OAUTH_TIMEOUT=30
```

### Variable Explanations

| Variable | Description | Required |
|----------|-------------|----------|
| `MICROSOFT_CLIENT_ID` | Application (client) ID from Azure app registration | Yes |
| `MICROSOFT_CLIENT_SECRET` | Client secret value from Azure | Yes |
| `MICROSOFT_CLIENT_TENANT_ID` | Directory (tenant) ID from Azure | Yes |
| `ENABLE_OAUTH_SIGNUP` | Allow new users to sign up via OAuth | Yes |
| `OAUTH_MERGE_ACCOUNTS_BY_EMAIL` | Merge existing accounts by email address | Recommended |
| `OPENID_PROVIDER_URL` | OIDC discovery endpoint (required for logout) | Yes |
| `MICROSOFT_REDIRECT_URI` | Explicit redirect URI (auto-detected if omitted) | Optional |
| `MICROSOFT_OAUTH_SCOPE` | OAuth scopes to request | Optional |
| `MICROSOFT_CLIENT_LOGIN_BASE_URL` | Base URL for Microsoft login (for sovereign clouds) | Optional |

---

## Optional Claims Configuration

### Why Email Claim is Critical

By design, Microsoft Entra ID keeps tokens lean. The `email` claim appears automatically in ID tokens **only** for:
- Guest accounts (external users) with email on record
- Personal Microsoft accounts

For **normal tenant users (managed accounts)**, the email claim is **omitted by default**.

### Configuring Email Claim via Azure Portal

**Method 1: Token Configuration (Recommended)**

1. App Registration > **Token configuration**
2. **+ Add optional claim** > **ID** token
3. Select **email** checkbox
4. Click **Add**
5. Confirm Microsoft Graph permission if prompted

**Method 2: Manifest Editor**

1. App Registration > **Manifest**
2. Find `optionalClaims` section
3. Add:
```json
"optionalClaims": {
  "idToken": [
    {
      "name": "email",
      "source": null,
      "essential": false,
      "additionalProperties": []
    }
  ]
}
```
4. Click **Save**

### Verifying Email Claim

After configuration, test authentication and check the ID token contains:
```json
{
  "email": "user@domain.com",
  "preferred_username": "user@domain.com",
  "name": "User Name",
  ...
}
```

**Note:** The email claim will **only** be returned if the user's profile includes an email attribute (typically from `userPrincipalName` or primary email field).

---

## Kubernetes Deployment

### Using Kubernetes Secrets

**Step 1: Create Secret**

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: open-webui-oauth
  namespace: open-webui
type: Opaque
stringData:
  MICROSOFT_CLIENT_ID: "<your-application-client-id>"
  MICROSOFT_CLIENT_SECRET: "<your-client-secret>"
  MICROSOFT_CLIENT_TENANT_ID: "<your-directory-tenant-id>"
```

Apply the secret:
```bash
kubectl apply -f open-webui-oauth-secret.yaml
```

**Step 2: Reference in Deployment**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: open-webui
  namespace: open-webui
spec:
  template:
    spec:
      containers:
      - name: open-webui
        image: ghcr.io/open-webui/open-webui:main
        env:
        # OAuth secrets from Kubernetes Secret
        - name: MICROSOFT_CLIENT_ID
          valueFrom:
            secretKeyRef:
              name: open-webui-oauth
              key: MICROSOFT_CLIENT_ID
        - name: MICROSOFT_CLIENT_SECRET
          valueFrom:
            secretKeyRef:
              name: open-webui-oauth
              key: MICROSOFT_CLIENT_SECRET
        - name: MICROSOFT_CLIENT_TENANT_ID
          valueFrom:
            secretKeyRef:
              name: open-webui-oauth
              key: MICROSOFT_CLIENT_TENANT_ID

        # OAuth configuration (non-sensitive)
        - name: ENABLE_OAUTH_SIGNUP
          value: "true"
        - name: OAUTH_MERGE_ACCOUNTS_BY_EMAIL
          value: "true"
        - name: OPENID_PROVIDER_URL
          value: "https://login.microsoftonline.com/<tenant-id>/v2.0/.well-known/openid-configuration"
        - name: MICROSOFT_REDIRECT_URI
          value: "https://your-domain.com/oauth/microsoft/callback"
```

### Using Azure Key Vault (Recommended for Production)

**Option 1: Secrets Store CSI Driver**

1. Install the Azure Key Vault Provider for Secrets Store CSI Driver
2. Configure SecretProviderClass:

```yaml
apiVersion: secrets-store.csi.x-k8s.io/v1
kind: SecretProviderClass
metadata:
  name: open-webui-azure-keyvault
  namespace: open-webui
spec:
  provider: azure
  parameters:
    usePodIdentity: "false"
    useVMManagedIdentity: "true"
    userAssignedIdentityID: "<managed-identity-client-id>"
    keyvaultName: "<your-keyvault-name>"
    cloudName: "AzurePublicCloud"
    objects: |
      array:
        - |
          objectName: microsoft-client-id
          objectType: secret
          objectAlias: MICROSOFT_CLIENT_ID
        - |
          objectName: microsoft-client-secret
          objectType: secret
          objectAlias: MICROSOFT_CLIENT_SECRET
        - |
          objectName: microsoft-tenant-id
          objectType: secret
          objectAlias: MICROSOFT_CLIENT_TENANT_ID
    tenantId: "<azure-tenant-id>"
```

3. Mount in deployment:

```yaml
volumes:
- name: secrets-store
  csi:
    driver: secrets-store.csi.k8s.io
    readOnly: true
    volumeAttributes:
      secretProviderClass: open-webui-azure-keyvault
```

**Option 2: External Secrets Operator**

1. Install External Secrets Operator
2. Create SecretStore:

```yaml
apiVersion: external-secrets.io/v1beta1
kind: SecretStore
metadata:
  name: azure-keyvault
  namespace: open-webui
spec:
  provider:
    azurekv:
      tenantId: "<azure-tenant-id>"
      vaultUrl: "https://<keyvault-name>.vault.azure.net"
      authType: WorkloadIdentity
      serviceAccountRef:
        name: open-webui-sa
```

3. Create ExternalSecret:

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: open-webui-oauth
  namespace: open-webui
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: azure-keyvault
    kind: SecretStore
  target:
    name: open-webui-oauth
    creationPolicy: Owner
  data:
  - secretKey: MICROSOFT_CLIENT_ID
    remoteRef:
      key: microsoft-client-id
  - secretKey: MICROSOFT_CLIENT_SECRET
    remoteRef:
      key: microsoft-client-secret
  - secretKey: MICROSOFT_CLIENT_TENANT_ID
    remoteRef:
      key: microsoft-tenant-id
```

### Helm Chart Configuration

If using the Open WebUI Helm chart:

```yaml
# values.yaml
env:
  ENABLE_OAUTH_SIGNUP: "true"
  OAUTH_MERGE_ACCOUNTS_BY_EMAIL: "true"
  OPENID_PROVIDER_URL: "https://login.microsoftonline.com/<tenant-id>/v2.0/.well-known/openid-configuration"
  MICROSOFT_REDIRECT_URI: "https://your-domain.com/oauth/microsoft/callback"

# Use existing secret
envFrom:
  - secretRef:
      name: open-webui-oauth
```

---

## Common Gotchas

### 1. AADSTS9002325: Proof Key for Code Exchange Required

**Error:** "AADSTS9002325: Proof Key for Code Exchange is required for cross-origin authorization code redemption"

**Cause:** Azure AD now requires PKCE (Proof Key for Code Exchange) for cross-origin OAuth flows.

**Solution:**
- In Azure Portal, ensure app platform is set to **Web** (NOT Single-Page Application)
- Open WebUI automatically handles PKCE when the OAuth server supports it
- Check that `code_challenge_methods_supported` includes `S256` in the OIDC discovery document

**Code Reference:**
```python
# From open_webui/utils/oauth.py (lines 433-444)
if (
    oauth_client_info.server_metadata
    and oauth_client_info.server_metadata.code_challenge_methods_supported
):
    if (
        isinstance(
            oauth_client_info.server_metadata.code_challenge_methods_supported,
            list,
        )
        and "S256"
        in oauth_client_info.server_metadata.code_challenge_methods_supported
    ):
        kwargs["code_challenge_method"] = "S256"
```

### 2. Email Claim Missing

**Error:** Authentication fails silently or returns "Email is required"

**Cause:** Email claim not included in ID token (Azure AD default for managed accounts)

**Solution:**
1. Add **email** as optional claim in Token Configuration
2. Grant Microsoft Graph `email` permission
3. Ensure user has email attribute populated in Azure AD profile

**Verification:**
```bash
# Decode ID token to check claims (use jwt.io or similar)
# Look for "email" field in token payload
```

### 3. Redirect URI Mismatch

**Error:** "AADSTS50011: The redirect URI does not match the redirect URIs configured for the application"

**Cause:** Redirect URI in request doesn't match Azure app registration

**Solution:**
- Ensure exact match (case-sensitive, trailing slash matters)
- Format: `https://<domain>/oauth/microsoft/callback`
- Protocol must match (http vs https)
- No query parameters in registered URI

**Common mistakes:**
```
❌ https://domain.com/oauth/microsoft/callback/
❌ https://domain.com/oauth/microsoft/
❌ http://domain.com/oauth/microsoft/callback (when using https)
✅ https://domain.com/oauth/microsoft/callback
```

### 4. Single-Tenant Limitation

**Issue:** Cannot authenticate users from multiple Azure AD tenants

**Cause:** Open WebUI's Microsoft provider supports one tenant at a time

**Solution:**
- For multi-tenant: Use generic OIDC provider instead (`OAUTH_CLIENT_ID`, `OPENID_PROVIDER_URL`)
- For guest users: Invite them to your primary tenant first
- For partners: Consider federation at the Azure AD level

### 5. Logout Not Working

**Issue:** Users redirected to blank page or error after logout

**Cause:** `OPENID_PROVIDER_URL` not configured

**Solution:**
```bash
OPENID_PROVIDER_URL=https://login.microsoftonline.com/<tenant-id>/v2.0/.well-known/openid-configuration
```

**Code Reference:**
```python
# From open_webui/config.py (lines 805-809)
if configured_providers and not OPENID_PROVIDER_URL.value:
    provider_list = ", ".join(configured_providers)
    log.warning(
        f"⚠️  OAuth providers configured ({provider_list}) but OPENID_PROVIDER_URL not set - logout will not work!"
    )
```

### 6. Behind Reverse Proxy Issues

**Issue:** OAuth redirects to internal URL or fails with proxy

**Cause:** Proxy doesn't forward correct scheme/host headers

**Solution:**
- Configure proxy to set `X-Forwarded-Proto` and `X-Forwarded-Host` headers
- For NGINX:
```nginx
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header X-Forwarded-Host $host;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
```
- For Traefik: Enable `forwardedHeaders.insecure=true` (dev) or configure trusted IPs (prod)

### 7. Token Expiration Issues

**Issue:** Users logged out unexpectedly or frequent re-authentication required

**Cause:** Short JWT expiration in Open WebUI

**Solution:**
```bash
# Increase JWT expiration (default: 4 weeks)
JWT_EXPIRES_IN=8w
```

**Note:** `-1` disables expiration (NOT recommended for production)

---

## Troubleshooting

### Enable OAuth Debug Logging

```bash
OAUTH_LOG_LEVEL=DEBUG
GLOBAL_LOG_LEVEL=DEBUG
```

### Check OIDC Discovery Endpoint

Test that Azure AD's discovery endpoint is accessible:

```bash
curl https://login.microsoftonline.com/<tenant-id>/v2.0/.well-known/openid-configuration
```

Expected response includes:
```json
{
  "issuer": "https://login.microsoftonline.com/<tenant-id>/v2.0",
  "authorization_endpoint": "https://login.microsoftonline.com/<tenant-id>/oauth2/v2.0/authorize",
  "token_endpoint": "https://login.microsoftonline.com/<tenant-id>/oauth2/v2.0/token",
  "token_endpoint_auth_methods_supported": [
    "client_secret_post",
    "client_secret_basic"
  ],
  "code_challenge_methods_supported": [
    "plain",
    "S256"
  ],
  ...
}
```

### Test OAuth Flow Manually

1. Navigate to Open WebUI login page
2. Open browser developer tools (F12) > Network tab
3. Click Microsoft login button
4. Check redirect URLs and token exchange requests
5. Look for errors in console logs

### Verify Environment Variables Loaded

Check container environment:
```bash
# Kubernetes
kubectl exec -it <pod-name> -n open-webui -- env | grep MICROSOFT

# Docker
docker exec <container-name> env | grep MICROSOFT
```

### Check Open WebUI Logs

```bash
# Kubernetes
kubectl logs <pod-name> -n open-webui | grep -i oauth

# Docker
docker logs <container-name> | grep -i oauth
```

### Common Log Messages

**Success:**
```
INFO: OAuth providers configured (Microsoft) but OPENID_PROVIDER_URL not set - logout will not work!
INFO: 'MICROSOFT_CLIENT_ID' loaded from the latest database entry
INFO: Stored OAuth session server-side for user <user-id>, provider microsoft
```

**Failures:**
```
ERROR: OAuth callback failed, user data is missing
ERROR: No OAuth client found for provider microsoft
WARNING: OAuth callback failed, email is missing
```

---

## Security Best Practices

### 1. Secure Secret Storage

**Never commit secrets to version control:**
```bash
# .gitignore
.env
*secret*.yaml
```

**Use secret management solutions:**
- Kubernetes Secrets with RBAC
- Azure Key Vault with Managed Identity
- HashiCorp Vault
- External Secrets Operator

### 2. Principle of Least Privilege

**Azure AD Permissions:**
- Only grant required Graph API permissions (`openid`, `email`, `profile`)
- Use delegated permissions (not application permissions)
- Enable admin consent only when necessary

**Kubernetes RBAC:**
```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: open-webui-sa
  namespace: open-webui
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: open-webui-secret-reader
  namespace: open-webui
rules:
- apiGroups: [""]
  resources: ["secrets"]
  resourceNames: ["open-webui-oauth"]
  verbs: ["get"]
```

### 3. Network Security

**Enforce HTTPS:**
```bash
WEBUI_AUTH_COOKIE_SECURE=true
WEBUI_SESSION_COOKIE_SECURE=true
```

**Configure SameSite cookies:**
```bash
WEBUI_AUTH_COOKIE_SAME_SITE=lax
WEBUI_SESSION_COOKIE_SAME_SITE=lax
```

### 4. Client Secret Rotation

**Schedule regular rotation:**
1. Create new client secret in Azure AD
2. Update Kubernetes secret
3. Restart Open WebUI pods
4. Delete old secret in Azure AD after verification

**Automation example:**
```bash
# Azure CLI
az ad app credential reset --id <app-id> --years 2

# Update Kubernetes secret
kubectl create secret generic open-webui-oauth \
  --from-literal=MICROSOFT_CLIENT_SECRET=<new-secret> \
  --dry-run=client -o yaml | kubectl apply -f -

# Restart deployment
kubectl rollout restart deployment/open-webui -n open-webui
```

### 5. Audit Logging

Enable audit logging to track authentication events:

```bash
AUDIT_LOG_LEVEL=METADATA
AUDIT_LOGS_FILE_PATH=/app/data/audit.log
```

### 6. Conditional Access Policies

Configure Azure AD Conditional Access to:
- Require MFA for Open WebUI access
- Restrict access by location/IP
- Enforce compliant device requirements
- Block legacy authentication

---

## Architecture Decision Records (ADR)

### ADR-001: Use Microsoft Provider vs Generic OIDC

**Context:**
Open WebUI supports both Microsoft-specific OAuth and generic OIDC configuration.

**Decision:**
Use Microsoft provider (`MICROSOFT_*` variables) for single-tenant scenarios.

**Rationale:**
- Simpler configuration (fewer variables)
- Better integration with Microsoft Graph for profile pictures
- Automatic tenant ID handling in discovery URL
- Native support in Open WebUI codebase

**Consequences:**
- Limited to single tenant (one organization)
- Cannot use multi-tenant Azure AD apps
- For multi-tenant, must use generic OIDC with `OAUTH_CLIENT_ID`

### ADR-002: Token Storage - Server-Side Sessions

**Context:**
OAuth tokens can be stored client-side (cookies) or server-side (database).

**Decision:**
Open WebUI stores OAuth sessions server-side in database.

**Rationale:**
- More secure (tokens not exposed to client)
- Automatic token refresh without client interaction
- Centralized session management
- Easier revocation

**Consequences:**
- Requires database storage
- Scaling considerations for multi-replica deployments
- No stateless authentication

**Code Reference:**
```python
# From open_webui/utils/oauth.py (lines 1560-1576)
session = OAuthSessions.create_session(
    user_id=user.id,
    provider=provider,
    token=token,
)

response.set_cookie(
    key="oauth_session_id",
    value=session.id,
    httponly=True,
    samesite=WEBUI_AUTH_COOKIE_SAME_SITE,
    secure=WEBUI_AUTH_COOKIE_SECURE,
)
```

---

## Environment Variable Reference (Complete)

### Microsoft OAuth Variables

```bash
# Required
MICROSOFT_CLIENT_ID=<application-client-id>
MICROSOFT_CLIENT_SECRET=<client-secret>
MICROSOFT_CLIENT_TENANT_ID=<directory-tenant-id>

# Optional (with defaults)
MICROSOFT_OAUTH_SCOPE=openid email profile
MICROSOFT_REDIRECT_URI=<auto-detected>
MICROSOFT_CLIENT_LOGIN_BASE_URL=https://login.microsoftonline.com
MICROSOFT_CLIENT_PICTURE_URL=https://graph.microsoft.com/v1.0/me/photo/$value
```

### General OAuth Variables

```bash
# Signup & Accounts
ENABLE_OAUTH_SIGNUP=true
OAUTH_MERGE_ACCOUNTS_BY_EMAIL=true

# Provider Configuration
OPENID_PROVIDER_URL=https://login.microsoftonline.com/<tenant-id>/v2.0/.well-known/openid-configuration

# Timeout
OAUTH_TIMEOUT=30

# Custom Claims (advanced)
OAUTH_EMAIL_CLAIM=email
OAUTH_USERNAME_CLAIM=preferred_username
OAUTH_PICTURE_CLAIM=picture
OAUTH_SUB_CLAIM=sub

# Role & Group Management (advanced)
ENABLE_OAUTH_ROLE_MANAGEMENT=false
OAUTH_ROLES_CLAIM=roles
OAUTH_ALLOWED_ROLES=user,admin
OAUTH_ADMIN_ROLES=admin

ENABLE_OAUTH_GROUP_MANAGEMENT=false
OAUTH_GROUPS_CLAIM=groups
ENABLE_OAUTH_GROUP_CREATION=false
OAUTH_BLOCKED_GROUPS=[]
```

### Security Variables

```bash
# Cookie Security
WEBUI_AUTH_COOKIE_SECURE=true
WEBUI_AUTH_COOKIE_SAME_SITE=lax
WEBUI_SESSION_COOKIE_SECURE=true
WEBUI_SESSION_COOKIE_SAME_SITE=lax

# JWT Configuration
JWT_EXPIRES_IN=4w
WEBUI_SECRET_KEY=<generate-secure-key>

# OAuth Encryption
OAUTH_CLIENT_INFO_ENCRYPTION_KEY=<generate-secure-key>
OAUTH_SESSION_TOKEN_ENCRYPTION_KEY=<generate-secure-key>

# Persistent Config
ENABLE_OAUTH_PERSISTENT_CONFIG=false
```

---

## Integration Examples

### Docker Compose

```yaml
version: '3.8'

services:
  open-webui:
    image: ghcr.io/open-webui/open-webui:main
    container_name: open-webui
    ports:
      - "3000:8080"
    environment:
      # Microsoft OAuth
      MICROSOFT_CLIENT_ID: ${MICROSOFT_CLIENT_ID}
      MICROSOFT_CLIENT_SECRET: ${MICROSOFT_CLIENT_SECRET}
      MICROSOFT_CLIENT_TENANT_ID: ${MICROSOFT_CLIENT_TENANT_ID}

      # OAuth Configuration
      ENABLE_OAUTH_SIGNUP: "true"
      OAUTH_MERGE_ACCOUNTS_BY_EMAIL: "true"
      OPENID_PROVIDER_URL: "https://login.microsoftonline.com/${MICROSOFT_CLIENT_TENANT_ID}/v2.0/.well-known/openid-configuration"

      # Security
      WEBUI_AUTH_COOKIE_SECURE: "true"
      WEBUI_AUTH_COOKIE_SAME_SITE: "lax"
      JWT_EXPIRES_IN: "4w"

      # Optional
      MICROSOFT_REDIRECT_URI: "https://your-domain.com/oauth/microsoft/callback"
    volumes:
      - open-webui-data:/app/backend/data
    restart: unless-stopped

volumes:
  open-webui-data:
```

**.env file:**
```bash
MICROSOFT_CLIENT_ID=12345678-1234-1234-1234-123456789012
MICROSOFT_CLIENT_SECRET=your_client_secret_here
MICROSOFT_CLIENT_TENANT_ID=87654321-4321-4321-4321-210987654321
```

### Kubernetes with Kustomize

**base/deployment.yaml:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: open-webui
spec:
  replicas: 2
  selector:
    matchLabels:
      app: open-webui
  template:
    metadata:
      labels:
        app: open-webui
    spec:
      containers:
      - name: open-webui
        image: ghcr.io/open-webui/open-webui:main
        ports:
        - containerPort: 8080
        env:
        - name: MICROSOFT_CLIENT_ID
          valueFrom:
            secretKeyRef:
              name: oauth-secrets
              key: client-id
        - name: MICROSOFT_CLIENT_SECRET
          valueFrom:
            secretKeyRef:
              name: oauth-secrets
              key: client-secret
        - name: MICROSOFT_CLIENT_TENANT_ID
          valueFrom:
            secretKeyRef:
              name: oauth-secrets
              key: tenant-id
        envFrom:
        - configMapRef:
            name: oauth-config
```

**base/configmap.yaml:**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: oauth-config
data:
  ENABLE_OAUTH_SIGNUP: "true"
  OAUTH_MERGE_ACCOUNTS_BY_EMAIL: "true"
  WEBUI_AUTH_COOKIE_SECURE: "true"
  WEBUI_AUTH_COOKIE_SAME_SITE: "lax"
  JWT_EXPIRES_IN: "4w"
```

**overlays/production/kustomization.yaml:**
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

namespace: open-webui

resources:
  - ../../base

configMapGenerator:
  - name: oauth-config
    behavior: merge
    literals:
      - OPENID_PROVIDER_URL=https://login.microsoftonline.com/<tenant-id>/v2.0/.well-known/openid-configuration
      - MICROSOFT_REDIRECT_URI=https://openwebui.example.com/oauth/microsoft/callback

secretGenerator:
  - name: oauth-secrets
    envs:
      - secrets.env
```

**overlays/production/secrets.env:**
```bash
client-id=12345678-1234-1234-1234-123456789012
client-secret=your_client_secret_here
tenant-id=87654321-4321-4321-4321-210987654321
```

---

## Performance Considerations

### Token Refresh

Open WebUI automatically refreshes OAuth tokens when they're within 5 minutes of expiration.

**Code Reference:**
```python
# From open_webui/utils/oauth.py (lines 577-579)
if force_refresh or datetime.now() + timedelta(
    minutes=5
) >= datetime.fromtimestamp(session.expires_at):
```

### Scaling Considerations

**Database Sessions:**
- OAuth sessions stored in database
- Safe for multi-replica deployments
- No sticky sessions required

**Token Caching:**
- Tokens cached in memory per container
- Consider Redis for distributed caching (future enhancement)

---

## References

### Official Documentation

- [SSO (OAuth, OIDC, Trusted Header) | Open WebUI](https://docs.openwebui.com/features/auth/sso/)
- [Troubleshooting OAUTH / SSO Issues | Open WebUI](https://docs.openwebui.com/troubleshooting/sso/)
- [Microsoft identity platform and OAuth 2.0 authorization code flow | Microsoft Learn](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow)
- [OpenID Connect on the Microsoft identity platform | Microsoft Learn](https://learn.microsoft.com/en-us/entra/identity-platform/v2-protocols-oidc)
- [Configure optional claims - Microsoft identity platform | Microsoft Learn](https://learn.microsoft.com/en-us/entra/identity-platform/optional-claims)

### Community Resources

- [Single Sign-On (SSO) integration with Microsoft Azure Active Directory (Entra ID) - GitHub Discussion #13074](https://github.com/open-webui/open-webui/discussions/13074)
- [Enable Microsoft OAuth SSO authentication - GitHub Discussion #6329](https://github.com/open-webui/open-webui/discussions/6329)
- [Microsoft login option - GitHub Discussion #3784](https://github.com/open-webui/open-webui/discussions/3784)

### Azure Documentation

- [Redirect URI (reply URL) best practices and limitations | Microsoft Learn](https://learn.microsoft.com/en-us/entra/identity-platform/reply-url)
- [Access token claims reference | Microsoft Learn](https://learn.microsoft.com/en-us/entra/identity-platform/access-token-claims-reference)
- [Error AADSTS50011 redirect URI mismatch | Microsoft Learn](https://learn.microsoft.com/en-us/troubleshoot/entra/entra-id/app-integration/error-code-aadsts50011-redirect-uri-mismatch)

### Kubernetes Security

- [Secrets | Kubernetes](https://kubernetes.io/docs/concepts/configuration/secret/)
- [Azure Key Vault Provider for Secrets Store CSI Driver](https://azure.github.io/secrets-store-csi-driver-provider-azure/)
- [External Secrets Operator Documentation](https://external-secrets.io/)

---

## Appendix A: Code Structure Analysis

### OAuth Implementation Files

**Core OAuth Logic:**
- `backend/open_webui/utils/oauth.py` - Main OAuth manager classes
  - `OAuthManager` - Handles provider-specific OAuth flows (lines 807-1581)
  - `OAuthClientManager` - Manages dynamic client registration (lines 402-805)

**Configuration:**
- `backend/open_webui/config.py` - Environment variable loading and provider registration
  - Microsoft provider registration (lines 660-688)
  - `load_oauth_providers()` function (line 633)

**Environment Variables:**
- `backend/open_webui/env.py` - OAuth environment variable definitions (lines 497-511)

**Data Models:**
- `backend/open_webui/models/oauth_sessions.py` - OAuth session storage
- `backend/open_webui/models/users.py` - User OAuth mapping

**Routes:**
- `backend/open_webui/routers/auths.py` - Authentication endpoints
  - `/oauth/{provider}/login` - Initiate OAuth flow
  - `/oauth/{provider}/callback` - OAuth callback handler

### Key Functions

**Provider Registration:**
```python
# config.py lines 666-682
def microsoft_oauth_register(oauth: OAuth):
    client = oauth.register(
        name="microsoft",
        client_id=MICROSOFT_CLIENT_ID.value,
        client_secret=MICROSOFT_CLIENT_SECRET.value,
        server_metadata_url=f"{MICROSOFT_CLIENT_LOGIN_BASE_URL.value}/{MICROSOFT_CLIENT_TENANT_ID.value}/v2.0/.well-known/openid-configuration?appid={MICROSOFT_CLIENT_ID.value}",
        client_kwargs={
            "scope": MICROSOFT_OAUTH_SCOPE.value,
        },
        redirect_uri=MICROSOFT_REDIRECT_URI.value,
    )
    return client
```

**OAuth Callback Handler:**
```python
# oauth.py lines 1275-1580
async def handle_callback(self, request, provider, response):
    # Authorize access token
    token = await client.authorize_access_token(request, **auth_params)

    # Get user info
    user_data: UserInfo = await client.userinfo(token=token)

    # Extract email claim
    email = user_data.get(email_claim, "")

    # Create or update user
    # ...

    # Store OAuth session
    session = OAuthSessions.create_session(
        user_id=user.id,
        provider=provider,
        token=token,
    )
```

---

## Appendix B: Troubleshooting Checklist

### Pre-Deployment Checklist

- [ ] Azure AD app registration created
- [ ] Platform set to **Web** (not SPA)
- [ ] Redirect URI configured: `https://<domain>/oauth/microsoft/callback`
- [ ] Client secret generated and saved
- [ ] Microsoft Graph permissions added (`openid`, `email`, `profile`)
- [ ] Optional email claim configured in Token Configuration
- [ ] Admin consent granted (if required by organization)
- [ ] Environment variables configured
- [ ] `OPENID_PROVIDER_URL` set for logout support
- [ ] HTTPS enforced for production
- [ ] Secrets stored securely (not in version control)

### Post-Deployment Checklist

- [ ] Microsoft login button appears on login page
- [ ] Clicking button redirects to Microsoft login
- [ ] After authentication, redirected back to Open WebUI
- [ ] User account created or merged
- [ ] Email populated in user profile
- [ ] Logout works correctly
- [ ] Token refresh works (check logs after 1 hour)
- [ ] Multiple login/logout cycles work
- [ ] Audit logs capturing authentication events

### When Things Go Wrong

1. **Check environment variables loaded**
   ```bash
   kubectl exec <pod> -- env | grep MICROSOFT
   ```

2. **Check logs for OAuth errors**
   ```bash
   kubectl logs <pod> | grep -i oauth
   ```

3. **Verify OIDC discovery endpoint**
   ```bash
   curl https://login.microsoftonline.com/<tenant>/v2.0/.well-known/openid-configuration
   ```

4. **Test token manually** (use Postman or curl)
   - Authorization endpoint
   - Token endpoint
   - Userinfo endpoint

5. **Check Azure AD sign-in logs**
   - Azure Portal > Entra ID > Sign-in logs
   - Look for failures and error codes

6. **Enable debug logging**
   ```bash
   OAUTH_LOG_LEVEL=DEBUG
   GLOBAL_LOG_LEVEL=DEBUG
   ```

---

## Appendix C: Migration from Trusted Header Auth

### Why Migrate?

**Current (Trusted Header):**
- Requires reverse proxy to set headers
- Proxy becomes single point of trust
- Complex configuration
- Limited audit trail

**Target (Native OAuth):**
- Direct authentication with Microsoft
- Better security (no proxy trust required)
- Richer user information
- Native token refresh
- Easier troubleshooting

### Migration Steps

1. **Test in parallel**
   - Keep trusted header auth enabled
   - Add OAuth configuration
   - Test with test users

2. **Gradual rollout**
   - Communicate change to users
   - Document new login process
   - Provide support during transition

3. **Update configuration**
   ```bash
   # Remove trusted header config
   # WEBUI_AUTH_TRUSTED_EMAIL_HEADER=X-Auth-Email
   # WEBUI_AUTH_TRUSTED_NAME_HEADER=X-Auth-Name

   # Add OAuth config
   MICROSOFT_CLIENT_ID=...
   MICROSOFT_CLIENT_SECRET=...
   MICROSOFT_CLIENT_TENANT_ID=...
   ENABLE_OAUTH_SIGNUP=true
   ```

4. **Update reverse proxy**
   - Remove header injection rules
   - Keep HTTPS enforcement
   - Keep `X-Forwarded-*` headers for OAuth redirect

5. **Account migration**
   - Enable `OAUTH_MERGE_ACCOUNTS_BY_EMAIL=true`
   - Existing users matched by email
   - No data loss if emails match

6. **Cleanup**
   - Remove old authentication code
   - Update documentation
   - Archive old config

---

**Document Version:** 1.0
**Last Updated:** 2026-01-06
**Author:** Technical Research Specialist
**Open WebUI Version:** v0.6.40+
