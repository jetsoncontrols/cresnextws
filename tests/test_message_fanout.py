"""0.3.0: one call per message for a full-message subscription, and the path match cache.

Oak Forest, 2026-11-05: a DM-NAX MP2 push matched ha-nax's full-message Players subscription
once per nested path, so its handler ran ~5 times per message (173 runs for 33 messages), each
re-merging the same message; with fnmatch for every path x subscription (50,000 calls) that was
a 0.13-0.20 s event-loop stall per track change.
"""

from unittest.mock import MagicMock

import pytest

from cresnextws import DataEventManager

PUSH = {
    "Device": {
        "MediaPlayerNeXt": {
            "Players": {
                "p3": {"Player": {"NowPlayingData": {"TrackTitle": "Everlong", "ArtistName": "Foo Fighters"}}},
                "p1": {"Player": {"State": "idle"}},
            }
        }
    }
}


@pytest.fixture
def manager():
    return DataEventManager(MagicMock())


def test_a_full_message_subscription_is_called_once_per_message(manager):
    calls = []
    manager.subscribe("/Device/MediaPlayerNeXt/Players", lambda p, m: calls.append(p), full_message=True)
    manager._process_message(PUSH)
    assert calls == ["/Device/MediaPlayerNeXt/Players"]  # the first path of it that matched
    manager._process_message(PUSH)
    assert len(calls) == 2  # once per MESSAGE, not once ever


def test_a_per_path_subscription_is_still_called_for_each_matching_path(manager):
    seen = []
    manager.subscribe("/Device/MediaPlayerNeXt/Players/*/Player/NowPlayingData/TrackTitle",
                      lambda p, d: seen.append((p, d)))
    manager.subscribe("/Device/MediaPlayerNeXt/Players/p1", lambda p, d: seen.append((p, d)))
    manager._process_message(PUSH)
    assert ("/Device/MediaPlayerNeXt/Players/p3/Player/NowPlayingData/TrackTitle", "Everlong") in seen
    assert any(p == "/Device/MediaPlayerNeXt/Players/p1/Player/State" for p, _ in seen)  # a child


def test_the_match_cache_follows_subscribe_unsubscribe_and_clear(manager):
    a, b = [], []
    manager.subscribe("/Device/MediaPlayerNeXt/Players", lambda p, m: a.append(p), full_message=True)
    manager._process_message(PUSH)
    assert manager._match_cache  # filled
    sub_b = manager.subscribe("/Device/MediaPlayerNeXt/Players/p3", lambda p, d: b.append(p))
    assert not manager._match_cache  # a new subscription invalidates it
    manager._process_message(PUSH)
    assert b
    manager.unsubscribe(sub_b)
    b.clear()
    manager._process_message(PUSH)
    assert not b
    manager.clear_subscriptions()
    a.clear()
    manager._process_message(PUSH)
    assert not a and not any(manager._match_cache.values())  # refilled, matching nothing


def test_a_callback_that_unsubscribes_another_mid_message_is_safe(manager):
    later = []
    ids = {}

    def first(path, msg):
        manager.unsubscribe(ids["later"])

    manager.subscribe("/Device/MediaPlayerNeXt/Players", first, full_message=True)
    ids["later"] = manager.subscribe("/Device/MediaPlayerNeXt/Players/p3", lambda p, d: later.append(p))
    manager._process_message(PUSH)
    assert later == []  # removed before its paths came up: never called


def test_no_debug_string_is_built_when_debug_is_off(manager, caplog):
    class Loud(dict):
        def __repr__(self):  # formatting the message is the cost being avoided
            raise AssertionError("message formatted with debug off")

    import logging

    logging.getLogger("cresnextws.data_event_manager").setLevel(logging.INFO)
    manager._process_message(Loud(PUSH))
