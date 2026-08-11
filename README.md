# K8S-GitOps-DevSecOps-Logging-Obs-Stack

A production-style, GitOps-driven Kubernetes deployment pipeline — built to demonstrate containerization, automated CI/CD, observability, and real operational debugging on a local Kind cluster.

**Stack:** FastAPI · PostgreSQL · Kubernetes (Kind) · Jenkins · ArgoCD · Docker

---

## Overview

This project deploys a two-tier application (FastAPI backend + static frontend) backed by PostgreSQL, using a GitOps delivery model:

Developer → Git → Jenkins (CI) → Local Registry
↓
Git commit (image tag bump)
↓
ArgoCD (CD) → Kind Cluster → assignment-demo namespace


Jenkins owns **CI**: build, test, image push, and a manifest commit back to Git.
ArgoCD owns **CD**: it watches the Git repo and reconciles cluster state automatically — no `kubectl apply` from the pipeline, no manual sync. This separation is the core GitOps principle the project is built around: **Git is the single source of truth**, and the cluster is a reflection of it, not the other way around.

---

## Architecture

| Layer | Choice | Why |
|---|---|---|
| Cluster | Kind (Kubernetes in Docker) | Fast, disposable, fully local — no cloud cost or provisioning lag |
| CI | Jenkins | Builds images, pushes to registry, bumps manifest tags, commits to Git |
| CD | ArgoCD | Declarative sync + self-heal from Git; drift is automatically reverted |
| Backend | FastAPI + psycopg2 | Lightweight, async-capable, clean separation of liveness vs readiness |
| Database | PostgreSQL (in-cluster) | Simple, PVC-backed, demonstrates a real stateful dependency |
| Ingress | ingress-nginx | Path-based routing: `/` → frontend, `/api` → backend |
| Reliability | Readiness/liveness probes + HPA | See [Reliability Engineering](#reliability-engineering) below |

---

## Features

- **Two-tier application** — FastAPI backend with a Postgres dependency, static frontend served via nginx
- **Full GitOps loop** — Jenkins never touches the cluster directly; ArgoCD reconciles from Git on every commit
- **Health-aware deployments** — liveness and readiness are deliberately separate: liveness never depends on the database, so a slow DB doesn't trigger unnecessary pod restarts
- **Horizontal Pod Autoscaling** — CPU-driven scaling with a tuned scale-down stabilization window to avoid thrash
- **Local, private image registry** — no external registry dependency, wired directly into the Kind network
- **Reproducible from scratch** — a single script bootstraps the entire cluster, registry, ingress controller, metrics pipeline, and ArgoCD

---

## Reliability Engineering

**Chosen improvement: resource limits + Horizontal Pod Autoscaler**

- **Problem it solves** — fixed replica counts don't respond to real traffic, and pods without memory/CPU limits can starve their neighbors on a shared node
- **Why this over alternatives** — probes alone only detect failure after it happens; HPA is the difference between reactive and proactive reliability, and it's the improvement most directly tied to production traffic patterns
- **Tradeoff** — CPU-based scaling is a blunt signal. A backend that's slow because Postgres is saturated won't show CPU pressure, so HPA scales out pods that don't fix the actual bottleneck. In a real production system, this would be paired with custom Prometheus metrics via the Prometheus Adapter rather than CPU alone.

---

## Failure Simulation

**Scenario: OOMKilled backend pod under load**

A memory limit is deliberately set below what the application needs under load, triggering a real `OOMKilled` termination — not a scripted or simulated failure.

**Debugging sequence:**
1. `kubectl get pods -n assignment-demo` → `CrashLoopBackOff`
2. `kubectl describe pod <pod>` → `Last State: Terminated, Reason: OOMKilled`
3. `kubectl logs <pod> --previous` → confirm no application-level error, ruling out bad code/config
4. `kubectl top pod` → memory pressure visible before the kill
5. Root cause isolated to the resource limit, not application logic
6. Fix committed to Git → ArgoCD auto-syncs the corrected limit → pod stabilizes

This mirrors a real incident pattern (JVM heap OOMKills under production load) rather than a contrived failure mode.

---

## Project Structure

.
├── app/
│ ├── backend/ FastAPI service (health/ready endpoints, Postgres-backed API)
│ └── frontend/ Static UI, nginx-served
├── k8s/ Kubernetes manifests (namespace, config, secrets, deployments, HPA, ingress)
├── ci/
│ └── Jenkinsfile Build → push → manifest commit
├── argocd/
│ └── application.yaml ArgoCD Application (auto-sync, self-heal)
├── kind/
│ ├── kind-config.yaml Cluster config with ingress port mappings
│ └── setup-cluster.sh One-shot bootstrap: cluster, registry, ingress, metrics-server, ArgoCD
├── docs/
│ └── RUNBOOK.md Full step-by-step setup and failure-simulation walkthrough
└── README.md


---

## Getting Started

### Prerequisites
Docker · [kind](https://kind.sigs.k8s.io/) · kubectl · a Git repository you can push to

### 1. Bootstrap the cluster
```bash
bash kind/setup-cluster.sh
```
Creates the Kind cluster, local registry (`localhost:5001`), ingress-nginx, metrics-server, and ArgoCD.

### 2. Build and deploy
```bash
docker build -t localhost:5001/assignment-backend:latest ./app/backend
docker push localhost:5001/assignment-backend:latest

docker build -t localhost:5001/assignment-frontend:latest ./app/frontend
docker push localhost:5001/assignment-frontend:latest

kubectl apply -f k8s/
```

### 3. Register with ArgoCD
```bash
kubectl apply -f argocd/application.yaml
```

### 4. Verify
```bash
kubectl get pods -n assignment-demo
curl http://localhost/api/items
```

Full step-by-step instructions, including Jenkins setup and the failure-simulation walkthrough, are in [`docs/RUNBOOK.md`](docs/RUNBOOK.md).

---

## What Would Change in Real Production

This project intentionally simplifies several things to stay demonstrable within a local, single-node setup:

| Simplified here | Production equivalent |
|---|---|
| In-cluster Postgres, single replica | Managed RDS/Cloud SQL with HA, automated backups |
| Plaintext Kubernetes Secret | HashiCorp Vault or External Secrets Operator |
| Local Docker registry | ECR / GCR / Harbor with image scanning (Trivy) in the pipeline |
| CPU-only HPA | Custom metrics (queue depth, latency) via Prometheus Adapter |
| Manual Jenkins credentials | OIDC-based short-lived credentials, no long-lived secrets in CI |
| No SSO on ArgoCD/Jenkins UI | Enterprise SSO (Keycloak/Entra ID) in front of every internal tool |

---

## License

MIT — free to use as a reference or starting point.
