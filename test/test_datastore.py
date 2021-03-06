"""
Tests datastore.py
"""

import asyncio
import os

import pytest
from brewblox_devcon_spark import datastore

TESTED = datastore.__name__


@pytest.fixture
def database_test_file():
    def remove(f):
        try:
            os.remove(f)
        except FileNotFoundError:
            pass

    f = 'test_file.json'
    remove(f)
    yield f
    remove(f)


@pytest.fixture
async def file_store(app, client, database_test_file, loop):
    store = datastore.FileDataStore(
        filename=database_test_file,
        read_only=False,
    )
    await store.start(loop=loop)
    await store.purge()
    yield store
    await store.close()


@pytest.fixture
async def memory_store(app, client, loop):
    store = datastore.MemoryDataStore()
    await store.start(loop=loop)
    yield store
    await store.close()


@pytest.fixture
async def stores(file_store, memory_store):
    return [file_store, memory_store]


@pytest.fixture
def obj():
    return {
        'service_id': 'pancakes',
        'type': 6,
        'obj': {
            'settings': {
                'address': 'KP7p/ggAABc=',
                'offset': 0
            }
        }
    }


async def test_basics(client, stores, loop):
    for store in stores:
        assert str(store)

        await store.close()
        await store.close()

        await store.start(loop)
        await store.close()


async def test_insert(stores, obj):
    for store in stores:
        await store.insert(obj)
        assert await store.find_by_key('service_id', obj['service_id']) == [obj]


async def test_insert_multiple(stores, obj):
    for store in stores:
        await store.insert_multiple([obj]*100)
        assert len(await store.find_by_key('service_id', obj['service_id'])) == 100


async def test_insert_unique(stores, obj):
    for store in stores:
        await store.insert_unique('service_id', obj)

        # already exists
        with pytest.raises(AssertionError):
            await store.insert_unique('service_id', obj)

        # obj[pancakes] does not exist
        with pytest.raises(KeyError):
            await store.insert_unique('pancakes', obj)

        assert await store.find_by_key('service_id', obj['service_id']) == [obj]


async def test_update(stores):
    for store in stores:
        await store.insert_multiple([{'id': i} for i in range(10)])
        await store.update('id', 6, {'something': 'different'})

        obj = await store.find_by_key('id', 6)
        assert obj[0]['something'] == 'different'

        await store.update('id', 6, {'id': 101})
        assert not await store.find_by_key('id', 6)


async def test_update_unique(stores, obj):
    for store in stores:
        await store.insert_multiple([obj]*10)
        await store.insert_multiple([{'service_id': i} for i in range(10)])

        await store.update_unique('service_id', 8, {'something': 'different'})

        with pytest.raises(AssertionError):
            await store.update_unique('service_id', obj['service_id'], obj, None)

        with pytest.raises(AssertionError):
            await store.update_unique('service_id', 2, obj, 'service_id')


async def test_spam(stores, obj):
    """
    Tests coherence of database write actions when running many non-sequential async tasks
    """
    for store in stores:
        data = [dict(obj) for i in range(100)]
        await asyncio.wait([asyncio.ensure_future(store.insert(d)) for d in data])

        result = await store.all()
        assert len(data) == len(result)


async def test_exception_handling(stores, mocker):
    for store in stores:
        with pytest.raises(ArithmeticError):
            await store._do_with_db(lambda db: 1 / 0)
