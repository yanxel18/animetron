# Spec: human-review

Status: Approved for implementation on November 14, 2026.
Depends on: workflow-runtime.

## Objective

Persist an authorized human decision on the exact video revision, caption and
destination set without keeping a generation worker occupied.

## Commands and structure

Inherit [shared commands and layout](SPECIFICATIONS.md).
Focused verification: `python -m pytest tests/test_human_review.py -q`.
Ownership: review entities/services and `app/integrations/telegram`.

## Code style and provider contracts

Inherit shared style. ReviewRequest contains runId, artifact hash/revision,
caption hash, destination identities, expiry and delivery metadata.
States: PENDING_DELIVERY, AWAITING_DECISION, APPROVED, REJECTED, EXPIRED,
SUPERSEDED, DELIVERY_FAILED, DELIVERY_UNKNOWN.

- `GET /api/v1/reviews`: paginated queue.
- `POST /api/v1/reviews/{id}/decisions`: authenticated decision bound to revision.
- Internal `getValidApproval(reviewId, publicationScope)`: valid immutable
  checked approval metadata or explicit rejection; consumed by future publishing.
  The bounded internal implementation below is not a cryptographic proof or a
  reusable publication capability.

Default Telegram transport is one outbound long-polling consumer. Persist update
ids and use single-use server-resolved callback tokens within current Telegram
limits. Match configured reviewer user id and chat id, not username alone.
If public webhooks are later approved, verify Telegram's webhook secret header,
TLS, ingress bounds and update deduplication.

## Testing and acceptance criteria

1. Unauthorized, expired, replayed or superseded decisions cannot authorize
   publication; simultaneous approve/reject has one transactional winner.
2. Exact preview/caption/destinations are shown; edits create a fresh request and
   invalidate the old approval. Proposed decision expiry: 24 hours.
3. Persist decisions and outbox effects atomically. Polling restart does not lose
   acknowledged updates. Telegram delivery failures/unknown outcomes are visible;
   provider size limits produce explicit delivery errors, not false success.

## Boundaries

Inherit shared boundaries. Telegram review necessarily transmits content outside
the workstation. Consent is configured explicitly. Review callbacks never carry
secrets or arbitrary paths. Dashboard and MCP decisions require the same role and
state checks. Rejection/expiry never creates a publication intent.

## P4-02 persistence boundary

The internal persistence slice stores exact `ReviewScope` values, caller-supplied
aware expiry, delivery outcome state and one immutable decision per request in
caller-owned PostgreSQL transactions. A changed scope supersedes the prior
active request without rewriting its historic decision. The proposed 24-hour
expiry is not assumed as a default. This slice does not implement reviewer
authorization, `getValidApproval`, HTTP/UI, Telegram or any other content
transmission, outbox effects, or publication; persisted rows are not
authorization or approval proofs.

## P4-03a bounded internal decision service

Owner-only approve/reject was explicitly selected on November 14, 2026.
`app.services.reviews.decisions.record_decision(connection, principal,
expected_scope, review_id, outcome) -> ReviewDecision` accepts only a caller-owned
explicit non-AUTOCOMMIT SQLAlchemy psycopg transaction, a trusted-server
`Principal`, an exact `ReviewScope`, an RFC-variant UUID4 review ID and a typed
`DecisionOutcome`. No expiry, role or content-hash defaults are supplied.

The trusted caller must freshly authenticate before **every** invocation,
including retries; `Principal` must never come from client deserialization.
This boundary checks owner role and aware expiry against PostgreSQL
`clock_timestamp()` after run/request locks and again after the final intent
lock/insert, before any successful return. It does not independently authenticate
the session or check revocation; a cached Principal is not an authentication
mechanism. Operator and viewer are denied for both outcomes.

The service locks the stored `workflow_runs` row before `review_requests`,
matching scope supersession ordering, then rereads the request and guards exact
scope, expiry and current state before effects **and identical replay**.
Concurrent opposing decisions have one winner. The existing
`get_review_request`, `get_review_decision` and `decide_review` store operations
remain the state machine; no second transition implementation is introduced.

An approval and one stable internal notification intent commit or roll back
together inside a savepoint, even if the caller catches an enqueue exception and
commits other work. Outer commit/rollback remains caller-owned. The topic
`internal.review-approved.v1` and UUID5 namespace
`fd3e1bf7-f2a6-51b9-bdaa-2299c3124a19` (name: canonical review UUID) are reserved
for this service's trusted writers. Identical valid retries do not enqueue.
Changed topic/resource collisions fail explicitly. An undecided request with a
pre-existing reserved intent is a conflict, even with identical contents.

