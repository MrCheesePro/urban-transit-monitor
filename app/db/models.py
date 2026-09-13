"""ORM models. Import this module so tables register on Base.metadata (Alembic relies on it).

Tables are added per milestone; see docs/DESIGN.md.
"""

from app.db.base import Base

__all__ = ["Base"]
