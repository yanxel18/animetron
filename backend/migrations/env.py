import os

from alembic import context

from app.core.database import create_database_engine
from app.services.workflows.runs import metadata

url = os.environ.get("ANIMETRON_DATABASE_URL")
if not url:
    raise RuntimeError("ANIMETRON_DATABASE_URL is required for migrations")
if context.is_offline_mode():
    raise RuntimeError("Offline migrations are not supported")

engine = create_database_engine(url)
try:
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=metadata)
        with context.begin_transaction():
            context.run_migrations()
finally:
    engine.dispose()
