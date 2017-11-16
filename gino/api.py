import weakref

import sqlalchemy as sa
from asyncpg import Connection
from sqlalchemy.sql.base import Executable
from sqlalchemy.dialects import postgresql as sa_pg

from .crud import CRUDModel
from .declarative import declarative_base
from . import json_support
from .dialects.asyncpg import AsyncpgDialect
from .strategies import create_engine


class ConnectionAcquireContext:
    __slots__ = ('_connection',)

    def __init__(self, connection):
        self._connection = connection

    async def __aenter__(self):
        return self._connection

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    def __await__(self):
        return self

    def __next__(self):
        raise StopIteration(self._connection)


class BindContext:
    def __init__(self, bind):
        self._bind = bind
        self._ctx = None

    async def __aenter__(self):
        args = {}
        if isinstance(self._bind, Connection):
            return self._bind
        elif isinstance(self._bind, GinoPool):
            args = dict(reuse=True)
        # noinspection PyArgumentList
        self._ctx = self._bind.acquire(**args)
        return await self._ctx.__aenter__()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        ctx, self._ctx = self._ctx, None
        if ctx is not None:
            await ctx.__aexit__(exc_type, exc_val, exc_tb)


class GinoExecutor:
    __slots__ = ('_query',)

    def __init__(self, query):
        self._query = query

    @property
    def query(self):
        return self._query

    def model(self, model):
        self._query = self._query.execution_options(model=weakref.ref(model))
        return self

    def return_model(self, switch):
        self._query = self._query.execution_options(return_model=switch)
        return self

    def timeout(self, timeout):
        self._query = self._query.execution_options(timeout)
        return self

    def get_bind(self, bind):
        return BindContext(bind or self._query.bind)

    async def all(self, *multiparams, bind=None, **params):
        async with self.get_bind(bind) as conn:
            return await conn.metadata.dialect.do_all(
                conn, self._query, *multiparams, **params)

    async def first(self, *multiparams, bind=None, **params):
        async with self.get_bind(bind) as conn:
            return await conn.metadata.dialect.do_first(
                conn, self._query, *multiparams, **params)

    async def scalar(self, *multiparams, bind=None, **params):
        async with self.get_bind(bind) as conn:
            return await conn.metadata.dialect.do_scalar(
                conn, self._query, *multiparams, **params)

    async def status(self, *multiparams, bind=None, **params):
        """
        You can parse the return value like this: https://git.io/v7oze
        """
        async with self.get_bind(bind) as conn:
            return await conn.metadata.dialect.do_status(
                conn, self._query, *multiparams, **params)

    def iterate(self, *multiparams, connection=None, **params):
        def env_factory():
            conn = connection or self._query.bind
            return conn, conn.metadata
        return GinoCursorFactory(env_factory, self._query, multiparams, params)


class Gino(sa.MetaData):
    model_base_classes = (CRUDModel,)
    query_executor = GinoExecutor

    def __init__(self, bind=None, dialect=None, model_classes=None,
                 query_ext=True, **kwargs):
        self._bind = None
        super().__init__(bind=bind, **kwargs)
        self.dialect = dialect or AsyncpgDialect()
        if model_classes is None:
            model_classes = self.model_base_classes
        self.Model = declarative_base(self, model_classes)
        for mod in json_support, sa_pg, sa:
            for key in mod.__all__:
                if not hasattr(self, key):
                    setattr(self, key, getattr(mod, key))
        if query_ext:
            Executable.gino = property(self.query_executor)

    @property
    def bind(self):
        return getattr(self._bind, 'get_current_connection',
                       lambda: None)() or self._bind

    # noinspection PyMethodOverriding
    @bind.setter
    def bind(self, val):
        self._bind = val

    @staticmethod
    def create_engine(*args, **kwargs):
        return create_engine(*args, **kwargs)
    # async def create_engine(self, dsn=None, *,
    #                         min_size=10,
    #                         max_size=10,
    #                         max_queries=50000,
    #                         max_inactive_connection_lifetime=300.0,
    #                         setup=None,
    #                         init=None,
    #                         loop=None,
    #                         **connect_kwargs):
    #     database = await AsyncpgDatabase.create(
    #         dsn,
    #         min_size=min_size, max_size=max_size,
    #         max_queries=max_queries, loop=loop, setup=setup, init=init,
    #         max_inactive_connection_lifetime=max_inactive_connection_lifetime,
    #         **connect_kwargs)
    #     rv = Engine(database, AsyncpgDialect())
    #     self.bind = rv
    #     return rv

    def compile(self, elem, *multiparams, **params):
        return self.dialect.compile(elem, *multiparams, **params)

    async def all(self, clause, *multiparams, bind=None, **params):
        async with BindContext(bind or self.bind) as conn:
            return await self.dialect.do_all(
                conn, clause, *multiparams, **params)

    async def first(self, clause, *multiparams, bind=None, **params):
        async with BindContext(bind or self.bind) as conn:
            return await self.dialect.do_first(
                conn, clause, *multiparams, **params)

    async def scalar(self, clause, *multiparams, bind=None, **params):
        async with BindContext(bind or self.bind) as conn:
            return await self.dialect.do_scalar(
                conn, clause, *multiparams, **params)

    async def status(self, clause, *multiparams, bind=None, **params):
        async with BindContext(bind or self.bind) as conn:
            return await self.dialect.do_status(
                conn, clause, *multiparams, **params)

    def iterate(self, clause, *multiparams, connection=None, **params):
        return GinoCursorFactory(lambda: (connection or self.bind, self),
                                 clause, multiparams, params)

    def acquire(self, *, timeout=None, reuse=True, lazy=False):
        method = getattr(self._bind, 'acquire', None)
        if method is None:
            return ConnectionAcquireContext(self._bind)
        else:
            return method(timeout=timeout, reuse=reuse, lazy=lazy)

    def transaction(self, *, isolation='read_committed', readonly=False,
                    deferrable=False, timeout=None, reuse=True):
        return GinoTransaction(self.acquire(timeout=timeout, reuse=reuse),
                               isolation, readonly, deferrable)
