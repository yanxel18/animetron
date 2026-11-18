import os

from alembic import context

from app.core.artifacts import metadata as artifact_metadata
from app.core.auth import metadata as auth_metadata
from app.core.database import create_database_engine
from app.core.outbox import metadata as outbox_metadata
from app.services.reviews.store import metadata as review_metadata
from app.services.scheduling.due_slots import metadata as due_slot_metadata
from app.services.scheduling.store import metadata as schedule_metadata
from app.services.workflows.drafts import metadata as draft_metadata
from app.services.workflows.execution_bindings import (
    metadata as execution_binding_metadata,
)
from app.services.workflows.node_admission import metadata as admission_metadata
from app.services.workflows.node_outcomes import outcomes as _node_outcomes  # noqa: F401
from app.services.workflows.revisions import metadata as revision_metadata
from app.services.workflows.run_dispatch import metadata as run_metadata
from app.services.workflows.run_requests import metadata as request_metadata
from app.services.workflows.run_revisions import metadata as binding_metadata

url = os.environ.get("ANIMETRON_DATABASE_URL")
if not url:
    raise RuntimeError("ANIMETRON_DATABASE_URL is required for migrations")
if context.is_offline_mode():
    raise RuntimeError("Offline migrations are not supported")

engine = create_database_engine(url)
try:
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=[
                run_metadata,
                admission_metadata,
                outbox_metadata,
                revision_metadata,
                binding_metadata,
                artifact_metadata,
                auth_metadata,
                review_metadata,
                schedule_metadata,
                due_slot_metadata,
                request_metadata,
                execution_binding_metadata,
                draft_metadata,
            ],
        )
        with context.begin_transaction():
            context.run_migrations()
finally:
    engine.dispose()
