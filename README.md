# CampusEats — a cloud-native microservices application

Campus canteen ordering system, redesigned as **microservices** and packaged for **cloud-native deployment**
(Docker → Docker Compose → Kubernetes, with CI/CD and monitoring).
It evolved from the author's CS50 final project (a Flask monolith); the business logic and UI are kept, the architecture is new.

```
Browser ──► API Gateway (Nginx) ──┬─► Frontend (Flask, HTML pages)
                                  ├─► User service     ── userdb
                                  ├─► Menu service     ── menudb
                                  ├─► Order service    ── orderdb ──calls──► Menu service, Payment service
                                  └─► Payment service  ── paymentdb
Prometheus ──scrapes /metrics──► every service ──► Grafana dashboards
```

| Component | Responsibility | Port |
|---|---|---|
| `gateway/` | Single entry point, routing, rate limiting (Nginx) | 80 (8080 locally) |
| `frontend/` | Web pages (Jinja templates + CSS from the CS50 project); no database | 5000 |
| `services/user/` | Register, login, JWT issuing, profile | 5001 |
| `services/menu/` | Categories and food items, admin menu management, price lookup | 5002 |
| `services/order/` | Checkout, order history, cancel, admin status workflow | 5003 |
| `services/payment/` | Simulated payments and refunds | 5004 |
| `common/` | Shared code: DB layer (SQLite/PostgreSQL), JWT auth, health/metrics/logging |  |

## Run it

**1. Without Docker (quickest, SQLite databases)**
```bash
pip install Flask PyJWT requests
python scripts/run_local.py            # open http://localhost:8080   (admin / admin12345)
python scripts/smoke_test.py http://localhost:8080      # in another terminal
python scripts/ui_smoke_test.py http://localhost:8080
```

**2. Docker Compose (PostgreSQL + all services + gateway + Prometheus + Grafana)**
```bash
cp .env.example .env        # optional: change the secrets
docker compose up --build
# App http://localhost:8080 · Prometheus http://localhost:9090 · Grafana http://localhost:3000 (admin / $GRAFANA_PASSWORD, default "admin")
```

**3. Kubernetes** (kind/minikube locally, or AKS/GKE/EKS) — see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)
```bash
kubectl apply -k k8s/
```

Default admin login (change it!): `admin` / `admin12345`.

## Tests
```bash
python -m unittest discover -s . -t . -v      # 36 unit tests, no Docker needed
```
Plus two end-to-end scripts in `scripts/` that run against any running system (local, Compose or Kubernetes).

## DevOps features
- **Containers:** one small non-root Dockerfile per component, health checks, Gunicorn.
- **Orchestration:** Compose for local; Kubernetes Deployments (2 replicas, rolling updates with zero unavailable), Services, StatefulSet for PostgreSQL with a PersistentVolume, Secrets, ConfigMaps, readiness/liveness probes, resource requests/limits, HorizontalPodAutoscalers, NetworkPolicy.
- **CI/CD (GitHub Actions):** unit tests → integration test of the full Compose stack → build & push 6 images to GHCR → deploy to Kubernetes (optional).
- **Observability:** JSON access logs, `/health`, Prometheus `/metrics` in every service, Grafana dashboard (rate, errors, p95 latency, orders/min).
- **Security:** JWT auth verified in every service, role checks (student/admin), CSRF protection, hashed passwords, server-side price calculation, gateway rate limiting (stricter on login), secrets kept out of images, non-root containers.

## Verification status (be aware)
Verified by running here: all 36 unit tests; the complete system (6 processes, SQLite) with the API and browser-style smoke tests (26 checks), all passing.
**Not executed yet:** Docker image builds, Compose with PostgreSQL, and the Kubernetes manifests (the machine used to write this had no registry access). `docker compose config` and YAML parsing pass. The CI workflow's `integration` job runs the Compose + PostgreSQL stack on its first push, so that is where any remaining problem will show up first. Expect to fix a small typo or two on the first real run.

## Repository layout
```
common/            shared Python code            frontend/   web UI + tests
services/<name>/   app.py, Dockerfile, tests     gateway/    nginx.conf + Dockerfile
k8s/               Kubernetes manifests          monitoring/ Prometheus + Grafana (Compose)
scripts/           run_local, smoke tests        docs/       architecture, deployment, report notes
.github/workflows/ CI/CD pipeline                db/init.sql one database per service
```

## Credits and AI disclosure
Application logic, schema ideas and UI come from the author's CS50 final project (which already discloses its AI assistance).
The microservice split, DevOps configuration and this documentation were produced with the help of Claude (Anthropic).
Follow your college's rules on disclosing AI assistance, and make sure you can explain every part.
