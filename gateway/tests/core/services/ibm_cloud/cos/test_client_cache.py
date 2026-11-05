"""Unit tests for CosClientCache."""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from core.ibm_cloud.cos.client_cache import CosClientCache

_CLOCK = "core.ibm_cloud.cos.client_cache.time.monotonic"


def test_the_client_is_built_once_and_reused():
    cache = CosClientCache(ttl_seconds=60)
    build = MagicMock(side_effect=lambda: object())

    first = cache.get("project", build)
    second = cache.get("project", build)

    assert first is second
    build.assert_called_once()


def test_each_key_has_its_own_client():
    cache = CosClientCache(ttl_seconds=60)

    assert cache.get("a", object) is not cache.get("b", object)


def test_the_client_is_built_again_after_the_ttl():
    cache = CosClientCache(ttl_seconds=60)
    clock = [1000.0]
    build = MagicMock(side_effect=lambda: object())

    with patch(_CLOCK, side_effect=lambda: clock[0]):
        first = cache.get("project", build)
        clock[0] += 61
        second = cache.get("project", build)

    assert first is not second
    assert build.call_count == 2


def test_the_rebuilt_client_replaces_the_stale_one():
    """Otherwise every later call would build again."""
    cache = CosClientCache(ttl_seconds=60)
    clock = [1000.0]
    build = MagicMock(side_effect=lambda: object())

    with patch(_CLOCK, side_effect=lambda: clock[0]):
        cache.get("project", build)
        clock[0] += 61
        cache.get("project", build)
        clock[0] += 1
        cache.get("project", build)

    assert build.call_count == 2


def test_a_failed_build_is_not_cached():
    cache = CosClientCache(ttl_seconds=60)
    build = MagicMock(side_effect=[RuntimeError("down"), "client"])

    with pytest.raises(RuntimeError):
        cache.get("project", build)

    assert cache.get("project", build) == "client"


def test_clear_drops_every_client():
    cache = CosClientCache(ttl_seconds=60)
    build = MagicMock(side_effect=lambda: object())
    cache.get("project", build)

    cache.clear()
    cache.get("project", build)

    assert build.call_count == 2


def _ask_from_threads(cache, key, build, threads_count=8):
    """Several threads ask for the same key at the same moment. Returns what each of them got."""
    barrier = threading.Barrier(threads_count)
    results = [None] * threads_count

    def ask(index):
        barrier.wait()
        results[index] = cache.get(key, build)

    threads = [threading.Thread(target=ask, args=(index,)) for index in range(threads_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results


def test_threads_asking_for_the_same_key_at_once_build_it_once():
    cache = CosClientCache(ttl_seconds=60)
    builds = []

    def slow_build():
        # a network call: long enough for every other thread to reach the cache while this one is still building
        time.sleep(0.2)
        builds.append(1)
        return object()

    results = _ask_from_threads(cache, "project", slow_build)

    assert len(builds) == 1
    assert len({id(client) for client in results}) == 1


def test_a_cached_client_is_returned_while_another_one_is_being_built():
    """A hit never waits: only a miss takes the build lock."""
    cache = CosClientCache(ttl_seconds=60)
    cache.get("cached", lambda: "cached client")
    slow_started = threading.Event()
    release_slow = threading.Event()

    def slow_build():
        slow_started.set()
        assert release_slow.wait(timeout=10)
        return "slow client"

    slow = threading.Thread(target=lambda: cache.get("slow", slow_build))
    slow.start()
    assert slow_started.wait(timeout=10)

    answered = []
    hit = threading.Thread(target=lambda: answered.append(cache.get("cached", lambda: "never built")))
    hit.start()
    hit.join(timeout=5)
    release_slow.set()
    slow.join()

    assert answered == ["cached client"]
