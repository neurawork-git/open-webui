# Microsoft OAuth Quick Start Guide

## 5-Minute Setup

### Step 1: Azure AD App Registration (2 minutes)

1. **Azure Portal** → **Entra ID** → **App registrations** → **+ New registration**

2. **Configure:**
   - Name: `Open WebUI`
   - Account type: `Single tenant`
   - Redirect URI: **Web** → `https://your-domain.com/oauth/microsoft/callback`

3. **Copy these values:**
   - Application (client) ID
   - Directory (tenant) ID

4. **Create secret:**
   - **Certificates & secrets** → **+ New client secret**
   - Copy the value immediately

5. **Add permissions:**
   - **API permissions** → **+ Add permission** → **Microsoft Graph** → **Delegated**
   - Add: `openid`, `email`, `profile`
   - Click **Grant admin consent**

6. **Add email claim (CRITICAL):**
   - **Token configuration** → **+ Add optional claim** → **ID**
   - Check `email` → **Add**

### Step 2: Environment Variables (1 minute)

```bash
MICROSOFT_CLIENT_ID=<your-application-id>
MICROSOFT_CLIENT_SECRET=<your-client-secret>
MICROSOFT_CLIENT_TENANT_ID=<your-tenant-id>
ENABLE_OAUTH_SIGNUP=true
OAUTH_MERGE_ACCOUNTS_BY_EMAIL=true
OPENID_PROVIDER_URL=https://login.microsoftonline.com/<tenant-id>/v2.0/.well-known/openid-configuration
```

### Step 3: Deploy (2 minutes)

**Docker Compose:**
```yaml
services:
  open-webui:
    image: ghcr.io/open-webui/open-webui:main
    environment:
      MICROSOFT_CLIENT_ID: ${MICROSOFT_CLIENT_ID}
      MICROSOFT_CLIENT_SECRET: ${MICROSOFT_CLIENT_SECRET}
      MICROSOFT_CLIENT_TENANT_ID: ${MICROSOFT_CLIENT_TENANT_ID}
      ENABLE_OAUTH_SIGNUP: "true"
      OAUTH_MERGE_ACCOUNTS_BY_EMAIL: "true"
      OPENID_PROVIDER_URL: "https://login.microsoftonline.com/${MICROSOFT_CLIENT_TENANT_ID}/v2.0/.well-known/openid-configuration"
```

**Kubernetes:**
```bash
# Create secret
kubectl create secret generic open-webui-oauth \
  --from-literal=MICROSOFT_CLIENT_ID=<client-id> \
  --from-literal=MICROSOFT_CLIENT_SECRET=<client-secret> \
  --from-literal=MICROSOFT_CLIENT_TENANT_ID=<tenant-id>

# Add to deployment
env:
- name: MICROSOFT_CLIENT_ID
  valueFrom:
    secretKeyRef:
      name: open-webui-oauth
      key: MICROSOFT_CLIENT_ID
# ... (repeat for other variables)
```

---

## Troubleshooting (Top 3 Issues)

### 1. Email claim missing → Login fails

**Fix:** Azure Portal → App registration → Token configuration → Add optional claim → ID → email

### 2. AADSTS50011: Redirect URI mismatch

**Fix:** Ensure exact match in Azure: `https://<domain>/oauth/microsoft/callback`

### 3. AADSTS9002325: PKCE required

**Fix:** Azure Portal → App registration → Authentication → Platform = **Web** (not SPA)

---

## Verification

1. Navigate to Open WebUI
2. Login page shows "Sign in with Microsoft" button
3. Click → redirects to Microsoft login
4. After login → redirected back to Open WebUI
5. User profile shows email address

---

## Complete Documentation

For detailed setup, troubleshooting, and Kubernetes deployment: See `MICROSOFT_ENTRA_ID_OAUTH_SETUP.md`

---

## Resources

- [Open WebUI SSO Docs](https://docs.openwebui.com/features/auth/sso/)
- [Microsoft OAuth 2.0 Docs](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow)
- [Troubleshooting Guide](https://docs.openwebui.com/troubleshooting/sso/)