An existing low-level APPROVED row without the matching reserved service intent
is rejected, never retroactively enqueued/promoted. This association is evidence
only within the trusted-writer contract: arbitrary database/outbox writers could
forge it. It is **not** an authenticated publication approval proof. Rejected
reviews create no approval or publication intent. Preserve the reserved intent
when maintaining outbox history; deleting it deliberately makes approval replay
fail closed.

Errors propagate: `AuthDenied` for authorization/expiry, `ReviewConflict` for
scope/state/replay conflicts, `OutboxConflict` for reserved intent collisions,
store lookup and type/validation errors for invalid inputs, and database/enqueue
failures without broad catches. Callers must configure transaction-local lock
and statement timeouts; any bounded retry must reauthenticate and reuse the
same review ID/scope/outcome. Lock waits can outlast principal/request expiry
and both are rechecked using a fresh advancing database clock after the last
potentially blocking intent lock/insert; failure rolls back the savepoint.

No HTTP/MCP/Telegram endpoint, outbound delivery, automatic publish consumer,
`getValidApproval`, publication intent/proof, live integration or deployment is
implemented. The broader commands/provider contracts above remain future work.
Focused database tests: `tests/test_review_decision_service.py`, executed only
through the ownership-checked disposable auth harness; full verification uses
`python tests/run_auth_checks.py`.

## P4-04b bounded current-approval lookup

`app.services.reviews.approvals.require_valid_approval(connection, review_id,
expected_scope, *, auth_config: AuthConfig) -> CheckedApproval` implements only
the internal current-approval inspection part of the future `getValidApproval`
requirement. The keyword-only configuration must be **current trusted-server
settings**, never client supplied. It derives the current owner principal ID
using existing `auth.digest(issuer + "\0" + owner_subject)`, exactly as
`AuthStore.create_session` does; another/former configured owner's decision
fails closed. No active human-owner session is required to inspect a past
decision. Fresh caller authorization remains a future transport/publisher duty.

The lookup accepts only the existing explicit non-AUTOCOMMIT SQLAlchemy psycopg
caller transaction, typed `ReviewScope` and RFC-variant UUID4 review ID.
One small canonical `lock_review_request` helper is shared with the decision
service: read the stored run identity, lock `workflow_runs`, lock
`review_requests`, then reread. The lookup next locks the reserved outbox intent.
The decision service's transitions, savepoint and post-intent expiry checks are
unchanged.

Successful inspection requires current APPROVED state, an existing immutable
APPROVED decision with matching review ID and current configured owner, exact
expected scope, and the decision-service reserved intent ID/topic/resource.
Expiry must be strictly after a fresh advancing PostgreSQL `clock_timestamp()`
**after all potentially blocking locks, including the final intent lock**.
Missing, unverified low-level, stale, superseded, expired, rejected, pending or
colliding approvals fail explicitly, never repaired or promoted.

`CheckedApproval` is frozen metadata: exact scope, review ID, immutable decision
identity/owner/time, and request expiry. It is valid only for the checked state
and current settings in this caller transaction—not a cryptographic proof,
reusable authorization capability, cached publication permission, or verification
of artifact bytes. A trusted publisher must call/recheck on **every publication
attempt and before effects**; inspection cannot prevent time/settings changes
after return. Privileged arbitrary database writers remain outside the
trusted-storage integrity guarantee.

There are no enqueues, state changes, content transmissions, commit/rollback
ownership changes, caller-supplied role/digest defaults, HTTP/MCP/Telegram
endpoints or publisher. This does not complete P4 or P9. Existing store lookup/
validation errors propagate; invalid current approval raises `ReviewConflict`,
reserved topic/resource collisions raise `OutboxConflict`, invalid config/scope
types raise `TypeError`. Callers own transaction-local lock/statement budgets;
timeouts and database errors propagate rather than yielding partial approval.
Any bounded retry must use current trusted settings and exact review/scope.
Focused tests: `tests/test_review_approval_lookup.py`, including a real separate
PG connection holding the final intent lock and observed `pg_stat_activity`
waiting until expiry. Preserve the missing-DB infrastructure skip convention;
full gates run the existing owned PostgreSQL/Keycloak harness.
