"""Alembic environment for the results store.

`ResultStore` runs migrations in-process and hands its connection over
through `config.attributes`. Offline (`tablewatch store sql`, spec 038) the
revisions are written as PostgreSQL for a migration tool to apply, without
BEGIN/COMMIT: that tool owns the transaction. The engine branch below only
serves developers running the alembic CLI against `alembic.ini` to write a
new revision.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import Connection, engine_from_config, pool

from tablewatch.results.models import VERSION_TABLE, Base


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        version_table=VERSION_TABLE,
        render_as_batch=True,  # SQLite needs batch mode to ALTER
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_offline() -> None:
    context.configure(
        dialect_name="postgresql",
        target_metadata=Base.metadata,
        version_table=VERSION_TABLE,
        render_as_batch=True,
        literal_binds=True,
        transactional_ddl=False,
    )
    with context.begin_transaction():
        context.run_migrations()


_connection = context.config.attributes.get("connection")
if context.is_offline_mode():
    _run_offline()
elif _connection is not None:
    _run(_connection)
else:
    _engine = engine_from_config(
        context.config.get_section(context.config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with _engine.connect() as _conn:
        _run(_conn)
