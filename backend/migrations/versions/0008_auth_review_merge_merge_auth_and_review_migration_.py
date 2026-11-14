"""merge auth and review migration histories

Revision ID: 0008_auth_review_merge
Revises: 0007_auth_denial_counters, p4_02_review_records_20261114
Create Date: 2026-11-14 14:18:57.441220

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0008_auth_review_merge"
down_revision: str | Sequence[str] | None = (
    "0007_auth_denial_counters",
    "p4_02_review_records_20261114",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""


def downgrade() -> None:
    """Downgrade schema."""
