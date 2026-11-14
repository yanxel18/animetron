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
  approval proof or explicit rejection; consumed by publishing.

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
