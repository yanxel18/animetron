import os

from alembic import context

from app.core.artifacts import metadata as artifact_metadata
from app.core.database import create_database_engine
from app.core.outbox import metadata as outbox_metadata
from app.services.workflows.revisions import metadata as revision_metadata
from app.services.workflows.run_revisions import metadata as binding_metadata
from app.services.workflows.runs import metadata as run_metadata

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
                outbox_metadata,
                revision_metadata,
                binding_metadata,
                artifact_metadata,
            ],
        )
        with context.begin_transaction():
            context.run_migrations()
finally:
    engine.dispose()
