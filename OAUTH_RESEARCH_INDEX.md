# Microsoft Entra ID OAuth Research - Documentation Index

## Overview

This research provides comprehensive documentation for setting up Microsoft Entra ID (Azure AD) OAuth authentication for Open WebUI, replacing the current trusted header authentication approach.

**Research Completion Date:** 2026-01-06
**Open WebUI Version:** v0.6.40+
**Status:** Production-Ready

---

## Documentation Suite

### 1. Quick Start Guide
**File:** `MICROSOFT_OAUTH_QUICKSTART.md`

**Purpose:** 5-minute setup guide for getting Microsoft OAuth working quickly

**Use when:**
- You want to get started immediately
- You have basic Azure AD knowledge
- You're doing a proof-of-concept

**Contents:**
- Minimal Azure AD configuration (3 steps)
- Essential environment variables only
- Quick deployment examples (Docker Compose, Kubernetes)
- Top 3 troubleshooting issues

---

### 2. Complete Setup Guide
**File:** `MICROSOFT_ENTRA_ID_OAUTH_SETUP.md`

**Purpose:** Comprehensive technical reference with all details

**Use when:**
- Planning production deployment
- Need to understand all configuration options
- Troubleshooting complex issues
- Designing security architecture

**Contents:**
- **Azure AD Configuration:**
  - Step-by-step app registration
  - API permissions setup
  - Optional claims configuration (email claim - CRITICAL)
  - Client secret management

- **Environment Variables:**
  - Complete reference table
  - Required vs optional variables
  - Variable explanations and defaults

- **Integration Patterns:**
  - Docker Compose examples
  - Kubernetes with native secrets
  - Kustomize overlays
  - Helm chart configuration

- **Common Gotchas (7 major issues):**
  1. AADSTS9002325: PKCE required
  2. Email claim missing
  3. Redirect URI mismatch
  4. Single-tenant limitation
  5. Logout not working
  6. Behind reverse proxy issues
  7. Token expiration issues

- **Troubleshooting:**
  - Debug logging setup
  - OIDC endpoint testing
  - Log analysis
  - Environment verification

- **Security Best Practices:**
  - Secret storage patterns
  - Least privilege principles
  - Network security
  - Client secret rotation
  - Audit logging
  - Conditional access policies

- **Architecture Decision Records:**
  - Microsoft provider vs generic OIDC
  - Server-side session storage

- **Appendices:**
  - Code structure analysis
  - Troubleshooting checklist
  - Migration from trusted header auth

---

### 3. Kubernetes Production Guide
**File:** `kubernetes/MICROSOFT_OAUTH_K8S_SETUP.md`

**Purpose:** Production-grade Kubernetes deployment patterns

**Use when:**
- Deploying to Kubernetes cluster
- Need production-ready configurations
- Implementing secret management
- Setting up monitoring and security

**Contents:**
- **3 Deployment Options:**
  1. Native Kubernetes Secrets (simplest)
  2. External Secrets Operator (recommended for production)
  3. Sealed Secrets (GitOps-friendly)

- **Complete Kubernetes Manifests:**
  - Namespace configuration
  - Secrets and ConfigMaps
  - Deployment with health probes
  - Service and Ingress (NGINX and Traefik)
  - PersistentVolumeClaim

- **Azure Integration:**
  - Azure Key Vault setup
  - Workload Identity configuration
  - Federated credentials

- **Helm Chart Deployment:**
  - Complete values.yaml
  - Installation commands
  - Upgrade procedures

- **Security Hardening:**
  - Network policies
  - Pod security standards
  - RBAC configuration

- **Monitoring:**
  - Health check endpoints
  - Prometheus ServiceMonitor
  - Grafana dashboard example

- **Scaling:**
  - HorizontalPodAutoscaler
  - Database considerations
  - Multi-replica deployment

- **Operations:**
  - Backup and restore
  - Troubleshooting guide
  - Complete example repository structure

