# Logging

Log aggregation via **Elasticsearch + Fluent Bit + Kibana** (EFK) — the same
pattern I run in production, sized down for a single-node Kind cluster.

**Why Fluent Bit over Fluentd as the shipper:** functionally similar for
this use case, but Fluent Bit's C-based footprint is a fraction of
Fluentd's — meaningful when it's a DaemonSet competing for resources with
everything else on a single Kind node. If asked "why not Fluentd" on
camera, that's the honest answer: at this scale Fluent Bit is strictly
lighter for the same outcome.

## 1. Install Elasticsearch

\`\`\`bash
helm repo add elastic https://helm.elastic.co
helm repo update

helm install elasticsearch elastic/elasticsearch \
  --namespace logging --create-namespace \
  -f logging/elasticsearch-values.yaml
\`\`\`
Single node, `xpack.security.enabled: false`, modest JVM heap (512m) —
all deliberate simplifications for the demo, documented directly in
`logging/elasticsearch-values.yaml`. Say this out loud in your tradeoffs
section rather than letting it look like an oversight.

Wait for it to come up (can take a couple minutes — it's the heaviest
component in this whole stack):
\`\`\`bash
kubectl get pods -n logging -l app=elasticsearch-master -w
\`\`\`

Sanity check it's actually healthy:
\`\`\`bash
kubectl port-forward -n logging svc/elasticsearch-master 9200:9200 &
curl http://localhost:9200/_cluster/health?pretty
\`\`\`
Look for `"status" : "yellow"` or `"green"` (yellow is expected and fine
for a single-node cluster — there's no second node to hold replica shards).

## 2. Install Kibana

\`\`\`bash
helm install kibana elastic/kibana \
  --namespace logging \
  -f logging/kibana-values.yaml
\`\`\`
\`\`\`bash
kubectl get pods -n logging -l app=kibana -w
\`\`\`

## 3. Install Fluent Bit

\`\`\`bash
helm repo add fluent https://fluent.github.io/helm-charts
helm repo update

helm install fluent-bit fluent/fluent-bit \
  --namespace logging \
  -f logging/fluent-bit-values.yaml
\`\`\`
Runs as a DaemonSet — confirm one pod per node:
\`\`\`bash
kubectl get pods -n logging -l app.kubernetes.io/name=fluent-bit
\`\`\`

## 4. Deploy the app (if not already running)

\`\`\`bash
kubectl apply -f k8s/
\`\`\`
`app/backend/main.py` already emits structured JSON logs to stdout via
`python-json-logger` — Fluent Bit's `kubernetes` filter (`Merge_Log On` in
`logging/fluent-bit-values.yaml`) parses that JSON into real fields once it
reaches Elasticsearch, rather than storing one opaque `log` string per line.
This is the same reason the JSON logging change mattered when we were on
Loki — the shipper changed, the payoff from structured app logs didn't.

## 5. Open Kibana and build an index pattern

\`\`\`bash
kubectl port-forward -n logging svc/kibana-kibana 5601:5601
\`\`\`
Open `http://localhost:5601` →  **Stack Management → Index Patterns** →
create pattern `backend-logs-*` (matches `Logstash_Prefix` in
`logging/fluent-bit-values.yaml`) → time field `@timestamp`.

Then **Discover** to browse/query logs. Useful filters for the video:

| What | KQL query |
|---|---|
| Only backend pod logs | `kubernetes.labels.app: "backend"` |
| Errors/warnings only | `log_processed.level: "ERROR" or log_processed.level: "WARNING"` |
| Slow requests (>500ms) | `log_processed.duration_ms > 500` |
| A specific request path | `log_processed.path: "/api/items"` |

(`log_processed` is the merge key set in the Fluent Bit `kubernetes` filter
— it's where your app's parsed JSON fields live once merged.)

## 6. Correlating logs with the failure simulation

Same payoff as before: during the OOMKill demo, pull up Kibana Discover
filtered to the backend pod and show the last log lines right before the
container died, next to the `OOMKilled` reason from `kubectl describe pod`
— two independent signals (structured logs + cluster events) confirming the
same root cause, which reads as much stronger debugging methodology than
either alone.

## What's out of scope here (name in tradeoffs)
- Single Elasticsearch node — no replica shards, no HA, data loss risk if
  the node goes down (production: a proper ES cluster with dedicated
  master/data/ingest node roles)
- Security disabled (`xpack.security.enabled: false`) — no auth, no TLS,
  no RBAC on who can query logs (production: this would be a hard
  requirement, not optional, especially for anything touching customer data)
- No index lifecycle management (ILM) — logs accumulate indefinitely with
  no rollover/retention policy
- No alerting on log patterns — only the Prometheus/Grafana metrics side
  has alerting in this setup

## Resource footprint note
This is the heaviest addition to the cluster — Elasticsearch alone wants
1GB+ of memory even at minimum settings. If your Kind node is resource
constrained, this is worth mentioning explicitly as a real operational
constraint you hit and worked around (e.g., cutting `esJavaOpts`, running
fewer replicas of the app itself while EFK is up) rather than something to
hide.