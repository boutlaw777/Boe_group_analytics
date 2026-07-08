from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from finclone.config import DATABASE_URL


class Base(DeclarativeBase):
    pass


# pool_pre_ping: Supabase's pooler drops idle connections; without the ping,
# the first requests after an idle stretch fail with a 500 on a stale socket.
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    # Import models so their tables are registered on Base before create_all.
    from finclone import models  # noqa: F401

    Base.metadata.create_all(engine)


def get_session() -> Session:
    return SessionLocal()