---

## Key Research Findings

### What Open WebUI Supports

✅ **Native Microsoft OAuth provider** (separate from generic OIDC)
- Dedicated environment variables with `MICROSOFT_` prefix
- Automatic PKCE support when server advertises it
- Built-in token refresh mechanism
- Server-side session storage

✅ **Required Environment Variables:**
```bash
MICROSOFT_CLIENT_ID          # Azure app client ID
MICROSOFT_CLIENT_SECRET      # Azure app secret
MICROSOFT_CLIENT_TENANT_ID   # Azure tenant ID
ENABLE_OAUTH_SIGNUP          # Allow new user registration
OPENID_PROVIDER_URL          # For logout support
```

✅ **Code Implementation:**
- `backend/open_webui/config.py` - Provider registration (lines 660-688)
- `backend/open_webui/utils/oauth.py` - OAuth flow handling
- Supports automatic token refresh 5 minutes before expiration
- Stores tokens encrypted in database (not cookies)

### Critical Gotchas Discovered

🚨 **Email Claim Not Included by Default**
- Azure AD omits email claim for managed accounts
- MUST configure as optional claim in Token Configuration
- Without this: authentication will fail silently
- Solution documented in all guides

🚨 **PKCE Required for Modern Azure AD**
- Error: AADSTS9002325
- Must set platform to "Web" (NOT Single-Page Application)
- Open WebUI automatically handles PKCE when supported
- Code reference: `oauth.py` lines 433-444

🚨 **Redirect URI Must Match Exactly**
- Format: `https://<domain>/oauth/microsoft/callback`
- Case-sensitive, protocol matters, no trailing slash
- Configure in Azure AD app registration

🚨 **Single Tenant Limitation**
- Open WebUI's Microsoft provider supports ONE tenant only
- For multi-tenant: use generic OIDC instead
- For guest users: invite to primary tenant first

### Security Considerations

**Secret Management:**
- Use Kubernetes Secrets with RBAC
- Azure Key Vault with Workload Identity (recommended)
- External Secrets Operator for dynamic sync
- Never commit secrets to Git (use Sealed Secrets for GitOps)

**Cookie Security:**
```bash
WEBUI_AUTH_COOKIE_SECURE=true      # HTTPS only
WEBUI_AUTH_COOKIE_SAME_SITE=lax    # CSRF protection
```

**Client Secret Rotation:**
- Azure AD secrets expire (max 24 months)
- Plan rotation before expiry
- Zero-downtime process documented

---

## Integration Examples

### Docker Compose (Simple)
```yaml
services:
  open-webui:
    environment:
      MICROSOFT_CLIENT_ID: ${MICROSOFT_CLIENT_ID}
      MICROSOFT_CLIENT_SECRET: ${MICROSOFT_CLIENT_SECRET}
      MICROSOFT_CLIENT_TENANT_ID: ${MICROSOFT_CLIENT_TENANT_ID}
      ENABLE_OAUTH_SIGNUP: "true"
      OAUTH_MERGE_ACCOUNTS_BY_EMAIL: "true"
```

### Kubernetes (Production)
```yaml
# Use External Secrets Operator + Azure Key Vault
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: open-webui-oauth
spec:
  secretStoreRef:
    name: azure-keyvault
  data:
  - secretKey: MICROSOFT_CLIENT_ID
    remoteRef:
      key: microsoft-client-id
```

---

## Troubleshooting Quick Reference

| Issue | Cause | Solution | Guide Reference |
|-------|-------|----------|----------------|
| Email claim missing | Not configured in Azure AD | Add optional claim in Token Configuration | Complete Guide § Optional Claims |
| AADSTS9002325 | PKCE required | Set platform to "Web" in Azure AD | All guides § Gotcha #1 |
| AADSTS50011 | Redirect URI mismatch | Exact match required | All guides § Gotcha #3 |
| Login button missing | Env vars not loaded | Verify secret mounted correctly | K8s Guide § Troubleshooting |
| Logout not working | OPENID_PROVIDER_URL missing | Add provider URL | All guides § Gotcha #5 |
| Token expired | JWT_EXPIRES_IN too short | Increase expiration | Complete Guide § Gotcha #7 |

