# Open WebUI Production Deployment Research Report
## Kubernetes with 100+ Concurrent Users

**Research Date:** 2026-01-05
**Target Scale:** 100+ concurrent users
**Platform:** Kubernetes
**Version Focus:** Open WebUI v0.6.x (Latest stable)

---

## Executive Summary

Open WebUI can successfully scale to 100+ concurrent users on Kubernetes with proper configuration. However, **critical architectural decisions** must be made upfront to avoid production issues:

### Critical Success Factors
1. **External PostgreSQL database is mandatory** - SQLite cannot handle multi-replica writes
2. **Redis is required** for WebSocket support and session management across replicas
3. **Shared persistent storage (RWX)** is essential for RAG uploads and generated images
4. **Consistent WEBUI_SECRET_KEY** across all replicas prevents authentication loops
5. **Resource tuning** is critical - default Helm chart has NO resource limits set

### Key Risks Identified
- **Memory leaks** with ChromaDB vector embeddings (5-13GB after processing documents)
- **Database migrations** can corrupt data if run concurrently across multiple replicas
- **WebSocket disconnections** without proper Redis configuration and sticky sessions
- **Performance degradation** at scale without proper worker/threading configuration

**Recommendation:** For 100+ users, deploy 3-5 replicas with external PostgreSQL, Redis, and dedicated vector database (PGVector or Qdrant instead of ChromaDB).

---

## 1. Architecture Considerations

### 1.1 Horizontal Scaling Patterns

#### Multi-Replica Architecture (Recommended for 100+ Users)

```
┌─────────────────────────────────────────────────────────────┐
│                     Load Balancer / Ingress                 │
│              (with sticky sessions enabled)                 │
└─────────────┬───────────────────────────────────────────────┘
              │
    ┌─────────┴─────────┬─────────────┬─────────────┐
    ▼                   ▼             ▼             ▼
┌─────────┐        ┌─────────┐   ┌─────────┐   ┌─────────┐
│ Pod 1   │        │ Pod 2   │   │ Pod 3   │   │ Pod N   │
│ Open    │        │ Open    │   │ Open    │   │ Open    │
│ WebUI   │        │ WebUI   │   │ WebUI   │   │ WebUI   │
└─────────┘        └─────────┘   └─────────┘   └─────────┘
    │                   │             │             │
    └───────────────────┴─────────────┴─────────────┘
                        │
    ┌───────────────────┼───────────────────────┐
    ▼                   ▼                       ▼
┌──────────┐      ┌──────────┐         ┌─────────────┐
│PostgreSQL│      │  Redis   │         │   Vector    │
│ Database │      │  Cluster │         │   Database  │
│          │      │          │         │ (PGVector/  │
│          │      │          │         │  Qdrant)    │
└──────────┘      └──────────┘         └─────────────┘
    │
    ▼
┌──────────────────────┐
│  Shared Storage      │
│  (RWX PVC for        │
│   RAG/images)        │
└──────────────────────┘
```

