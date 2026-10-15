# Notes for your report / viva

## How the project satisfies the title
"Develop and deploy a **cloud-native application** using **microservices architecture**"
| Keyword | Evidence in this repo |
|---|---|
| Microservices | 4 independent services + frontend + gateway; each has its own code, tests, Dockerfile and database |
| Cloud-native | Containers, stateless services, config via environment, health probes, horizontal scaling, self-healing (Kubernetes) |
| Develop | Python/Flask, REST APIs, JWT security, PostgreSQL, 36 automated tests |
| Deploy | Docker Compose, Kubernetes manifests (kustomize), GitHub Actions CI/CD, cloud deployment guide |
| DevOps | Pipeline stages, container registry, monitoring (Prometheus/Grafana), logs, rollbacks |

## Suggested report outline
1. Introduction and objectives  2. Monolith → microservices (use the table in ARCHITECTURE.md)  3. System design (diagram, API list, DB per service)
4. Implementation (auth, checkout saga, gateway)  5. Containerization  6. Kubernetes deployment  7. CI/CD pipeline
8. Monitoring and logging  9. Testing (unit, integration, smoke)  10. Results/screenshots  11. Limitations and future work

## Likely viva questions
- *Why microservices for this app?* Independent scaling/deploys (the order service gets the load), fault isolation, team ownership; the cost is complexity (network calls, data consistency).
- *How do services authenticate each other's users?* Signed JWT from the user service, verified by each service with a shared secret.
- *What if the payment service is down?* Order is saved, payment call fails, order is cancelled (compensating action) and the user is told to retry. Other features (browsing, history) keep working.
- *Why one database per service?* Loose coupling; a schema change in one service cannot break another. That is why order items store a copy of the name and price.
- *What does Kubernetes give you here?* Replicas + load balancing, rolling updates without downtime, restarts on failed health checks, autoscaling, secrets/config management.
- *What does the CI/CD pipeline do?* Runs unit tests, starts the whole stack in Compose and runs smoke tests, builds/pushes images tagged with the commit SHA, deploys with `kubectl apply -k`.
- *How would you improve it?* Message queue for events, managed databases, asymmetric JWT keys, Ingress + TLS, Helm, distributed tracing.