---

## Migration Path from Trusted Header Auth

### Current Setup
- Reverse proxy (Traefik/NGINX) sets headers
- `WEBUI_AUTH_TRUSTED_EMAIL_HEADER=X-Auth-Email`
- `WEBUI_AUTH_TRUSTED_NAME_HEADER=X-Auth-Name`
- Proxy becomes authentication enforcement point

### Target Setup
- Direct OAuth with Microsoft Entra ID
- No proxy header manipulation required
- Native token refresh and session management
- Better audit trail and security

### Migration Steps
1. Run OAuth in parallel with header auth (test users)
2. Enable `OAUTH_MERGE_ACCOUNTS_BY_EMAIL=true`
3. Communicate change to users
4. Switch authentication method
5. Remove header auth configuration
6. Update proxy config (keep X-Forwarded headers)

**Detailed migration guide:** See `MICROSOFT_ENTRA_ID_OAUTH_SETUP.md` Appendix C

---

## Performance Implications

### Token Refresh
- Automatic refresh 5 minutes before expiry
- No user interruption
- Server-side operation (not client)

### Scaling
- Server-side sessions stored in database
- Safe for multi-replica deployments
- No sticky sessions required
- Consider Redis for future caching

### Resource Usage
- Minimal overhead (one token refresh per hour typical)
- Database queries for session lookup
- Encrypted token storage

---

## Best Practices Summary

1. **Always configure email claim** in Azure AD Token Configuration
2. **Use Web platform** (not SPA) for Azure AD app registration
3. **Set OPENID_PROVIDER_URL** for logout support
4. **Enable HTTPS** and secure cookies in production
5. **Use Azure Key Vault** with Workload Identity for Kubernetes
6. **Enable audit logging** for compliance
7. **Plan secret rotation** before expiry
8. **Test in non-prod** before production rollout

---

## Source Code References

### Key Files in Open WebUI Codebase

**Configuration:**
- `backend/open_webui/config.py`
  - Lines 346-417: Microsoft OAuth variables
  - Lines 660-688: Microsoft provider registration
  - Lines 633-815: OAuth provider loader

**OAuth Logic:**
- `backend/open_webui/utils/oauth.py`
  - Lines 807-1581: `OAuthManager` class
  - Lines 1263-1273: Login handler
  - Lines 1275-1580: Callback handler
  - Lines 577-596: Token refresh logic

**Environment Variables:**
- `backend/open_webui/env.py`
  - Lines 497-511: OAuth config variables

**Data Models:**
- `backend/open_webui/models/oauth_sessions.py` - Session storage
- `backend/open_webui/models/users.py` - User OAuth mapping

**Routes:**
- `backend/open_webui/routers/auths.py` - Authentication endpoints

---

## External References

