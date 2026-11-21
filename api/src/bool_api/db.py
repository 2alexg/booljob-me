"""Postgres connection pool (service-level access; authorization is enforced in code)."""

from psycopg_pool import AsyncConnectionPool


def create_pool(database_url: str) -> AsyncConnectionPool:
    return AsyncConnectionPool(
        database_url,
        min_size=1,
        max_size=10,
        open=False,
        kwargs={"autocommit": True},
    )


async def ping(pool: AsyncConnectionPool) -> None:
    async with pool.connection() as conn:
        await conn.execute("select 1")
