# Spec: social-publishing

Status: Approved for implementation on November 14, 2026.
Depends on: human-review.

## Objective

Publish approved content to eligible destinations through official APIs, with
durable per-destination status and safe recovery from unknown external outcomes.

## Commands and structure

Inherit [shared commands and layout](SPECIFICATIONS.md).
Focused verification: `python -m pytest tests/test_social_publishing.py -q`.
Ownership: publication entities/services and `app/integrations/publishing`.
Live tests are opt-in and separately authorized.

## Code style and provider contracts

Inherit shared style. Adapter contract: validateEligibility, validateMedia,
startUpload, pollProcessing, finalizePublication, reconcile. Persist provider
upload/session/publication ids as soon as received.

- `GET /api/v1/connections`: redacted identities/eligibility.
- `POST /api/v1/connections/{id}/checks`: credential/permission check.
- `GET /api/v1/publications`: paginated per-destination status.
- `POST /api/v1/reviews/{id}/publications`: valid approval + stable intent key.
- `POST /api/v1/publications/{id}/reconciliations`: safe status discovery.

Unique intent scope: approved revision + destination + explicit publication
intent id. Reuse one key across attempts; changed payload fails with 422.
States: BLOCKED, QUEUED, UPLOADING, PROCESSING, PUBLISHING, PUBLISHED, FAILED,
UNKNOWN, CANCELLED. Provider timeout is UNKNOWN unless failure is confirmed.

## Testing and acceptance criteria

1. Facebook Page Reels passes current permission/token/media eligibility checks
   and one authorized live acceptance test before enabled status.
2. Instagram Reels, YouTube Shorts and TikTok each pass independent official
   eligibility, upload, processing and review-consent requirements. Unsupported
   flows remain BLOCKED with explanation, including audit restrictions.
3. Concurrent retries produce one local intent; missing provider idempotency is
   not treated as exactly-once. Unknown finalization is reconciled or requires
   explicit human resolution before retry. Mixed outcomes remain per-platform.

## Boundaries

Inherit shared boundaries. Platform versions, quotas, visibility rules, required
disclosures and account types must be verified before implementation pins.
Approval is rechecked before irreversible finalization. Cancellation cannot
recall already published content; deletion is a separate authorized operation.
No personal-profile assumption, credential scraping or browser-bot fallback.