**Source:** [The SRE's Guide to High Availability Open WebUI Deployment](https://taylorwilsdon.medium.com/the-sres-guide-to-high-availability-open-webui-deployment-architecture-2ee42654eced)

#### Scaling Triggers

For 100+ concurrent users:
- **Start with:** 3 replicas (minimum for HA)
- **Scale to:** 5-7 replicas based on CPU/memory utilization
- **Trigger metrics:** CPU > 70%, Memory > 80%, or response latency > 2s

**Important:** Open WebUI's performance bottleneck shifts from CPU to I/O (database/vector operations) under high concurrency, so horizontal scaling has diminishing returns without proper database tuning.

### 1.2 Database Requirements

#### PostgreSQL vs SQLite Decision Matrix

| Deployment Type | Database | Justification |
|----------------|----------|---------------|
| Single replica | SQLite | Simpler, no external dependencies |
| Multiple replicas | **PostgreSQL (REQUIRED)** | SQLite cannot handle concurrent network writes |
| 100+ users | **PostgreSQL (REQUIRED)** | Better concurrency, connection pooling, scalability |

**Critical Gotcha #1: SQLite Corruption with Multiple Replicas**

**Issue:** SQLite was never designed for concurrent writes across network-mounted storage. Multiple Open WebUI replicas writing to the same SQLite file will cause database corruption.

**Workaround:** You **MUST** use external PostgreSQL for multi-replica deployments. This is non-negotiable.

**Reference:** [Multi-Replica Troubleshooting Guide](https://docs.openwebui.com/troubleshooting/multi-replica/)

#### PostgreSQL Configuration for 100+ Users

**Recommended Connection String:**
```bash
DATABASE_URL=postgresql+asyncpg://openwebui:password@postgres-host:5432/webui
```

**Connection Pool Settings (Environment Variables):**
```bash
# For Open WebUI application database
PGVECTOR_POOL_SIZE=20                    # Base pool size
PGVECTOR_POOL_MAX_OVERFLOW=10            # Additional connections beyond pool
PGVECTOR_POOL_TIMEOUT=30                 # Seconds to wait for connection
PGVECTOR_POOL_RECYCLE=3600               # Recycle connections every hour
```

**PostgreSQL Server Tuning (postgresql.conf):**
```ini
max_connections = 200                     # Open WebUI replicas + admin overhead
shared_buffers = 4GB                      # 25% of available RAM
effective_cache_size = 12GB               # 75% of available RAM
work_mem = 16MB                           # Per-query memory
maintenance_work_mem = 512MB              # For VACUUM operations
checkpoint_completion_target = 0.9
wal_buffers = 16MB
default_statistics_target = 100
random_page_cost = 1.1                    # SSD storage
effective_io_concurrency = 200            # SSD storage
```

**Source:** [Database Configuration Guide](https://deepwiki.com/open-webui/open-webui/17.3-database-configuration)

### 1.3 Redis/Caching Requirements

#### Redis is MANDATORY for Multi-Worker/Multi-Replica Deployments

**Why Redis is Required:**
1. **WebSocket Event Broadcasting:** Stream responses from Pod A to users connected to Pod B
2. **Session Management:** Share authentication state across replicas
3. **Configuration Synchronization:** Propagate admin panel changes via Pub/Sub
4. **Rate Limiting:** Coordinated request throttling across instances

**Redis Configuration:**

```bash
# Primary Redis connection
REDIS_URL=redis://redis:6379/0

# WebSocket-specific configuration
ENABLE_WEBSOCKET_SUPPORT=true
WEBSOCKET_MANAGER=redis
WEBSOCKET_REDIS_URL=redis://redis:6379/1    # Use separate DB number

# Optional: Redis Sentinel for HA
REDIS_SENTINEL_HOSTS=redis-a:26379,redis-b:26379
WEBSOCKET_SENTINEL_HOSTS=${REDIS_SENTINEL_HOSTS}
```

**Source:** [Redis WebSocket Support](https://docs.openwebui.com/tutorials/integrations/redis/)

**Critical Gotcha #2: Missing Redis = WebSocket Failures**

**Issue:** Without Redis, WebSocket events default to in-memory storage. Events on Replica A (e.g., LLM generation finish) are NOT broadcast to users connected to Replica B, causing:
- Chat responses never appearing
- UI appearing frozen
- Users needing to refresh page constantly

**Workaround:** Always configure `WEBSOCKET_MANAGER=redis` and `WEBSOCKET_REDIS_URL` when running multiple replicas.

**Reference:** [WebSocket Disconnects Discussion](https://github.com/open-webui/open-webui/discussions/13215)

#### Redis Resource Requirements

**For 100 Users:**
```yaml
resources:
  requests:
    memory: 256Mi
    cpu: 250m
  limits:
    memory: 512Mi
    cpu: 500m
```

**Redis Persistence:**
- For production: Enable RDB snapshots every 60 seconds
- For high availability: Use Redis Sentinel with 3+ nodes

**Source:** [Kubernetes Resource Examples](https://github.com/open-webui/open-webui/discussions/5109)

### 1.4 WebSocket Handling at Scale

#### Ingress Configuration for WebSockets

**NGINX Ingress Controller (Recommended):**

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: open-webui
  annotations:
    # WebSocket support
    nginx.ingress.kubernetes.io/websocket-services: "open-webui"

    # Session affinity (sticky sessions)
    nginx.ingress.kubernetes.io/affinity: "cookie"
    nginx.ingress.kubernetes.io/session-cookie-name: "route"
    nginx.ingress.kubernetes.io/session-cookie-expires: "172800"
    nginx.ingress.kubernetes.io/session-cookie-max-age: "172800"

    # Large file uploads
    nginx.ingress.kubernetes.io/proxy-body-size: "4096m"

    # Timeouts for long-running operations
    nginx.ingress.kubernetes.io/proxy-connect-timeout: "360"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "360"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "360"
```

**Source:** [Multi-Replica Deployment Guide](https://docs.openwebui.com/troubleshooting/multi-replica/)

**Critical Gotcha #3: CORS Issues with Load Balancers**

**Issue:** If the load balancer origin doesn't match allowed origins, WebSocket connections fail with CORS errors.

**Workaround:** Set `CORS_ALLOW_ORIGIN` to include ALL user-facing domains/IPs (semicolon-separated):

```bash
CORS_ALLOW_ORIGIN=https://chat.company.com;http://chat.company.com;http://10.0.0.100
```

**Warning:** Never use `CORS_ALLOW_ORIGIN=*` in production.

**Reference:** [Multi-Replica Troubleshooting](https://docs.openwebui.com/troubleshooting/multi-replica/)

#### Session Affinity Best Practices

While Redis enables full multi-replica WebSocket support, **session affinity (sticky sessions)** at the load balancer still provides benefits:
- Reduces WebSocket connection "jitter" when replicas restart
- Improves cache locality for user-specific data
- Minimizes cross-replica coordination overhead

**Recommendation:** Enable sticky sessions with 48-hour cookie expiry for best UX.

---

## 2. Resource Recommendations

### 2.1 CPU/Memory Per Pod

#### Baseline Resource Requirements

**Minimum Production Configuration (per replica):**
```yaml
resources:
  requests:
    memory: 1Gi
    cpu: 1000m      # 1 CPU core
  limits:
    memory: 4Gi     # Allow bursting for large operations
    cpu: 2000m      # 2 CPU cores max
```

**Source:** [Kubernetes Resource Examples](https://github.com/open-webui/helm-charts/blob/main/charts/open-webui/values.yaml)

#### Resource Scaling by Load

| Concurrent Users | Replicas | CPU Request | CPU Limit | Memory Request | Memory Limit |
|-----------------|----------|-------------|-----------|----------------|--------------|
| 1-20 users | 1 | 500m | 1000m | 512Mi | 2Gi |
| 20-50 users | 2 | 1000m | 2000m | 1Gi | 4Gi |
| 50-100 users | 3-4 | 1000m | 2000m | 2Gi | 6Gi |
| 100-200 users | 5-7 | 2000m | 4000m | 4Gi | 8Gi |

**Important Notes:**
- Memory limits should be **2-4x the request** to handle embedding operations
- CPU limits should be **1.5-2x the request** to allow burst processing
- Monitor actual usage and adjust based on workload patterns

### 2.2 Recommended Replica Counts

#### Horizontal Pod Autoscaler (HPA) Configuration

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: open-webui-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: open-webui
  minReplicas: 3              # Minimum for HA
  maxReplicas: 10             # Maximum based on infrastructure
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300    # Wait 5 min before scaling down
      policies:
      - type: Percent
        value: 50
        periodSeconds: 60
    scaleUp:
      stabilizationWindowSeconds: 60     # Scale up faster
      policies:
      - type: Percent
        value: 100
        periodSeconds: 30
```

**Why 3 Minimum Replicas?**
- Provides redundancy during rolling updates
- Tolerates single pod failure
- Distributes load for better performance
- Standard HA best practice

**Source:** [Open WebUI Features](https://docs.openwebui.com/features/)

### 2.3 Database Connection Pooling

#### Open WebUI Connection Pool Settings

**For 100 Users with 5 Replicas:**

```bash
# Application database pool (per replica)
PGVECTOR_POOL_SIZE=20                    # 20 connections per pod
PGVECTOR_POOL_MAX_OVERFLOW=10            # +10 overflow = 30 max per pod
PGVECTOR_POOL_TIMEOUT=30                 # 30s wait for connection
PGVECTOR_POOL_RECYCLE=3600               # Recycle connections hourly

# Calculation: 5 replicas × 30 max = 150 total connections
# PostgreSQL max_connections should be 200+ (150 + overhead)
```

**Critical Gotcha #4: Connection Pool Exhaustion**

**Issue:** Default pool size (SQLAlchemy defaults) is too small for high concurrency, causing `TimeoutError: QueuePool limit of size X overflow Y reached` errors.

**Workaround:** Set `PGVECTOR_POOL_SIZE` to 2-3x your expected concurrent queries per pod. For 100 users across 5 pods, expect ~20 concurrent database queries per pod during peak usage.

**Reference:** [PGVector Pool Configuration Feature](https://github.com/open-webui/open-webui/issues/15657)

#### External Connection Pooler (PgBouncer)

**For 100+ Users, Consider PgBouncer:**

```ini
# pgbouncer.ini
[databases]
webui = host=postgres-host port=5432 dbname=webui

[pgbouncer]
pool_mode = transaction              # Most efficient for web apps
max_client_conn = 500                # Total client connections
default_pool_size = 50               # Connections per database
reserve_pool_size = 10               # Reserved connections
server_idle_timeout = 600            # Close idle server connections after 10 min
```

**Benefits:**
- Reduces PostgreSQL connection overhead
- Better connection reuse across replicas
- Centralized connection management

**Open WebUI Configuration with PgBouncer:**
```bash
DATABASE_URL=postgresql+asyncpg://openwebui:password@pgbouncer:6432/webui
```

**Source:** [Database Configuration Best Practices](https://taylorwilsdon.medium.com/the-sres-guide-to-high-availability-open-webui-deployment-architecture-2ee42654eced)

---

## 3. Kubernetes Specifics

### 3.1 Ingress Configuration for WebSockets

#### Complete NGINX Ingress Example

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: open-webui
  namespace: open-webui
  annotations:
    # WebSocket support
    nginx.ingress.kubernetes.io/websocket-services: "open-webui"

    # Session affinity (sticky sessions) - CRITICAL
    nginx.ingress.kubernetes.io/affinity: "cookie"
    nginx.ingress.kubernetes.io/session-cookie-name: "open-webui-session"
    nginx.ingress.kubernetes.io/session-cookie-expires: "172800"
    nginx.ingress.kubernetes.io/session-cookie-max-age: "172800"
    nginx.ingress.kubernetes.io/session-cookie-path: "/"
    nginx.ingress.kubernetes.io/session-cookie-samesite: "Lax"

    # File upload limits
    nginx.ingress.kubernetes.io/proxy-body-size: "4096m"    # 4GB max upload

    # Timeouts for long operations (embeddings, tool calls)
    nginx.ingress.kubernetes.io/proxy-connect-timeout: "360"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "360"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "360"

    # SSL/TLS
    cert-manager.io/cluster-issuer: "letsencrypt-prod"

    # Rate limiting (optional)
    nginx.ingress.kubernetes.io/rate-limit: "100"           # 100 req/sec per IP
    nginx.ingress.kubernetes.io/limit-rps: "100"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - chat.company.com
    secretName: open-webui-tls
  rules:
  - host: chat.company.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: open-webui
            port:
              number: 80
```

**Source:** [Open WebUI Kubernetes Deployment Guide](https://autoize.com/open-webui-ollama-with-azure-kubernetes-service/)

**Critical Gotcha #5: File Upload Failures Above 1MB**

**Issue:** By default, NGINX Ingress Controller limits request body size to 1MB. File uploads above this limit fail silently (spinner keeps spinning).

**Workaround:** Set `nginx.ingress.kubernetes.io/proxy-body-size` to appropriate limit:
- For document uploads: `100m` to `1024m` (1GB)
- For image generation: `2048m` to `4096m` (4GB)
- Unlimited (not recommended): `0`

**Reference:** [Large File Upload Issues](https://github.com/open-webui/open-webui/discussions/3958)

### 3.2 Session Affinity Requirements

#### Why Session Affinity is Important

While Redis enables full statelessness, **sticky sessions still provide benefits**:

1. **Performance:** User connected to Pod A maintains connection even during scaling
2. **Cache Locality:** User-specific in-memory caches remain effective
3. **Reduced Redis Load:** Fewer cross-pod state synchronizations
4. **Better UX:** Minimizes WebSocket reconnection "jitter"

#### Configuration Options

**Cookie-Based Affinity (Recommended):**
```yaml
nginx.ingress.kubernetes.io/affinity: "cookie"
nginx.ingress.kubernetes.io/session-cookie-name: "route"
```

**IP-Based Affinity (Alternative):**
```yaml
nginx.ingress.kubernetes.io/affinity: "ip-hash"
```

**Note:** IP-hash affinity breaks with corporate NAT/proxies where many users share one IP.

**Source:** [Sticky Sessions Guide](https://kubernetes.github.io/ingress-nginx/examples/affinity/cookie/)

### 3.3 Health Check Endpoints

#### Open WebUI Health Endpoints

**Primary Health Check:**
```
GET /health
```

**Response:** `200 OK` (no authentication required)

**What it checks:**
- Web server availability
- Application initialization
- Basic database connectivity

**Source:** [Monitoring Your Open WebUI](https://docs.openwebui.com/getting-started/advanced-topics/monitoring/)

#### Kubernetes Probe Configuration

**Complete Deployment with Probes:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: open-webui
spec:
  replicas: 3
  template:
    spec:
      containers:
      - name: open-webui
        image: ghcr.io/open-webui/open-webui:0.6.41
        ports:
        - containerPort: 8080
          name: http

        # Startup probe - allows long initialization time
        startupProbe:
          httpGet:
            path: /health
            port: 8080
            scheme: HTTP
          initialDelaySeconds: 10
          periodSeconds: 5
          timeoutSeconds: 3
          failureThreshold: 30         # 30×5s = 150s max startup time
          successThreshold: 1

        # Liveness probe - restart unhealthy containers
        livenessProbe:
          httpGet:
            path: /health
            port: 8080
            scheme: HTTP
          initialDelaySeconds: 30
          periodSeconds: 10
          timeoutSeconds: 3
          failureThreshold: 3
          successThreshold: 1

        # Readiness probe - remove from service when not ready
        readinessProbe:
          httpGet:
            path: /health
            port: 8080
            scheme: HTTP
          initialDelaySeconds: 10
          periodSeconds: 5
          timeoutSeconds: 3
          failureThreshold: 2
          successThreshold: 1

        env:
        - name: WEBUI_SECRET_KEY
          valueFrom:
            secretKeyRef:
              name: open-webui-secrets
              key: secret-key
        # ... other environment variables
```

**Best Practices:**
- Use **startup probe** with long `failureThreshold` for initial database migrations
- Use **liveness probe** with conservative settings (avoid pod thrashing)
- Use **readiness probe** aggressively to remove slow pods from service

**Source:** [Kubernetes Liveness/Readiness Probes](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/)

#### Advanced Health Monitoring

**For Deeper Health Checks:**
```
GET /api/system/status
```

**Requires:** Authentication token

**Returns:** System status including model availability

**Use Case:** External monitoring systems that can authenticate and verify end-to-end functionality.

**Source:** [API Endpoints Documentation](https://deepwiki.com/open-webui/docs/9.3-api-endpoints-and-integration)

### 3.4 PersistentVolume Requirements

#### Storage Architecture for Multi-Replica Deployments

**Two Storage Types Needed:**

1. **Application Data (RWX - ReadWriteMany)**
   - Uploaded RAG documents
   - Generated images
   - User file attachments
   - Must be shared across all replicas

2. **Database Data (RWO - ReadWriteOnce)**
   - Only if using SQLite (not recommended for 100+ users)
   - PostgreSQL should be external service

**Critical Gotcha #6: Missing RAG Files with RWO Storage**

**Issue:** If you use `ReadWriteOnce` (RWO) storage in multi-replica deployment, uploaded files only exist on the replica that received them. Users get "file not found" errors when routed to different replicas.

**Workaround:** You **MUST** use `ReadWriteMany` (RWX) storage for multi-replica deployments:
- **Cloud:** AWS EFS, Azure Files, GCP Filestore
- **On-Prem:** NFS, GlusterFS, CephFS, Longhorn

**Reference:** [Kubernetes Data Persistence Issue](https://github.com/open-webui/open-webui/discussions/742)

#### PersistentVolumeClaim Configuration

**Application Data PVC (Shared Storage):**

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: open-webui-data
spec:
  accessModes:
    - ReadWriteMany           # CRITICAL for multi-replica
  resources:
    requests:
      storage: 50Gi           # Adjust based on expected RAG documents
  storageClassName: nfs-client   # Use appropriate storage class
```

**Mount Configuration:**

```yaml
spec:
  template:
    spec:
      containers:
      - name: open-webui
        volumeMounts:
        - name: data
          mountPath: /app/backend/data
      volumes:
      - name: data
        persistentVolumeClaim:
          claimName: open-webui-data
```

#### Storage Size Recommendations

| Users | RAG Usage | Recommended Size | Storage Class |
|-------|-----------|------------------|---------------|
| 1-20 | Light | 5-10Gi | RWO (single replica) |
| 20-50 | Moderate | 20-50Gi | RWX (multi-replica) |
| 50-100 | Heavy | 50-100Gi | RWX (multi-replica) |
| 100-200 | Enterprise | 100-200Gi | RWX + backup strategy |

**Factors Affecting Storage Size:**
- Average document size (PDFs, images)
- Number of RAG collections
- Image generation frequency
- Retention policy

**Source:** [Open WebUI Kubernetes Storage Guide](https://medium.com/@r.kosse/run-open-webui-with-kubernetes-be5fad2a7938)

#### Storage Performance Considerations

**IOPS Requirements:**
- **Minimum:** 3000 IOPS (standard SSD)
- **Recommended:** 5000-10000 IOPS (premium SSD)
- **High Load:** 10000+ IOPS (provisioned IOPS)

**Latency Requirements:**
- **Read Latency:** <5ms
- **Write Latency:** <10ms

**Why Performance Matters:**
- Vector database operations are I/O intensive
- Document chunking/embedding writes many small files
- User uploads need fast write acknowledgment

---

## 4. Known Gotchas

### Gotcha #1: ChromaDB Memory Leaks with Large Document Collections

**Issue Description:**
Open WebUI's default vector database (ChromaDB) exhibits severe memory leaks when processing large document collections. Memory consumption grows to 5-13GB after uploading 2,000-3,500 documents and never returns to baseline, even after embedding completes.

**Technical Details:**
- `ChromaDB.init_index()` holds ~13GB RAM after 2,000 documents
- Memory accumulates at ~2.5GB per 1,000 documents
- Python process never releases memory (no automatic garbage collection)
- Issue pronounced with large files (2-3MB each)

**Impact:**
- Out-of-memory kills in Kubernetes (OOMKilled)
- Pod restarts during batch uploads
- Cannot process large document sets

**Root Cause:**
Open WebUI's vector embedding pipeline lacks automatic memory cleanup. Temporary objects, buffers, and cached data accumulate without release after task completion.

**Workarounds:**

**Option 1: Switch to PGVector (Recommended)**
```bash
# Environment variables
VECTOR_DB=pgvector
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/webui
```

**Benefits:**
- No in-memory index accumulation
- Leverages PostgreSQL's connection pooling
- Better suited for production scale

**Option 2: Switch to Qdrant**
```bash
VECTOR_DB=qdrant
QDRANT_URL=http://qdrant:6333
ENABLE_QDRANT_MULTITENANCY_MODE=true    # Reduces RAM usage
```

**Benefits:**
- Swapping to Qdrant resolved memory leak for some users
- Multitenancy mode consolidates collections (lower RAM)
- Dedicated vector database service

**Option 3: Use External Embedding Engine**
```bash
RAG_EMBEDDING_ENGINE=ollama    # Use external Ollama instead of local SentenceTransformers
```

**Benefits:**
- Reduces Open WebUI pod memory from 1GB+ to ~200MB
- Offloads ML model memory to Ollama pod
- Recommended for RAM-constrained environments

**Monitoring:**
```bash
# Monitor memory usage
kubectl top pod -l app=open-webui

# Check for OOMKilled events
kubectl get events --sort-by='.lastTimestamp' | grep OOM
```

**References:**
- [Memory Leak When Embedding Discussion #8598](https://github.com/open-webui/open-webui/discussions/8598)
- [Memory Usage of WebUI Discussion #2583](https://github.com/open-webui/open-webui/discussions/2583)
- [Reduce RAM Usage Guide](https://docs.openwebui.com/tutorials/tips/reduce-ram-usage/)

---

### Gotcha #2: Database Migration Corruption with Concurrent Replicas

**Issue Description:**
Running database migrations concurrently across multiple replicas during upgrades causes database schema corruption, leading to application failure.

**Technical Details:**
- Alembic migrations are NOT idempotent when run in parallel
- Multiple pods attempt to apply same migration simultaneously
- Results in deadlocks, constraint violations, or corrupted schema
- Affects both PostgreSQL and SQLite (but SQLite is worse)

**Impact:**
- Complete application outage
- Data loss if migrations partially succeed
- Requires manual database recovery

**Root Cause:**
Open WebUI runs Alembic migrations on startup. With multiple replicas, all pods attempt migrations at boot, creating race conditions.

**Workaround (MANDATORY for Updates):**

**Safe Update Procedure:**

```bash
# Step 1: Scale down to single replica
kubectl scale deployment/open-webui --replicas=1

# Step 2: Apply update
kubectl set image deployment/open-webui \
  open-webui=ghcr.io/open-webui/open-webui:0.6.41

# Step 3: Wait for pod ready (migrations complete)
kubectl wait --for=condition=ready pod \
  -l app=open-webui --timeout=300s

# Step 4: Verify application health
kubectl exec -it deployment/open-webui -- \
  curl -f http://localhost:8080/health

# Step 5: Scale back to desired replicas
kubectl scale deployment/open-webui --replicas=5
```

**Helm Chart Automation:**

Create a pre-upgrade hook to automate scaling:

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: open-webui-pre-upgrade
  annotations:
    "helm.sh/hook": pre-upgrade
    "helm.sh/hook-weight": "-5"
    "helm.sh/hook-delete-policy": hook-succeeded
spec:
  template:
    spec:
      serviceAccountName: open-webui-upgrade
      containers:
      - name: scale-down
        image: bitnami/kubectl:latest
        command:
        - /bin/sh
        - -c
        - |
          kubectl scale deployment/open-webui --replicas=1
          kubectl wait --for=condition=ready pod -l app=open-webui --timeout=300s
      restartPolicy: OnFailure
```

**Alternative: Init Container with Migration Lock**

Advanced users can implement a migration lock using PostgreSQL advisory locks to prevent concurrent migrations.

**References:**
- [Multi-Replica Update Warning](https://docs.openwebui.com/troubleshooting/multi-replica/)
- [Update Process Discussion](https://github.com/open-webui/open-webui/discussions/5109)

---

### Gotcha #3: WebSocket Scaling Issues Without Redis

**Issue Description:**
WebSocket events fail to propagate across replicas when Redis is not configured, causing chat responses to never appear for users connected to different pods.

**Technical Details:**
- Without Redis, WebSocket manager defaults to in-memory storage
- Events emitted on Pod A stored only in Pod A's memory
- User connected to Pod B never receives events from Pod A
- Results in "frozen" UI with perpetual loading spinners

**User Experience Impact:**
- Chat messages never show responses
- Real-time streaming appears broken
- Users must refresh page (potentially routing to different pod)
- Inconsistent behavior ("works sometimes")

**Root Cause:**
Open WebUI's WebSocket implementation requires shared event bus for multi-replica deployments. In-memory storage is only suitable for single-replica deployments.

**Workaround:**

**Required Configuration:**
```bash
# Enable WebSocket support
ENABLE_WEBSOCKET_SUPPORT=true

# Use Redis as WebSocket manager
WEBSOCKET_MANAGER=redis
WEBSOCKET_REDIS_URL=redis://redis:6379/1    # Use separate DB number

# Also set general Redis URL for session management
REDIS_URL=redis://redis:6379/0
```

**Kubernetes Deployment:**
```yaml
env:
- name: ENABLE_WEBSOCKET_SUPPORT
  value: "true"
- name: WEBSOCKET_MANAGER
  value: "redis"
- name: WEBSOCKET_REDIS_URL
  value: "redis://redis-service:6379/1"
- name: REDIS_URL
  value: "redis://redis-service:6379/0"
```

**Verification:**
```bash
# Check Redis connections from Open WebUI
kubectl exec -it deployment/open-webui -- \
  redis-cli -h redis-service -p 6379 CLIENT LIST

# Monitor WebSocket events
kubectl logs -f deployment/open-webui | grep -i websocket
```

**References:**
- [WebSocket Disconnects Discussion #13215](https://github.com/open-webui/open-webui/discussions/13215)
- [Multi-Replica Requirements](https://docs.openwebui.com/troubleshooting/multi-replica/)

---

### Gotcha #4: Thread Pool Exhaustion Under High Concurrency

**Issue Description:**
Default thread pool size of 40 threads becomes a critical bottleneck under high concurrency, causing request timeouts and slow responses.

**Technical Details:**
- FastAPI/AnyIO uses thread pool for blocking I/O operations
- Default pool size: 40 threads (hardcoded when `THREAD_POOL_SIZE=0`)
- Each concurrent user request consumes 1+ threads
- With 100+ concurrent users, thread pool exhausts quickly
- Results in `RuntimeError: thread pool exhausted` errors

**Impact:**
- HTTP 500 errors during peak usage
- Slow response times (queued requests)
- User timeouts and frustration

**Root Cause:**
Open WebUI performs many blocking I/O operations (database queries, vector searches, file I/O) that rely on thread pool. Default sizing assumes low concurrency.

**Workaround:**

**For 100+ Concurrent Users:**
```bash
THREAD_POOL_SIZE=1000    # Scale to 10x concurrent users
```

**Calculation Formula:**
```
THREAD_POOL_SIZE = (concurrent_users × 2) + (replicas × 50)

Example: 100 users, 5 replicas
THREAD_POOL_SIZE = (100 × 2) + (5 × 50) = 450 minimum
Recommended: 1000 (buffer for spikes)
```

**Kubernetes ConfigMap:**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: open-webui-config
data:
  THREAD_POOL_SIZE: "1000"
```

**Monitoring Thread Pool Usage:**
```python
# Add to Open WebUI custom monitoring
import anyio
pool_size = anyio.to_thread.current_default_thread_limiter().total_tokens
used_threads = pool_size - anyio.to_thread.current_default_thread_limiter().available_tokens
print(f"Thread pool usage: {used_threads}/{pool_size}")
```

**References:**
- [Environment Variable Configuration](https://docs.openwebui.com/getting-started/env-configuration/)
- [Performance Tuning Guide](https://deepwiki.com/open-webui/docs/8.3-performance-tuning)

---

### Gotcha #5: Inconsistent WEBUI_SECRET_KEY Causes Authentication Loops

**Issue Description:**
Users experience infinite login loops, getting logged out when load balancer routes them to different replicas.

**Technical Details:**
- Each replica generates random `WEBUI_SECRET_KEY` on startup if not explicitly set
- Session tokens (JWTs) are signed with replica-specific keys
- Token signed by Pod A is invalid on Pod B (different key)
- User authenticated on Pod A gets "invalid token" error on Pod B
- Browser redirects to login, creating infinite loop

**User Experience:**
- Can login successfully sometimes (routed to same pod)
- Randomly logged out mid-session
- "Invalid or expired token" errors
- Works when testing single pod, breaks at scale

**Root Cause:**
Docker images generate random `WEBUI_SECRET_KEY` for security. This is safe for single-instance deployments but breaks multi-replica setups.

**Workaround (MANDATORY for Multi-Replica):**

**Generate Secure Secret:**
```bash
# Generate 32-byte random secret
openssl rand -base64 32
# Output: K8s3mP9nQ5tW2xY6zA1bC4dE7fG0hI3j

# Or use Python
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

**Kubernetes Secret:**
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: open-webui-secrets
type: Opaque
stringData:
  secret-key: "K8s3mP9nQ5tW2xY6zA1bC4dE7fG0hI3j"
```

**Deployment Configuration:**
```yaml
env:
- name: WEBUI_SECRET_KEY
  valueFrom:
    secretKeyRef:
      name: open-webui-secrets
      key: secret-key
```

**Verification:**
```bash
# Check all pods use same secret
kubectl exec -it deployment/open-webui -- env | grep WEBUI_SECRET_KEY

# Should return identical value across all pods
```

**Important:** Changing `WEBUI_SECRET_KEY` invalidates ALL existing user sessions. Plan key rotation during maintenance windows.

**References:**
- [Multi-Replica Troubleshooting](https://docs.openwebui.com/troubleshooting/multi-replica/)
- [Environment Variables Guide](https://docs.openwebui.com/getting-started/env-configuration/)

---

### Gotcha #6: Uvicorn Worker Configuration Breaks Without Redis

**Issue Description:**
Setting `UVICORN_WORKERS > 1` or `WEB_CONCURRENCY > 1` causes chat streaming to fail without proper Redis configuration.

**Technical Details:**
- Uvicorn workers are separate processes with isolated memory
- Without Redis, session state is in-memory per worker
- Worker A cannot access sessions created by Worker B
- WebSocket connections fail across workers
- LLM streaming responses never reach frontend

**Impact:**
- Chat responses appear frozen
- Streaming stops mid-response
- Document upload progress not shown
- Random failures depending on which worker processes request

**Root Cause:**
Uvicorn workers don't share memory. Multi-worker deployments require external state store (Redis).

**Workaround:**

**Configuration for Multi-Worker:**
```bash
# Set workers (2x CPU cores recommended)
UVICORN_WORKERS=4              # Or use WEB_CONCURRENCY=4

# MUST configure Redis for multi-worker
REDIS_URL=redis://redis:6379/0
WEBSOCKET_MANAGER=redis
WEBSOCKET_REDIS_URL=redis://redis:6379/1
ENABLE_WEBSOCKET_SUPPORT=true

# Shared secret key (also required)
WEBUI_SECRET_KEY=your-secret-key
```

**Worker Count Recommendations:**

| CPU Cores | Recommended Workers | Rationale |
|-----------|---------------------|-----------|
| 2 cores | 2-3 workers | 1-1.5x cores |
| 4 cores | 4-6 workers | 1-1.5x cores |
| 8 cores | 8-12 workers | 1-1.5x cores |
| 16+ cores | Use horizontal scaling instead | Better resource isolation |

**Important:** For Kubernetes, prefer horizontal scaling (more replicas) over vertical scaling (more workers per replica):
- Better fault tolerance
- Easier rolling updates
- More granular autoscaling

**Update Safety with Workers:**
```bash
# MUST scale to 1 worker during updates
UVICORN_WORKERS=1

# Update application
# ...

# Then restore worker count
UVICORN_WORKERS=4
```

**References:**
- [Adding Uvicorn Workers Discussion #9032](https://github.com/open-webui/open-webui/discussions/9032)
- [Uvicorn Workers Configuration Feature #12286](https://github.com/open-webui/open-webui/issues/12286)

---

### Gotcha #7: CORS Configuration Prevents Cross-Origin Access

**Issue Description:**
WebSocket connections fail with CORS errors when Open WebUI is accessed through reverse proxy or different domain than backend.

**Technical Details:**
- Browser enforces CORS policy on WebSocket connections
- Default `CORS_ALLOW_ORIGIN` is restrictive
- Load balancer/ingress adds new origin header
- Open WebUI rejects WebSocket handshake as unauthorized origin

**Error Messages:**
```
Access to XMLHttpRequest blocked by CORS policy: No 'Access-Control-Allow-Origin' header
WebSocket connection to 'wss://chat.company.com/ws' failed: Error during WebSocket handshake
```

**Impact:**
- WebSocket connections fail entirely
- Chat streaming doesn't work
- Real-time updates break
- Users see "connection failed" errors

**Root Cause:**
Open WebUI must explicitly whitelist all domains/IPs used to access the application.

**Workaround:**

**Configure All Access Points:**
```bash
# Semicolon-separated list of allowed origins
CORS_ALLOW_ORIGIN=https://chat.company.com;http://chat.company.com;http://10.0.0.100;http://localhost:3000

# Include:
# - Production HTTPS domain
# - HTTP fallback (if applicable)
# - Internal IPs (for health checks)
# - Development URLs (for testing)
```

**Production Best Practice:**
```bash
# Use environment-specific origins
CORS_ALLOW_ORIGIN=https://chat.company.com;https://chat-staging.company.com
```

**Common Mistakes:**

❌ **NEVER use wildcard in production:**
```bash
CORS_ALLOW_ORIGIN=*    # SECURITY RISK - allows any origin
```

✅ **Always use explicit list:**
```bash
CORS_ALLOW_ORIGIN=https://chat.company.com;https://api.company.com
```

**Debugging CORS Issues:**
```bash
# Check browser console for CORS errors
# Chrome DevTools > Console

# Test CORS headers
curl -H "Origin: https://chat.company.com" \
     -H "Access-Control-Request-Method: GET" \
     -X OPTIONS \
     https://your-backend/health -v
```

**References:**
- [Multi-Replica CORS Configuration](https://docs.openwebui.com/troubleshooting/multi-replica/)
- [Environment Variables Guide](https://docs.openwebui.com/getting-started/env-configuration/)

---

### Gotcha #8: Reverse Proxy Timeout Kills Long-Running Operations

**Issue Description:**
Long-running operations (document embedding, web search tools) timeout after 100 seconds when Open WebUI is behind reverse proxy.

**Technical Details:**
- Default reverse proxy timeout: 60-100 seconds
- Cloudflare Free: 100 second hard limit
- NGINX default: 60 seconds
- Document embedding can take 5-10 minutes for large files
- Web search tools may exceed timeout

**Impact:**
- Document uploads fail mid-process
- Tool use (web search, code execution) fails
- Users see generic "request timeout" errors
- Incomplete operations leave database in inconsistent state

**Root Cause:**
Reverse proxies terminate idle connections to prevent resource exhaustion. Open WebUI's long-running operations exceed these timeouts.

**Workaround:**

**Option 1: Increase Proxy Timeouts (Recommended)**

**NGINX Ingress:**
```yaml
annotations:
  nginx.ingress.kubernetes.io/proxy-connect-timeout: "600"
  nginx.ingress.kubernetes.io/proxy-read-timeout: "600"
  nginx.ingress.kubernetes.io/proxy-send-timeout: "600"
```

**NGINX Config (non-Kubernetes):**
```nginx
location / {
    proxy_connect_timeout 600s;
    proxy_send_timeout 600s;
    proxy_read_timeout 600s;
}
```

**Cloudflare (Enterprise Only):**
- Free tier: 100s hard limit (cannot increase)
- Enterprise: Contact support to increase

**Option 2: Implement Client-Side Polling**

For operations that exceed any timeout limit:
```bash
# Enable background job processing
ENABLE_BACKGROUND_JOBS=true

# Client polls for completion status
# /api/jobs/{job_id}/status
```

**Option 3: Bypass Cloudflare for Upload Endpoint**

Create direct DNS record for uploads:
```
uploads.company.com → Direct to origin (bypass Cloudflare)
chat.company.com → Via Cloudflare (proxied)
```

**Monitoring Timeouts:**
```bash
# Check timeout errors in logs
kubectl logs -f deployment/open-webui | grep -i timeout

# Monitor request duration
# Prometheus metric: http_request_duration_seconds
```

**References:**
- [API Timeout Issue #16747](https://github.com/open-webui/open-webui/issues/16747)
- [Ingress Timeout Configuration](https://autoize.com/open-webui-ollama-with-azure-kubernetes-service/)

---

### Gotcha #9: PGVector Null Byte Errors Cause Memory Leaks

**Issue Description:**
When using PostgreSQL with PGVector extension, attaching web pages can create null bytes in embeddings, causing memory leaks and eventual Out-of-Memory crashes.

**Technical Details:**
- Web page parsing sometimes returns empty strings
- Empty strings converted to embeddings contain null bytes (`\x00`)
- PostgreSQL PGVector doesn't handle null bytes gracefully
- Open WebUI doesn't sanitize empty embedding results
- Memory accumulates from failed embedding operations

**Error Messages:**
```
ValueError: A string literal cannot contain NUL (0x00) characters
psycopg2.errors.StringDataRightTruncation: invalid byte sequence
```

**Impact:**
- VM/pod crashes with OOM after ~12 web page attachments
- Database connection errors
- Cannot use "Attach Web Page" feature
- Unpredictable memory growth

**Root Cause:**
Improper sanitization of search results before embedding, specifically when switching from ChromaDB to PGVector.

**Workaround:**

**Option 1: Use Qdrant Instead (Recommended)**
```bash
VECTOR_DB=qdrant
QDRANT_URL=http://qdrant:6333
ENABLE_QDRANT_MULTITENANCY_MODE=true
```

Qdrant handles edge cases better and doesn't have null byte issues.

**Option 2: Sanitize Input (Code Patch Required)**

This was addressed in recent Open WebUI versions. Ensure you're running v0.6.30 or later.

**Option 3: Increase Memory Limits Temporarily**

While fixing underlying issue:
```yaml
resources:
  limits:
    memory: 8Gi    # Temporarily increase while fixing
```

**Verification:**
```bash
# Monitor memory growth
watch kubectl top pod -l app=open-webui

# Check for null byte errors
kubectl logs deployment/open-webui | grep -i "null\|NUL\|0x00"
```

**References:**
- [Memory Leak with Attach Web Page Issue #19867](https://github.com/open-webui/open-webui/issues/19867)
- [PGVector Configuration Guide](https://www.heyitworks.tech/blog/openwebui-with-postgres-and-qdrant-a-setup-guide/)

---

### Gotcha #10: Performance Degradation at 1000+ Users Without vLLM

**Issue Description:**
When approaching 1000+ concurrent users, Ollama backend becomes bottleneck causing severe performance degradation (1 token per 2 seconds, 10-20 second delays before responses).

**Technical Details:**
- Ollama designed for single-user/low-concurrency scenarios
- Limited batch inference capabilities
- Each request processed sequentially
- At 200+ requests/second, Ollama queue grows indefinitely
- Frontend appears "frozen" during high load

**Impact:**
- UI slowdowns (10-20 seconds to register message send)
- Extremely slow token streaming (1 token per 2 seconds)
- Timeouts and failed requests
- Poor user experience at scale

**Root Cause:**
Ollama prioritizes simplicity over high-throughput serving. It's not optimized for parallel inference from many users.

**Workaround:**

**Option 1: Switch to vLLM (Recommended for 100+ Users)**

```bash
# Open WebUI configuration
OPENAI_API_BASE_URL=http://vllm-service:8000/v1
OPENAI_API_KEY=dummy    # vLLM doesn't require auth by default
```

**vLLM Deployment:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: vllm
spec:
  replicas: 1
  template:
    spec:
      containers:
      - name: vllm
        image: vllm/vllm-openai:latest
        args:
        - --model
        - mistralai/Mistral-7B-Instruct-v0.3
        - --max-model-len
        - "8192"
        - --max-num-seqs
        - "256"              # Critical for concurrency
        - --gpu-memory-utilization
        - "0.95"
        resources:
          limits:
            nvidia.com/gpu: 1
```

**Benefits of vLLM:**
- Continuous batching (serves multiple users simultaneously)
- Paged attention (efficient memory usage)
- 10-20x higher throughput than Ollama
- Better suited for production scale

**Option 2: Use OpenAI/Anthropic API**

For mission-critical deployments, external APIs provide:
- Unlimited scalability
- Professional SLAs
- No infrastructure management
- Pay-per-token pricing

**Option 3: Deploy Multiple Ollama Instances with Load Balancing**

```yaml
# Open WebUI load balances across multiple Ollama backends
OLLAMA_BASE_URLS=http://ollama-1:11434;http://ollama-2:11434;http://ollama-3:11434
```

Less efficient than vLLM, but works if you must use Ollama.

**Performance Benchmarks (Rough Estimates):**

| Backend | Concurrent Users | Avg Response Time | Throughput |
|---------|------------------|-------------------|------------|
| Ollama (single) | <20 | <2s | Low |
| Ollama (3 replicas) | 50-75 | 2-5s | Medium |
| vLLM (A100) | 200-500 | <1s | High |
| OpenAI API | Unlimited | <500ms | Very High |

**References:**
- [Large-Scale Deployment Discussion #7771](https://github.com/open-webui/open-webui/discussions/7771)
- [vLLM Documentation](https://docs.vllm.ai/)

---

### Gotcha Summary Table

| # | Gotcha | Impact | Severity | Workaround Complexity |
|---|--------|--------|----------|----------------------|
| 1 | ChromaDB Memory Leaks | OOMKilled pods | 🔴 Critical | Medium (switch to PGVector) |
| 2 | Concurrent Migration Corruption | Data loss | 🔴 Critical | Low (scale down before update) |
| 3 | WebSocket Failures Without Redis | Broken streaming | 🔴 Critical | Low (configure Redis) |
| 4 | Thread Pool Exhaustion | Slow responses | 🟠 High | Low (set env var) |
| 5 | Inconsistent SECRET_KEY | Auth loops | 🔴 Critical | Low (set secret) |
| 6 | Uvicorn Workers Without Redis | Broken features | 🟠 High | Low (configure Redis) |
| 7 | CORS Configuration | WebSocket failure | 🟠 High | Low (set CORS origins) |
| 8 | Reverse Proxy Timeouts | Failed uploads | 🟡 Medium | Medium (adjust timeouts) |
| 9 | PGVector Null Bytes | Memory leaks | 🟠 High | Medium (switch to Qdrant) |
| 10 | Ollama at Scale | Poor performance | 🟠 High | High (deploy vLLM) |

---

## 5. Monitoring & Observability

### 5.1 Prometheus Metrics

#### OpenTelemetry Integration (Built-in)

Open WebUI includes native OpenTelemetry (OTel) support for comprehensive observability.

**Configuration:**
```bash
# Enable OpenTelemetry
ENABLE_OTEL=true
ENABLE_OTEL_TRACES=true
ENABLE_OTEL_METRICS=true

# OTLP Exporter (gRPC)
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
OTEL_SERVICE_NAME=open-webui

# Optional: Export directly to Prometheus
OTEL_EXPORTER_PROMETHEUS_PORT=9090
```

**Source:** [OpenTelemetry Configuration](https://docs.openwebui.com/getting-started/advanced-topics/monitoring/otel/)

#### Available Metrics

**HTTP Request Metrics:**
```
http_server_requests_total              # Total HTTP requests
http_server_request_duration_seconds    # Request latency histogram
http_server_active_requests             # Current active requests
http_client_duration                    # Outbound API call duration
```

**Database Metrics:**
```
db_query_duration_seconds               # Database query latency
db_connection_pool_size                 # Current connection pool size
db_connection_pool_usage                # Active connections
```

**WebSocket Metrics:**
```
websocket_connections_active            # Current WebSocket connections
websocket_messages_sent_total           # Total messages sent
websocket_messages_received_total       # Total messages received
```

**Custom Application Metrics:**
```
openwebui_chats_created_total           # Total chats created
openwebui_messages_sent_total           # Total messages sent
openwebui_rag_documents_indexed_total   # RAG documents indexed
openwebui_embeddings_generated_total    # Embeddings generated
```

**Source:** [OpenTelemetry Integration Discussion #12344](https://github.com/open-webui/open-webui/discussions/12344)

#### Prometheus ServiceMonitor (Kubernetes)

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: open-webui
  labels:
    app: open-webui
spec:
  selector:
    matchLabels:
      app: open-webui
  endpoints:
  - port: metrics
    interval: 15s
    path: /metrics
    scheme: http
```

#### Grafana Dashboard

**Official Dashboard Available:**
- [Grafana Dashboard for Open WebUI #22867](https://grafana.com/grafana/dashboards/22867-grafana-dashboard-for-open-webui/)

**Key Panels:**
- Request rate and latency
- Error rate (4xx/5xx)
- WebSocket connection count
- Database query performance
- Memory and CPU usage
- Chat/message throughput

### 5.2 Logging Best Practices

#### Log Level Configuration

```bash
# Global log level
GLOBAL_LOG_LEVEL=INFO    # Options: DEBUG, INFO, WARNING, ERROR, CRITICAL

# Audit logging (detailed request/response logging)
AUDIT_LOG_LEVEL=METADATA  # Options: NONE, METADATA, REQUEST, REQUEST_RESPONSE

# Limit body size in audit logs (prevents log flooding)
MAX_BODY_LOG_SIZE=2048    # Bytes (2KB)
```

**Production Recommendations:**

| Environment | GLOBAL_LOG_LEVEL | AUDIT_LOG_LEVEL | MAX_BODY_LOG_SIZE |
|-------------|------------------|-----------------|-------------------|
| Development | DEBUG | REQUEST_RESPONSE | 10240 (10KB) |
| Staging | INFO | REQUEST | 4096 (4KB) |
| Production | WARNING | METADATA | 2048 (2KB) |

**Why Conservative Logging in Production:**
- High verbosity increases disk I/O and storage costs
- `REQUEST_RESPONSE` logging logs entire chat histories (privacy concern)
- `DEBUG` level produces gigabytes of logs per day at scale

**Source:** [Environment Variables Configuration](https://docs.openwebui.com/getting-started/env-configuration/)

#### Structured Logging with JSON

**Configure JSON Logging for Better Parsing:**

```bash
# Enable JSON structured logs (if supported by version)
LOG_FORMAT=json
```

**Example Log Entry:**
```json
{
  "timestamp": "2026-01-05T10:30:45.123Z",
  "level": "INFO",
  "service": "open-webui",
  "pod": "open-webui-abc123",
  "user_id": "user-xyz",
  "message": "Chat message processed",
  "duration_ms": 245,
  "model": "llama3",
  "tokens": 150
}
```

#### Log Aggregation Architecture

**Kubernetes Logging Stack:**

```
┌──────────────────────────────────────────────┐
│              Open WebUI Pods                 │
│   (JSON logs to stdout/stderr)               │
└─────────┬────────────────────────────────────┘
          │
          ▼
┌──────────────────────────────────────────────┐
│         Fluent Bit / Fluentd                 │
│   (DaemonSet on each node)                   │
│   - Collects container logs                  │
│   - Parses JSON                               │
│   - Adds Kubernetes metadata                  │
└─────────┬────────────────────────────────────┘
          │
          ▼
┌──────────────────────────────────────────────┐
│             Loki / Elasticsearch             │
│   (Centralized log storage)                  │
└─────────┬────────────────────────────────────┘
          │
          ▼
┌──────────────────────────────────────────────┐
│                  Grafana                      │
│   (Log visualization and querying)           │
└──────────────────────────────────────────────┘
```

#### Critical Log Queries

**High Error Rate:**
```logql
# Loki query
{app="open-webui"} |= "ERROR" | json | line_format "{{.message}}"
```

**Slow Database Queries:**
```logql
{app="open-webui"} | json | duration_ms > 1000
```

**Authentication Failures:**
```logql
{app="open-webui"} |= "authentication failed" | json | count_over_time(1m)
```

**WebSocket Connection Issues:**
```logql
{app="open-webui"} |= "websocket" |= "error" | json
```

### 5.3 Alerting Rules

#### Prometheus Alerting Examples

**High Error Rate:**
```yaml
groups:
- name: open-webui-alerts
  interval: 30s
  rules:
  - alert: HighErrorRate
    expr: |
      rate(http_server_requests_total{status=~"5.."}[5m]) > 0.05
    for: 5m
    labels:
      severity: critical
    annotations:
      summary: "High error rate in Open WebUI"
      description: "Error rate is {{ $value | humanizePercentage }} (threshold: 5%)"
```

**Memory Usage Critical:**
```yaml
- alert: MemoryUsageCritical
  expr: |
    container_memory_usage_bytes{pod=~"open-webui-.*"}
    / container_spec_memory_limit_bytes{pod=~"open-webui-.*"} > 0.9
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: "Open WebUI pod {{ $labels.pod }} high memory usage"
    description: "Memory usage is {{ $value | humanizePercentage }}"
```

**Database Connection Pool Exhausted:**
```yaml
- alert: DatabaseConnectionPoolExhausted
  expr: |
    db_connection_pool_usage / db_connection_pool_size > 0.9
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "Database connection pool near exhaustion"
    description: "Connection pool usage: {{ $value | humanizePercentage }}"
```

**Pod Restart Loop:**
```yaml
- alert: PodRestartLoop
  expr: |
    rate(kube_pod_container_status_restarts_total{pod=~"open-webui-.*"}[15m]) > 0.1
  for: 10m
  labels:
    severity: critical
  annotations:
    summary: "Open WebUI pod {{ $labels.pod }} in restart loop"
    description: "Pod has restarted {{ $value }} times in 15 minutes"
```

**WebSocket Connections Dropped:**
```yaml
- alert: WebSocketConnectionsDrop
  expr: |
    rate(websocket_connections_active[5m]) < -10
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Significant drop in WebSocket connections"
    description: "WebSocket connections dropped by {{ $value }} in 5 minutes"
```

#### AlertManager Configuration

```yaml
global:
  resolve_timeout: 5m

route:
  group_by: ['alertname', 'cluster']
  group_wait: 10s
  group_interval: 10s
  repeat_interval: 12h
  receiver: 'slack-notifications'
  routes:
  - match:
      severity: critical
    receiver: 'pagerduty-critical'
    continue: true

receivers:
- name: 'slack-notifications'
  slack_configs:
  - api_url: 'https://hooks.slack.com/services/xxx/yyy/zzz'
    channel: '#open-webui-alerts'
    title: '{{ .GroupLabels.alertname }}'
    text: '{{ range .Alerts }}{{ .Annotations.description }}{{ end }}'

- name: 'pagerduty-critical'
  pagerduty_configs:
  - service_key: 'your-pagerduty-key'
```

### 5.4 Distributed Tracing

#### Jaeger/Tempo Integration

**Configure Trace Export:**
```bash
ENABLE_OTEL_TRACES=true
OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo:4317
OTEL_EXPORTER_OTLP_PROTOCOL=grpc
OTEL_SERVICE_NAME=open-webui
OTEL_RESOURCE_ATTRIBUTES=deployment.environment=production,service.version=0.6.41
```

**What Gets Traced:**
- HTTP request lifecycle (ingress → handler → response)
- Database queries (with query sanitization)
- Redis operations (cache hits/misses)
- External API calls (Ollama, OpenAI, etc.)
- Vector database operations (embedding, search)
- File I/O operations

**Example Trace Analysis:**

```
User sends chat message
├─ HTTP POST /api/chat (200ms total)
│  ├─ Validate authentication (5ms)
│  ├─ Database: Fetch user context (10ms)
│  ├─ Database: Fetch chat history (15ms)
│  ├─ LLM API call (150ms) ← BOTTLENECK
│  │  ├─ Build prompt (5ms)
│  │  └─ Stream response (145ms)
│  └─ Database: Save message (15ms)
```

**Source:** [OpenTelemetry Guide](https://docs.openwebui.com/getting-started/advanced-topics/monitoring/otel/)

### 5.5 Performance Metrics to Monitor

#### Key Performance Indicators (KPIs)

**For 100+ User Deployment:**

| Metric | Target | Warning Threshold | Critical Threshold |
|--------|--------|-------------------|-------------------|
| **Request Latency (p95)** | <1s | >2s | >5s |
| **Request Latency (p99)** | <2s | >5s | >10s |
| **Error Rate** | <0.1% | >1% | >5% |
| **WebSocket Active** | Stable | -20% drop | -50% drop |
| **CPU Usage** | <60% | >80% | >95% |
| **Memory Usage** | <70% | >85% | >95% |
| **Database Connections** | <70% pool | >90% pool | 100% pool |
| **Pod Restarts** | 0/hour | >1/hour | >5/hour |

#### Dashboard Panel Examples

**Grafana Panel: Request Latency (Heatmap)**
```promql
histogram_quantile(0.95,
  sum(rate(http_server_request_duration_seconds_bucket[5m])) by (le, endpoint)
)
```

**Grafana Panel: Chat Messages Per Second**
```promql
rate(openwebui_messages_sent_total[5m])
```

**Grafana Panel: Database Query Performance**
```promql
histogram_quantile(0.99,
  sum(rate(db_query_duration_seconds_bucket[5m])) by (le, query_type)
)
```

---

## 6. Complete Production Configuration Example

### 6.1 Environment Variables (ConfigMap)

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: open-webui-config
  namespace: open-webui
data:
  # Server configuration
  ENV: "prod"
  PORT: "8080"
  WEBUI_URL: "https://chat.company.com"

  # Worker configuration (scale with CPU)
  UVICORN_WORKERS: "4"                   # 2x CPU cores recommended
  THREAD_POOL_SIZE: "1000"               # 10x concurrent users

  # Database
  DATABASE_URL: "postgresql+asyncpg://openwebui:CHANGEME@postgres:5432/webui"
  PGVECTOR_POOL_SIZE: "20"
  PGVECTOR_POOL_MAX_OVERFLOW: "10"
  PGVECTOR_POOL_TIMEOUT: "30"
  PGVECTOR_POOL_RECYCLE: "3600"

  # Redis (REQUIRED for multi-replica)
  REDIS_URL: "redis://redis:6379/0"
  WEBSOCKET_MANAGER: "redis"
  WEBSOCKET_REDIS_URL: "redis://redis:6379/1"
  ENABLE_WEBSOCKET_SUPPORT: "true"

  # CORS (adjust for your domains)
  CORS_ALLOW_ORIGIN: "https://chat.company.com;https://chat-staging.company.com"

  # Performance tuning
  MODELS_CACHE_TTL: "300"                # Cache model list for 5 min
  AIOHTTP_CLIENT_TIMEOUT: "300"
  CHAT_STREAM_RESPONSE_CHUNK_MAX_BUFFER_SIZE: "16777216"  # 16MB

  # Vector database (use external for production)
  VECTOR_DB: "pgvector"                  # Or "qdrant"
  # QDRANT_URL: "http://qdrant:6333"    # If using Qdrant
  # ENABLE_QDRANT_MULTITENANCY_MODE: "true"

  # Embedding (offload to external service)
  RAG_EMBEDDING_ENGINE: "ollama"         # Or "openai"
  RAG_EMBEDDING_MODEL: "nomic-embed-text"

  # Observability
  ENABLE_OTEL: "true"
  ENABLE_OTEL_TRACES: "true"
  ENABLE_OTEL_METRICS: "true"
  OTEL_EXPORTER_OTLP_ENDPOINT: "http://otel-collector:4317"
  OTEL_SERVICE_NAME: "open-webui"
  GLOBAL_LOG_LEVEL: "WARNING"
  AUDIT_LOG_LEVEL: "METADATA"
  MAX_BODY_LOG_SIZE: "2048"

  # Security
  ENABLE_PERSISTENT_CONFIG: "false"      # Enforce env vars over DB
  ENABLE_COMPRESSION_MIDDLEWARE: "true"
```

### 6.2 Secrets (Secret)

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: open-webui-secrets
  namespace: open-webui
type: Opaque
stringData:
  # CRITICAL: Must be identical across all replicas
  # Generate with: openssl rand -base64 32
  secret-key: "REPLACE_WITH_YOUR_SECURE_KEY_DO_NOT_USE_THIS_EXAMPLE"

  # Database credentials
  db-password: "CHANGEME"

  # Optional: External API keys
  openai-api-key: ""
  anthropic-api-key: ""
```

### 6.3 Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: open-webui
  namespace: open-webui
  labels:
    app: open-webui
spec:
  replicas: 3                            # Start with 3 for HA
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0                  # Zero downtime updates
  selector:
    matchLabels:
      app: open-webui
  template:
    metadata:
      labels:
        app: open-webui
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8080"
        prometheus.io/path: "/metrics"
    spec:
      # Security context
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        fsGroup: 1000

      # Init container for database migration (optional)
      initContainers:
      - name: wait-for-db
        image: busybox:1.35
        command:
        - sh
        - -c
        - |
          until nc -z postgres 5432; do
            echo "Waiting for PostgreSQL..."
            sleep 2
          done

      containers:
      - name: open-webui
        image: ghcr.io/open-webui/open-webui:0.6.41
        imagePullPolicy: IfNotPresent

        ports:
        - name: http
          containerPort: 8080
          protocol: TCP

        # Environment variables from ConfigMap
        envFrom:
        - configMapRef:
            name: open-webui-config

        # Secrets
        env:
        - name: WEBUI_SECRET_KEY
          valueFrom:
            secretKeyRef:
              name: open-webui-secrets
              key: secret-key
        - name: DATABASE_URL
          value: "postgresql+asyncpg://openwebui:$(DB_PASSWORD)@postgres:5432/webui"
        - name: DB_PASSWORD
          valueFrom:
            secretKeyRef:
              name: open-webui-secrets
              key: db-password

        # Resource requests/limits
        resources:
          requests:
            memory: "2Gi"
            cpu: "1000m"
          limits:
            memory: "6Gi"
            cpu: "2000m"

        # Volume mounts
        volumeMounts:
        - name: data
          mountPath: /app/backend/data

        # Health probes
        startupProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 10
          periodSeconds: 5
          timeoutSeconds: 3
          failureThreshold: 30

        livenessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 30
          periodSeconds: 10
          timeoutSeconds: 3
          failureThreshold: 3

        readinessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 10
          periodSeconds: 5
          timeoutSeconds: 3
          failureThreshold: 2

        # Security
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: false  # Open WebUI writes to /tmp
          capabilities:
            drop:
            - ALL

      # Shared storage (RWX required for multi-replica)
      volumes:
      - name: data
        persistentVolumeClaim:
          claimName: open-webui-data

      # Pod anti-affinity (spread across nodes)
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
          - weight: 100
            podAffinityTerm:
              labelSelector:
                matchLabels:
                  app: open-webui
              topologyKey: kubernetes.io/hostname
```

### 6.4 Service

```yaml
apiVersion: v1
kind: Service
metadata:
  name: open-webui
  namespace: open-webui
  labels:
    app: open-webui
spec:
  type: ClusterIP
  ports:
  - port: 80
    targetPort: 8080
    protocol: TCP
    name: http
  selector:
    app: open-webui
  sessionAffinity: None       # Sticky sessions handled at Ingress
```

### 6.5 Ingress

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: open-webui
  namespace: open-webui
  annotations:
    # WebSocket support
    nginx.ingress.kubernetes.io/websocket-services: "open-webui"

    # Session affinity
    nginx.ingress.kubernetes.io/affinity: "cookie"
    nginx.ingress.kubernetes.io/session-cookie-name: "open-webui-route"
    nginx.ingress.kubernetes.io/session-cookie-expires: "172800"
    nginx.ingress.kubernetes.io/session-cookie-max-age: "172800"

    # File upload limits
    nginx.ingress.kubernetes.io/proxy-body-size: "4096m"

    # Timeouts
    nginx.ingress.kubernetes.io/proxy-connect-timeout: "600"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "600"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "600"

    # SSL
    cert-manager.io/cluster-issuer: "letsencrypt-prod"

    # Security headers
    nginx.ingress.kubernetes.io/configuration-snippet: |
      more_set_headers "X-Frame-Options: SAMEORIGIN";
      more_set_headers "X-Content-Type-Options: nosniff";
      more_set_headers "X-XSS-Protection: 1; mode=block";
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - chat.company.com
    secretName: open-webui-tls
  rules:
  - host: chat.company.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: open-webui
            port:
              number: 80
```

### 6.6 PersistentVolumeClaim

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: open-webui-data
  namespace: open-webui
spec:
  accessModes:
  - ReadWriteMany              # REQUIRED for multi-replica
  storageClassName: nfs-client  # Use appropriate storage class
  resources:
    requests:
      storage: 50Gi
```

### 6.7 HorizontalPodAutoscaler

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: open-webui-hpa
  namespace: open-webui
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: open-webui
  minReplicas: 3
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
      - type: Percent
        value: 50
        periodSeconds: 60
    scaleUp:
      stabilizationWindowSeconds: 60
      policies:
      - type: Percent
        value: 100
        periodSeconds: 30
```

---

## 7. Deployment Checklist

### Pre-Deployment

- [ ] **External PostgreSQL database provisioned** with proper connection pooling
- [ ] **Redis cluster deployed** (or managed Redis service configured)
- [ ] **Persistent storage created** with ReadWriteMany (RWX) access mode
- [ ] **WEBUI_SECRET_KEY generated** and stored in Kubernetes Secret
- [ ] **Database credentials** created and stored in Secret
- [ ] **SSL/TLS certificates** obtained (Let's Encrypt or commercial)
- [ ] **CORS_ALLOW_ORIGIN** configured with all access domains
- [ ] **Ingress Controller** supports WebSockets (NGINX recommended)
- [ ] **Vector database** chosen (PGVector or Qdrant for production)
- [ ] **Backup strategy** for PostgreSQL and persistent storage defined

### Deployment

- [ ] **Create namespace** for Open WebUI resources
- [ ] **Apply ConfigMap** with all environment variables
- [ ] **Apply Secrets** with sensitive data
- [ ] **Deploy PostgreSQL** (if not using managed service)
- [ ] **Deploy Redis** (if not using managed service)
- [ ] **Create PersistentVolumeClaim** with RWX access mode
- [ ] **Deploy Open WebUI** with 1 replica initially (for migration)
- [ ] **Verify database migration** completed successfully
- [ ] **Scale to 3+ replicas** after migration completes
- [ ] **Apply Service** definition
- [ ] **Apply Ingress** with WebSocket annotations
- [ ] **Verify DNS** points to Ingress external IP
- [ ] **Test WebSocket** connectivity from browser

### Post-Deployment

- [ ] **Create admin user** via UI or API
- [ ] **Configure model providers** (Ollama, OpenAI, etc.)
- [ ] **Test RAG upload** with sample document
- [ ] **Verify session persistence** across replicas (login, switch pods, still logged in)
- [ ] **Configure monitoring** (Prometheus scraping, Grafana dashboards)
- [ ] **Set up alerting** (memory, CPU, errors, WebSocket drops)
- [ ] **Enable log aggregation** (Loki, Elasticsearch, or CloudWatch)
- [ ] **Perform load testing** with expected user count
- [ ] **Document runbook** for common issues (restart, scale, backup restore)
- [ ] **Schedule regular backups** (database, persistent storage)
- [ ] **Configure HorizontalPodAutoscaler** based on load test results
- [ ] **Review security** (network policies, pod security policies, RBAC)
- [ ] **Plan update strategy** (scaling down, testing, rolling back)

### Ongoing Operations

- [ ] **Monitor resource usage** weekly and adjust limits
- [ ] **Review logs** for errors and performance issues
- [ ] **Test backup restoration** quarterly
- [ ] **Update Open WebUI** monthly (following safe update procedure)
- [ ] **Rotate secrets** annually (WEBUI_SECRET_KEY, DB passwords)
- [ ] **Review and tune** autoscaling thresholds based on usage patterns
- [ ] **Audit user access** and permissions regularly
- [ ] **Capacity planning** based on growth trends

---

## 8. References

### Official Documentation
- [Open WebUI Documentation Home](https://docs.openwebui.com/)
- [Quick Start Guide](https://docs.openwebui.com/getting-started/quick-start/)
- [Environment Variable Configuration](https://docs.openwebui.com/getting-started/env-configuration/)
- [Multi-Replica Troubleshooting](https://docs.openwebui.com/troubleshooting/multi-replica/)
- [Redis WebSocket Support](https://docs.openwebui.com/tutorials/integrations/redis/)
- [OpenTelemetry Monitoring](https://docs.openwebui.com/getting-started/advanced-topics/monitoring/otel/)
- [Monitoring Your Open WebUI](https://docs.openwebui.com/getting-started/advanced-topics/monitoring/)
- [Reduce RAM Usage Guide](https://docs.openwebui.com/tutorials/tips/reduce-ram-usage/)
- [Enterprise Features](https://docs.openwebui.com/enterprise/)
- [Features Overview](https://docs.openwebui.com/features/)

### Kubernetes Deployment Guides
- [The SRE's Guide to High Availability Open WebUI Deployment](https://taylorwilsdon.medium.com/the-sres-guide-to-high-availability-open-webui-deployment-architecture-2ee42654eced)
- [Run Open WebUI with Kubernetes by Rick Kosse](https://medium.com/@r.kosse/run-open-webui-with-kubernetes-be5fad2a7938)
- [Install Open WebUI on Kubernetes and Access From Anywhere](https://anakinfoxe.com/blog/install-open-webui-on-k8s-and-access-from-anywhere/)
- [Open WebUI + Ollama with Azure Kubernetes Service](https://autoize.com/open-webui-ollama-with-azure-kubernetes-service/)
- [Deploy Open WebUI on Kubernetes with ArgoCD and Helm](https://kubito.dev/posts/deploy-open-webui-kubernetes-argocd-helm-openrouter/)
- [Ollama & Open-WebUI on Kubernetes by Arslan Khan](https://medium.com/@arslankhanali/ollama-open-webui-on-kubernetes-3c18497a3ed2)

### GitHub Resources
- [Open WebUI GitHub Repository](https://github.com/open-webui/open-webui)
- [Open WebUI Helm Charts](https://github.com/open-webui/helm-charts)
- [Helm Values.yaml](https://github.com/open-webui/helm-charts/blob/main/charts/open-webui/values.yaml)

### GitHub Issues & Discussions
- [Use Open WebUI at Large-Scale Discussion #7771](https://github.com/open-webui/open-webui/discussions/7771)
- [Multi-Replica Discussion #5109](https://github.com/open-webui/open-webui/discussions/5109)
- [Memory Leak When Embedding Discussion #8598](https://github.com/open-webui/open-webui/discussions/8598)
- [Memory Usage of WebUI Discussion #2583](https://github.com/open-webui/open-webui/discussions/2583)
- [WebSocket Disconnects Discussion #13215](https://github.com/open-webui/open-webui/discussions/13215)
- [Large File Upload Issues Discussion #3958](https://github.com/open-webui/open-webui/discussions/3958)
- [Adding Uvicorn Workers Discussion #9032](https://github.com/open-webui/open-webui/discussions/9032)
- [PGVector Pool Configuration Feature #15657](https://github.com/open-webui/open-webui/issues/15657)
- [API Timeout Issue #16747](https://github.com/open-webui/open-webui/issues/16747)
- [PGVector Null Byte Memory Leak #19867](https://github.com/open-webui/open-webui/issues/19867)

### Database & Storage
- [OpenWebUI With Postgres And Qdrant Setup Guide](https://www.heyitworks.tech/blog/openwebui-with-postgres-and-qdrant-a-setup-guide/)
- [Qdrant, Postgres, and Open WebUI Discussion #11597](https://github.com/open-webui/open-webui/discussions/11597)
- [Kubernetes Data Persistence Issue #742](https://github.com/open-webui/open-webui/discussions/742)

### Monitoring & Observability
- [OpenTelemetry Integration Discussion #12344](https://github.com/open-webui/open-webui/discussions/12344)
- [Grafana Dashboard for Open WebUI](https://grafana.com/grafana/dashboards/22867-grafana-dashboard-for-open-webui/)
- [Prometheus Exporter Feature Request #5304](https://github.com/open-webui/open-webui/discussions/5304)

### Kubernetes General
- [Kubernetes Liveness/Readiness Probes](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/)
- [Kubernetes Persistent Volumes](https://kubernetes.io/docs/concepts/storage/persistent-volumes/)
- [NGINX Ingress Sticky Sessions](https://kubernetes.github.io/ingress-nginx/examples/affinity/cookie/)
- [WebSockets on GKE Ingress](https://www.d3vtech.com/insights/websockets-on-gke-ingress/)

### Community Guides
- [How to Deploy and Use Open WebUI - Northflank](https://northflank.com/guides/how-to-deploy-and-use-open-webui)
- [SUSE AI Open WebUI Configuration](https://documentation.suse.com/suse-ai/1.0/html/openwebui-configuring/index.html)

---

## 9. Glossary

**API (Application Programming Interface):** Interface for software components to communicate.

**ChromaDB:** Default vector database used by Open WebUI for RAG (Retrieval-Augmented Generation).

**CORS (Cross-Origin Resource Sharing):** Security feature controlling which domains can access resources.

**HPA (Horizontal Pod Autoscaler):** Kubernetes component that automatically scales replicas based on metrics.

**Ingress:** Kubernetes resource managing external access to services (typically HTTP/HTTPS).

**JWT (JSON Web Token):** Compact token format used for authentication and session management.

**LLM (Large Language Model):** AI model trained on vast text data (e.g., GPT, Llama, Mistral).

**Ollama:** Tool for running LLMs locally with simple API.

**OOMKilled:** Kubernetes termination reason when container exceeds memory limit.

**OTLP (OpenTelemetry Protocol):** Standard protocol for transmitting telemetry data.

**PGVector:** PostgreSQL extension for storing and querying vector embeddings.

**PVC (PersistentVolumeClaim):** Kubernetes request for storage resources.

**Qdrant:** Vector database optimized for similarity search and embeddings.

**RAG (Retrieval-Augmented Generation):** Technique combining document retrieval with LLM generation.

**Redis:** In-memory data store used for caching and session management.

**RWO (ReadWriteOnce):** Storage access mode allowing one node to mount volume.

**RWX (ReadWriteMany):** Storage access mode allowing multiple nodes to mount volume simultaneously.

**SQLite:** File-based relational database (not suitable for multi-replica deployments).

**Sticky Sessions (Session Affinity):** Load balancing technique routing user to same backend instance.

**Uvicorn:** ASGI web server used to run Open WebUI (FastAPI application).

**Vector Database:** Database optimized for storing and searching high-dimensional vectors (embeddings).

**vLLM:** High-throughput LLM serving engine with optimized inference.

**WebSocket:** Protocol enabling bidirectional real-time communication between client and server.

---

## 10. Conclusion

Deploying Open WebUI on Kubernetes for 100+ concurrent users is achievable with proper architecture and configuration. The key success factors are:

1. **Use external PostgreSQL** - Never use SQLite for multi-replica deployments
2. **Configure Redis** - Required for WebSocket support and session management
3. **Set WEBUI_SECRET_KEY** - Identical across all replicas to prevent auth loops
4. **Use RWX storage** - Shared persistent storage for RAG uploads and images
5. **Tune resources** - Proper CPU/memory limits and thread pool sizing
6. **Monitor actively** - OpenTelemetry, Prometheus, and Grafana for observability
7. **Plan for scale** - Consider vLLM instead of Ollama for 100+ users
8. **Follow safe update procedures** - Scale down to 1 replica during migrations

This research compiles best practices from official documentation, community deployments, and real-world production issues. Following these guidelines will help avoid common pitfalls and ensure a stable, performant deployment.

For questions or issues not covered here, refer to the [Open WebUI GitHub Discussions](https://github.com/open-webui/open-webui/discussions) or [official documentation](https://docs.openwebui.com/).

---

**Document Version:** 1.0
**Last Updated:** 2026-01-05
**Research Conducted By:** Technical Research Specialist
**Confidence Level:** High (based on official docs, community reports, and GitHub issues)