### Official Documentation
- [Open WebUI SSO Documentation](https://docs.openwebui.com/features/auth/sso/)
- [Open WebUI SSO Troubleshooting](https://docs.openwebui.com/troubleshooting/sso/)
- [Microsoft OAuth 2.0 Authorization Code Flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow)
- [Microsoft OpenID Connect Protocol](https://learn.microsoft.com/en-us/entra/identity-platform/v2-protocols-oidc)
- [Azure AD Optional Claims](https://learn.microsoft.com/en-us/entra/identity-platform/optional-claims)

### Community Resources
- [GitHub Discussion #13074 - Azure AD Integration Issues](https://github.com/open-webui/open-webui/discussions/13074)
- [GitHub Discussion #6329 - Enable Microsoft OAuth SSO](https://github.com/open-webui/open-webui/discussions/6329)
- [GitHub Discussion #3784 - Microsoft Login Option](https://github.com/open-webui/open-webui/discussions/3784)

### Kubernetes Security
- [Kubernetes Secrets](https://kubernetes.io/docs/concepts/configuration/secret/)
- [External Secrets Operator](https://external-secrets.io/)
- [Azure Workload Identity](https://azure.github.io/azure-workload-identity/)
- [Sealed Secrets](https://github.com/bitnami-labs/sealed-secrets)

---

## Decision Tree: Which Guide to Use?

```
┌─ Need quick proof-of-concept?
│  └─> MICROSOFT_OAUTH_QUICKSTART.md
│
├─ Planning production deployment?
│  ├─> Docker Compose?
│  │  └─> MICROSOFT_ENTRA_ID_OAUTH_SETUP.md (§ Docker Compose)
│  │
│  └─> Kubernetes?
│     └─> kubernetes/MICROSOFT_OAUTH_K8S_SETUP.md
│
├─ Troubleshooting specific issue?
│  ├─> Check OAUTH_RESEARCH_INDEX.md (this file) troubleshooting table
│  └─> See detailed guide for your deployment type
│
├─ Need to understand optional claims?
│  └─> MICROSOFT_ENTRA_ID_OAUTH_SETUP.md (§ Optional Claims Configuration)
│
├─ Migrating from trusted header auth?
│  └─> MICROSOFT_ENTRA_ID_OAUTH_SETUP.md (Appendix C)
│
└─ Need code-level understanding?
   └─> MICROSOFT_ENTRA_ID_OAUTH_SETUP.md (Appendix A + source references)
```

---

## Success Metrics

After implementing this research, you should achieve:

✅ **Functional:**
- Microsoft login button appears on Open WebUI login page
- Users can authenticate with organizational Microsoft accounts
- Email addresses automatically populated in user profiles
- Logout works correctly
- Token refresh happens automatically

✅ **Security:**
- No secrets in version control
- HTTPS enforced for all OAuth flows
- Secrets stored in Azure Key Vault (production)
- Audit logging enabled
- Regular secret rotation scheduled

✅ **Operations:**
- Multi-replica Kubernetes deployment working
- Health checks passing
- Monitoring configured
- Backup/restore tested
- Troubleshooting runbooks documented

---

## Feedback and Updates

This research is based on:
- Open WebUI v0.6.40+ codebase analysis
- Official Microsoft Entra ID documentation (Jan 2026)
- Community discussions and issue reports
- Production deployment best practices

**For updates or corrections:**
- Check [Open WebUI GitHub](https://github.com/open-webui/open-webui) for latest changes
- Review [Open WebUI Docs](https://docs.openwebui.com/) for official updates
- Monitor Azure AD/Entra ID changes for OAuth protocol updates

---

## Quick Command Reference

### Azure CLI
```bash
# Create app registration
az ad app create --display-name "Open WebUI"

# Create secret
az ad app credential reset --id <app-id>

# List app registrations
az ad app list --display-name "Open WebUI"
```

### Kubernetes
```bash
# Create secret
kubectl create secret generic open-webui-oauth \
  --from-literal=MICROSOFT_CLIENT_ID=<id> \
  --from-literal=MICROSOFT_CLIENT_SECRET=<secret> \
  --from-literal=MICROSOFT_CLIENT_TENANT_ID=<tenant>

# Check logs
kubectl logs -f deployment/open-webui -n open-webui | grep -i oauth

# Test endpoint
kubectl run curl-test --image=curlimages/curl -it --rm -- \
  curl http://open-webui.open-webui.svc.cluster.local/health
```

### Docker
```bash
# Check environment
docker exec <container> env | grep MICROSOFT

# Check logs
docker logs <container> | grep -i oauth
```

---

**Research Conducted By:** Technical Research Specialist
**Date:** 2026-01-06
**Version:** 1.0
**Status:** Complete & Production-Ready
