"""Alembic environment.

The URL comes from the application settings so migrations and the app can
never disagree about which database they mean, and no credential is written
into a tracked file.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings
from app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# A URL set by the caller (tests, or "alembic -x url=...") wins; otherwise the
# application's own DATABASE_URL is used, so migrations and the app agree.
if not config.get_main_option("sqlalchemy.url", None):
    config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
target_metadata = Base.metadata

# PostGIS ships its own tables (spatial_ref_sys, the TIGER geocoder schema,
# topology). They are not this application's, so autogenerate must never
# propose dropping or altering them.
_SYSTEM_SCHEMAS = {"tiger", "tiger_data", "topology"}
_POSTGIS_COLUMNS = {"geom", "centroid_geom", "extent_geom", "footprint_geom"}
_SYSTEM_TABLES = {
    "spatial_ref_sys",
    "geometry_columns",
    "geography_columns",
    "raster_columns",
    "raster_overviews",
}


def include_object(obj, name, type_, reflected, compare_to):  # noqa: ANN001, ANN201
    """Limit migrations to tables this application defines."""
    if getattr(obj, "schema", None) in _SYSTEM_SCHEMAS:
        return False
    if type_ == "table":
        return name in target_metadata.tables and name not in _SYSTEM_TABLES
    if type_ == "column" and reflected and name in _POSTGIS_COLUMNS:
        # The geometry columns are PostgreSQL-only and are created by a
        # migration; the models stay portable, so autogenerate sees them as
        # "removed" unless told otherwise.
        return False
    if type_ == "index" and reflected:
        # Hand-written indexes (the PostGIS GIST and query indexes) live in
        # migrations, not in the models, so autogenerate must not drop them.
        return False
    if reflected and getattr(obj, "table", None) is not None:
        return obj.table.name in target_metadata.tables
    return True


def run_migrations_offline() -> None:
    """Emit SQL without connecting."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_object=include_object,
            # SQLite cannot ALTER most things in place.
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
