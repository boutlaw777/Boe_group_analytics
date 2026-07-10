from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from finclone.config import DATABASE_URL


class Base(DeclarativeBase):
    pass


# pool_pre_ping: Supabase's pooler drops idle connections; without the ping,
# the first requests after an idle stretch fail with a 500 on a stale socket.
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# search_path=boe: our tables live in their own schema — public belongs to the
# legacy DCF app, whose dashboard "restore" snippets rewrite it wholesale.
# Set per connection (Supabase's pooler strips the `options` startup param).
if DATABASE_URL.startswith("postgresql"):
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _set_search_path(dbapi_conn, _record):
        with dbapi_conn.cursor() as cur:
            cur.execute("set search_path to boe, public")
        dbapi_conn.commit()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    # Import models so their tables are registered on Base before create_all.
    from finclone import models  # noqa: F401

    Base.metadata.create_all(engine)


def get_session() -> Session:
    return SessionLocal()
