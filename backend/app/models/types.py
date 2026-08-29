"""Dialect-portable column types.

Production runs on PostgreSQL, but the test suite runs on SQLite so the whole
API can be exercised without standing up a database. These variants keep one
set of models working on both: JSONB/JSON, native UUID/CHAR, INET/VARCHAR.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

JSONType = postgresql.JSONB().with_variant(sa.JSON(), "sqlite")
UUIDType = sa.Uuid(as_uuid=True)
INETType = postgresql.INET().with_variant(sa.String(45), "sqlite")
