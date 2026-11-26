"""Run database migrations once and exit: ``python -m app.migrate``.

Used by the Kubernetes migrate Job (and handy before a rolling deploy) so API
pods can start with ``ERID_RUN_MIGRATIONS=0``. Concurrent runs are safe: an
advisory lock in ``migrations/env.py`` serializes them.
"""

import logging
import sys

from app.core.settings import settings
from app.db.session import run_migrations


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not settings.database_url.startswith("postgresql"):
        logging.error("migrations need a Postgres DATABASE_URL (got %s)", settings.database_url.split("://", 1)[0])
        return 2
    run_migrations()
    logging.info("database is at the latest migration")
    return 0


if __name__ == "__main__":
    sys.exit(main())
