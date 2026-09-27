# Worker provisioning / deprovisioning

Automation for the ephemeral MicroK8s worker node that the trading-app pod runs
on during market hours. Driven by orchestrator system cron (see
`orchestrator.yml`): provision at **8:30am ET**, deprovision at **4:15pm ET**,
Mon–Fri.

| File | Role |
| --- | --- |
| `provision_worker.yml` | Orchestrates an ordered list of provisioning attempts; stops at the first Ready node. |
| `provision_attempt.yml` | One attempt against a single provider/region: create → bounded Ready-wait → cleanup on wedge. Included in a loop. |
| `deprovision_worker.yml` | Reaps **every** tracked instance (idempotently) and removes the node from the cluster. |

## Design: fail over, don't hang

The goal is "a Ready, labeled `trading-worker` node by ~9:20am" — by any path.
`provision_worker.yml` walks `provider_attempts` in order and stops at the first
attempt that produces a Ready node. Two failure classes are handled
automatically instead of silently losing the trading day:

- **Provider control-plane outage** (the API that *creates* VMs is down / 5xx).
  Retrying the same provider is pointless, so a different provider later in the
  list is what saves you. This is the case that actually bit us: Vultr's API
  returned 500s across every endpoint one morning while existing VMs were fine.
- **Boot wedge** (VM is created but `cloud-init` never finishes, so the node
  never joins — rare, intermittent). A fresh attempt clears it probabilistically
  because it isn't reproducible; a wedge that reproduced every run would fail
  daily, which it doesn't.

`A OR B` provisioning strictly *raises* availability: it only fails if every
attempt fails in the same ~50-minute window. There is **no standing second-cloud
compute** — a fallback provider is only ever created when the primary can't make
a VM, so blue-sky days cost nothing extra.

### Why each attempt is bounded and Ready-gated

The old wait was an unbounded `until microk8s kubectl get node` loop with no
timeout and no cleanup — a single wedge hung the playbook for hours and never
failed over. Each attempt now waits at most `node_ready_timeout` (default 12
min) and gates on the node's **`Ready`** condition, not merely on the node
*appearing*. A node that joins but never goes Ready is treated as a failure and
triggers the next attempt.

Provision only gates as far as **node Ready + labeled**. It cannot gate on the
strategy *pod* running, because the pod is scaled up separately by the 9:25am
`market-open` CronJob (the deployment sits at `replicas=0` at provision time).
Verifying the pod actually scheduled after 9:25 is a separate watchdog concern,
not part of provisioning — see "Known gaps".

### Timing budget

Attempts are sequential: `create + up to node_ready_timeout` each. At 12
min/attempt the two-region Vultr list resolves inside the 8:30 → 9:20 window,
before the 9:25 pod scale-up. Adding a third attempt (a second cloud) keeps ~14
min of margin. If the list grows, either shorten `node_ready_timeout` or move
the provision cron earlier — don't let the worst-case attempt chain cross 9:20.

### Per-attempt join token

`microk8s add-node` tokens have a TTL (`join_token_ttl`, default 30 min). A
token minted once up front can expire mid-run across a slow `apt`/`snap install`
plus a retry, silently invalidating the join. Each attempt therefore mints its
**own** fresh token immediately before rendering `user_data`.

## Instance tracking and teardown (billing safety)

Every instance that is *created* is appended to `instances_file`
(`/opt/trading/secrets/worker_instances`, tab-separated `provider region id`)
**before** we wait on it — so a wedged or orphaned box is always reapable even
if the run dies partway. A wedge is also destroyed immediately within the run so
we don't pay for two boxes at once.

`deprovision_worker.yml` reads the full list and issues an **idempotent** DELETE
per instance (404 tolerated), then clears the file. If the provider API is down
at 4:15pm the file is left intact so the next deprovision retries — this is the
self-healing path for an orphan left by a failed teardown. It also reaps the
**legacy single-ID file** (`worker_instance_id`) if present, for backward
compatibility with instances created before this change.

> Append-on-create + reap-all-then-clear is deliberate: provision *appends*
> (never truncates), deprovision *clears*. A worker left un-reaped by a failed
> teardown therefore survives in the list and gets cleaned on the next cycle.

## Adding a second cloud

The provider dimension is data-driven, but each provider needs its own
create/destroy API calls (request/response JSON shapes differ). To wire one in:

1. **Set up the account** (your step): create the account, an API key, upload
   the same SSH public key, note the base-image ID and a region slug, and place
   the API key at `/opt/trading/secrets/<provider>_api_key` on the orchestrator.
2. **create**: add a `create_<provider>` block in `provision_attempt.yml`
   guarded on `attempt.provider`, normalising its response into
   `created_instance_id` / `created_ok` / `provider_api_down`.
3. **destroy**: add the matching DELETE in both the wedge-cleanup task
   (`provision_attempt.yml`) and `deprovision_worker.yml`, guarded on the
   `provider` column read from `instances_file`.
4. **enable**: append `{ provider: <provider>, region: <slug> }` to
   `provider_attempts` in `provision_worker.yml` — last, so it's only reached
   after both Vultr regions fail.

## Notifications

Best-effort Telegram messages (same `telegram-credentials` secret as
`ibkr-preauth`) fire on **failover success** (a non-primary attempt won) and on
**total failure** (no provider produced a node). These are receipts/telemetry,
not a request for manual intervention — provisioning never fails because a
notification failed (`ignore_errors`).

## Known gaps

- **Pod-scheduled watchdog**: provisioning stops at node Ready+labeled; nothing
  yet verifies the pod actually reached `Running` after the 9:25 scale-up.
- **Second cloud not yet wired** — only Vultr (two regions) is active; see
  "Adding a second cloud".
