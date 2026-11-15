import { useEffect, useState } from "react";

import type { ReviewMetadataResponse, ReviewState } from "../api/generated";
import {
  fetchReviewPage,
  ReviewQueueError,
  reviewQueueErrorMessage,
} from "../api/reviews";

const stateLabels: Record<ReviewState, string> = {
  PENDING_DELIVERY: "Pending delivery",
  AWAITING_DECISION: "Awaiting decision",
  APPROVED: "Approved",
  REJECTED: "Rejected",
  EXPIRED: "Expired",
  SUPERSEDED: "Superseded",
  DELIVERY_FAILED: "Delivery failed",
  DELIVERY_UNKNOWN: "Delivery outcome unknown",
};

function formatTimestamp(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function ReviewCard({ review }: { review: ReviewMetadataResponse }) {
  const headingId = `review-heading-${review.id}`;

  return (
    <li className="review-list-item">
      <article className="review-card" aria-labelledby={headingId}>
        <header className="review-card-heading">
          <div className="review-card-title">
            <p className="panel-kicker">REVIEW REQUEST</p>
            <h2 id={headingId}>
              <code>{review.id}</code>
            </h2>
          </div>
          <span className="review-state">{stateLabels[review.state]}</span>
        </header>

        <dl className="review-metadata">
          <div>
            <dt>Run</dt>
            <dd>
              <code>{review.runId}</code>
            </dd>
          </div>
          <div>
            <dt>Artifact revision</dt>
            <dd>
              <code>{review.artifactRevision}</code>
            </dd>
          </div>
          <div>
            <dt>Created</dt>
            <dd>
              <time dateTime={review.createdAt}>
                {formatTimestamp(review.createdAt)}
              </time>
            </dd>
          </div>
          <div>
            <dt>State changed</dt>
            <dd>
              <time dateTime={review.stateChangedAt}>
                {formatTimestamp(review.stateChangedAt)}
              </time>
            </dd>
          </div>
          <div>
            <dt>Destinations</dt>
            <dd>
              {review.destinations.length === 0 ? (
                "None recorded"
              ) : (
                <ul className="review-destinations">
                  {review.destinations.map((destination) => (
                    <li key={`${destination.provider}:${destination.accountId}`}>
                      {destination.provider} · {destination.accountId}
                    </li>
                  ))}
                </ul>
              )}
            </dd>
          </div>
          <div>
            <dt>Expires</dt>
            <dd>
              <time dateTime={review.expiresAt}>
                {formatTimestamp(review.expiresAt)}
              </time>
            </dd>
          </div>
          {review.deliveryErrorCode !== null && (
            <div>
              <dt>Delivery issue</dt>
              <dd>
                <code>{review.deliveryErrorCode}</code>
              </dd>
            </div>
          )}
        </dl>

        <details className="review-integrity">
          <summary>Show artifact and caption hashes</summary>
          <dl className="review-hashes">
            <div>
              <dt>Artifact SHA-256</dt>
              <dd>
                <code>{review.artifactSha256}</code>
              </dd>
            </div>
            <div>
              <dt>Caption SHA-256</dt>
              <dd>
                <code>{review.captionSha256}</code>
              </dd>
            </div>
          </dl>
        </details>

        <p className="review-blocked-note" role="note">
          Decisions are unavailable because the exact video and caption preview
          are not available.
        </p>
      </article>
    </li>
  );
}

export function ReviewQueue() {
  const [reviews, setReviews] = useState<ReviewMetadataResponse[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [refreshToken, setRefreshToken] = useState(0);
  const [retryCursor, setRetryCursor] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setIsLoading(true);
    setError(null);
    setReviews([]);
    setCursor(null);
    setRetryCursor(null);

    void fetchReviewPage(null, controller.signal)
      .then((page) => {
        setReviews(page.data);
        setCursor(page.nextCursor);
      })
      .catch((requestError: unknown) => {
        if (!controller.signal.aborted) setError(requestError);
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsLoading(false);
      });

    return () => controller.abort();
  }, [refreshToken]);

  async function loadMore() {
    if (cursor === null || isLoadingMore) return;
    setIsLoadingMore(true);
    setError(null);
    setRetryCursor(null);

    try {
      const page = await fetchReviewPage(cursor);
      setReviews((current) => [...current, ...page.data]);
      setCursor(page.nextCursor);
    } catch (requestError: unknown) {
      setError(requestError);
      setRetryCursor(cursor);
    } finally {
      setIsLoadingMore(false);
    }
  }

  const errorStatus =
    error instanceof ReviewQueueError ? error.status : null;
  let loadMoreLabel = "Load more";
  if (isLoadingMore) {
    loadMoreLabel = "Loading more…";
  } else if (retryCursor !== null && retryCursor === cursor) {
    loadMoreLabel = "Retry loading more";
  }

  return (
    <section
      id="review"
      className="review-queue"
      aria-labelledby="review-queue-title"
      aria-busy={isLoading || isLoadingMore}
      tabIndex={-1}
    >
      <div className="page-heading">
        <div className="page-title">
          <p className="eyebrow">HUMAN REVIEW</p>
          <h1 id="review-queue-title" tabIndex={-1}>
            Review queue
          </h1>
          <p className="page-description">
            Inspect the stored revision and destination scope. Approval controls
            stay unavailable until the exact media and caption can be reviewed.
          </p>
        </div>
        <div className="workflow-actions" aria-label="Review queue actions">
          <button
            className="button button--secondary"
            type="button"
            disabled={isLoading || isLoadingMore}
            onClick={() => setRefreshToken((token) => token + 1)}
          >
            Refresh queue
          </button>
        </div>
      </div>

      {error !== null && (
        <div className="review-error" role="alert">
          <p>{reviewQueueErrorMessage(error)}</p>
          {errorStatus === 401 && (
            <a className="review-login-link" href="/api/v1/auth/login">
              Sign in
            </a>
          )}
          {retryCursor === null && (
            <button
              className="button button--secondary"
              type="button"
              onClick={() => setRefreshToken((token) => token + 1)}
            >
              Retry
            </button>
          )}
        </div>
      )}

      {isLoading && (
        <p className="review-queue-status" role="status">
          Loading review requests…
        </p>
      )}

      {!isLoading && reviews.length === 0 && error === null && (
        <p className="review-queue-status" role="status">
          No review requests are available.
        </p>
      )}

      {!isLoading && reviews.length > 0 && (
        <>
          <p className="review-queue-status" role="status" aria-live="polite">
            {reviews.length} review {reviews.length === 1 ? "request" : "requests"}{" "}
            loaded.
          </p>
          <ul className="review-list" aria-label="Review requests">
            {reviews.map((review) => (
              <ReviewCard key={review.id} review={review} />
            ))}
          </ul>
        </>
      )}

      {cursor !== null && (
        <div className="review-pagination">
          <button
            className="button button--secondary"
            type="button"
            disabled={isLoading || isLoadingMore}
            onClick={() => void loadMore()}
          >
            {loadMoreLabel}
          </button>
        </div>
      )}
    </section>
  );
}
