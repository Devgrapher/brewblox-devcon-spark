"""
Offers block metadata CRUD
"""


import asyncio
from abc import ABC, abstractmethod
from concurrent.futures import CancelledError
from datetime import timedelta
from typing import Any, Callable, List

from aiotinydb import AIOImmutableJSONStorage, AIOJSONStorage, AIOTinyDB
from aiotinydb.middleware import CachingMiddleware
from deprecated import deprecated
from tinydb import Query, TinyDB
from tinydb.storages import MemoryStorage

from brewblox_devcon_spark import brewblox_logger

OBJECT_TYPE_ = dict
ACTION_RETURN_TYPE_ = Any
DB_FUNC_TYPE_ = Callable[[TinyDB], ACTION_RETURN_TYPE_]

ACTION_TIMEOUT = timedelta(seconds=5)
DATABASE_RETRY_INTERVAL = timedelta(seconds=1)

LOGGER = brewblox_logger(__name__)


class DataStore(ABC):

    def __str__(self):
        return f'<{type(self).__name__}>'

    async def start(self, loop: asyncio.BaseEventLoop):
        """
        Implementing classes may require a startup function.
        They can (optionally) override this.
        """
        pass

    async def close(self):
        """
        Implementing classes may require a shutdown function.
        They can (optionally) override this.
        """
        pass

    @abstractmethod
    async def _do_with_db(self, func: DB_FUNC_TYPE_) -> ACTION_RETURN_TYPE_:
        """
        Should be overridden: governs how database calls are processed.
        Various functions in DataStore supply the logic,
        while the subclasses decide how the database is provided.

        Overriding functions should behave like they called:

            return func(my_database)
        """
        pass  # pragma: no cover

    @deprecated('Debugging function')
    async def all(self) -> List[OBJECT_TYPE_]:
        return await self._do_with_db(lambda db: db.all())

    async def purge(self):
        """
        Clears the entire database.
        """
        return await self._do_with_db(lambda db: db.purge())

    async def find_by_key(self, id_key: str, id_val: Any) -> List[OBJECT_TYPE_]:
        """
        Returns all documents where document[id_key] == id_val
        """
        return await self._do_with_db(lambda db: db.search(Query()[id_key] == id_val))

    async def insert(self, obj: dict):
        """
        Inserts document in data store. Does not verify uniqueness of any of its keys.
        """
        return await self._do_with_db(lambda db: db.insert(obj))

    async def insert_multiple(self, objects: List):
        """
        Inserts multiple documents in data store. Does not verify uniqueness.
        """
        return await self._do_with_db(lambda db: db.insert_multiple(objects))

    async def insert_unique(self, id_key: str, obj: dict):
        """
        Inserts document in data store.
        Asserts that no other document has the same value for the id_key.
        """
        def func(db):
            id = obj[id_key]
            assert not db.contains(Query()[id_key] == id), f'{id} already exists'
            db.insert(obj)

        return await self._do_with_db(func)

    async def update(self, id_key: str, id_val: Any, obj: dict):
        """
        Replaces all documents in data store where document[id_key] == id_val.
        """
        return await self._do_with_db(
            lambda db: db.update(obj, Query()[id_key] == id_val)
        )

    async def update_unique(self, id_key: str, id_val: Any, obj: dict, unique_key: str=None):
        """
        Replaces a document in data store where document[id_key] == id_val.
        Creates new document if it did not yet exist.
        Asserts that only one document will be updated.
        Asserts that no other documents exist where document[unique_key] == obj[unique_key]
        """
        def func(db):
            query = Query()[id_key] == id_val
            assert db.count(query) <= 1, f'Multiple documents with {id_key}={id_val} exist'
            # Check for documents that already use the to be inserted unique key
            if unique_key is not None:
                unique_id = obj[unique_key]
                assert not db.contains(Query()[unique_key] == unique_id), \
                    f'A document already exists with {unique_key}={unique_id}'

            db.upsert(obj, query)

        return await self._do_with_db(func)


class MemoryDataStore(DataStore):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._db = TinyDB(storage=CachingMiddleware(MemoryStorage))

    async def _do_with_db(self, func: DB_FUNC_TYPE_):
        return func(self._db)


class FileDataStore(DataStore):

    class Action():
        """
        Used for centralized file access management.
        Actions allow separation of call and result retrieval.
        """

        def __init__(self, func: Callable, loop: asyncio.BaseEventLoop):
            self._future: asyncio.Future = loop.create_future()
            self._func: Callable = func

        def do(self, db):
            try:
                self._future.set_result(self._func(db))
            except Exception as ex:
                self._future.set_exception(ex)

        async def wait_result(self) -> ACTION_RETURN_TYPE_:
            return await asyncio.wait_for(self._future, timeout=ACTION_TIMEOUT.seconds)

    ######################################################################

    def __init__(self, filename: str, read_only: bool, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._filename: str = filename

        storage = AIOImmutableJSONStorage if read_only else AIOJSONStorage
        self._storage = CachingMiddleware(storage)

        self._pending_actions: asyncio.Queue = None
        self._runner: asyncio.Task = None
        self._loop: asyncio.BaseEventLoop = None

    def __str__(self):
        return f'<{type(self).__name__} for {self._filename}>'

    # Overrides DataStore
    async def start(self, loop: asyncio.BaseEventLoop):
        self._loop = loop
        self._pending_actions = asyncio.Queue()
        self._runner = loop.create_task(self._run())

    # Overrides DataStore
    async def close(self):
        if self._runner:
            self._runner.cancel()
            await asyncio.wait([self._runner])
            self._runner = None

    # Overrides DataStore
    async def _do_with_db(self, func: DB_FUNC_TYPE_) -> ACTION_RETURN_TYPE_:
        assert self._pending_actions is not None, f'{self} not started before functions were called'
        action = FileDataStore.Action(func, self._loop)
        await self._pending_actions.put(action)
        return await action.wait_result()

    async def _run(self):
        while True:
            try:
                async with AIOTinyDB(self._filename, storage=CachingMiddleware(AIOJSONStorage)) as db:
                    LOGGER.info(f'{self} now available')
                    while True:
                        action = await self._pending_actions.get()
                        action.do(db)

            except CancelledError:
                LOGGER.debug(f'{self} shutdown')
                break

            except Exception as ex:  # pragma: no cover
                LOGGER.warn(f'{self} {type(ex).__name__}: {ex}')
                # Don't go crazy on persistent errors
                await asyncio.sleep(DATABASE_RETRY_INTERVAL.seconds)
