# Deployment guide

Build all images once (from the repository root):
```bash
for s in user:user-service menu:menu-service order:order-service payment:payment-service; do
  docker build -f services/${s%%:*}/Dockerfile -t campuseats/${s##*:}:latest .
done
docker build -f frontend/Dockerfile -t campuseats/frontend:latest .
docker build -f gateway/Dockerfile  -t campuseats/gateway:latest .
```

## A. Local Kubernetes (free, no cloud account) — good for the demo
Install Docker, `kubectl` and [kind](https://kind.sigs.k8s.io/) (or minikube).
```bash
kind create cluster --name campuseats
for i in user-service menu-service order-service payment-service frontend gateway; do
  kind load docker-image campuseats/$i:latest --name campuseats
done
kubectl apply -k k8s/
kubectl -n campuseats get pods -w                 # wait until everything is Running/Ready
kubectl -n campuseats port-forward svc/gateway 8080:80     # http://localhost:8080
python scripts/smoke_test.py http://localhost:8080
```
(HPAs need metrics-server; on kind they simply show `<unknown>`. That is fine for a demo.)

## B. A real cloud — Azure for Students (no credit card, ~US$100 credit)
Your college email (`@cmrcet.ac.in`) may qualify for **Azure for Students**: sign up at azure.microsoft.com/free/students.
Install the Azure CLI, then:
```bash
az login
az group create -n campuseats-rg -l centralindia
az aks create -g campuseats-rg -n campuseats-aks --node-count 2 --node-vm-size Standard_B2s --generate-ssh-keys
az aks get-credentials -g campuseats-rg -n campuseats-aks
```
Student subscriptions sometimes restrict regions or VM sizes; if `az aks create` complains, try another region (e.g. `southindia`, `eastus`) or size.

Images must be reachable from the cluster. Easiest: let GitHub Actions push them to GitHub Container Registry (section C), make the six packages **public** (GitHub → Packages → each package → Settings → Change visibility), then point the manifests at them:
```bash
cd k8s
OWNER=<your-github-username-lowercase>
for s in user-service menu-service order-service payment-service frontend gateway; do
  kustomize edit set image campuseats/$s=ghcr.io/$OWNER/campuseats-$s:latest      # or: kubectl kustomize edit ... via the kustomize CLI
done
cd .. && kubectl apply -k k8s/
kubectl -n campuseats get svc gateway -w        # wait for EXTERNAL-IP, then open http://<EXTERNAL-IP>
```
Before sharing the URL: replace the dev secrets in `k8s/secrets.yaml` (or create the Secret by hand and remove that file from `kustomization.yaml`):
```bash
kubectl -n campuseats create secret generic campuseats-secrets \
  --from-literal=POSTGRES_PASSWORD=... --from-literal=JWT_SECRET=$(openssl rand -hex 32) \
  --from-literal=SECRET_KEY=$(openssl rand -hex 32) --from-literal=ADMIN_USERNAME=admin --from-literal=ADMIN_PASSWORD=... \
  --from-literal=GRAFANA_PASSWORD=... \
  --from-literal=USER_DATABASE_URL=postgresql://campus:<pw>@postgres:5432/userdb \
  --from-literal=MENU_DATABASE_URL=postgresql://campus:<pw>@postgres:5432/menudb \
  --from-literal=ORDER_DATABASE_URL=postgresql://campus:<pw>@postgres:5432/orderdb \
  --from-literal=PAYMENT_DATABASE_URL=postgresql://campus:<pw>@postgres:5432/paymentdb
```
**Stop the bill when you are done:** `az group delete -n campuseats-rg --yes`.

*No Kubernetes cluster at all?* The same Compose file runs on any single cloud VM (Azure/Oracle/GCP free tiers): install Docker, copy the repo, `docker compose up -d --build`.

## C. CI/CD with GitHub Actions
1. Create a GitHub repository and push this project (`git init && git add . && git commit -m "CampusEats" && git push`).
2. The pipeline `.github/workflows/ci-cd.yml` then runs automatically: **test → integration (Compose + PostgreSQL) → build & push images to ghcr.io**.
3. To enable the automatic **deploy** job: Settings → Secrets and variables → Actions →
   - Secret `KUBE_CONFIG` = `base64 -w0 ~/.kube/config` of your cluster (for AKS: after `az aks get-credentials`)
   - Variable `DEPLOY_ENABLED` = `true`
   Every push to `main` then updates the cluster with the images built for that commit and waits for the rollout.

## D. Useful demo commands (screenshots for the report)
```bash
kubectl -n campuseats get pods,svc,hpa
kubectl -n campuseats scale deployment/order-service --replicas=4          # scaling
kubectl -n campuseats delete pod -l app=menu-service                       # self-healing
kubectl -n campuseats set image deployment/frontend frontend=campuseats/frontend:v2   # rolling update (after building v2)
kubectl -n campuseats rollout undo deployment/frontend                     # rollback
kubectl -n campuseats logs deploy/order-service                            # JSON logs
kubectl -n campuseats port-forward svc/grafana 3000:3000                   # Grafana dashboard
kubectl -n campuseats port-forward svc/prometheus 9090:9090                # Prometheus
```
