"""Tests for the approximate gloss-keyword topic tagger."""

import pytest

from backend.data.assign_topic import TOPICS, assign_topic


@pytest.mark.parametrize(
    ("gloss", "expected"),
    [
        ("house, building", "home"),
        ("the kitchen table", "food"),  # 'kitchen' -> food wins (listed before home)
        ("a train station", "transport"),
        ("teacher at a school", "education"),
        ("mother and father", "family"),
        ("to pay the price", "money"),
        ("doctor in a hospital", "health"),
        ("tomorrow morning", "time"),
    ],
)
def test_known_glosses(gloss, expected):
    assert assign_topic(gloss) == expected


def test_no_match_returns_none():
    assert assign_topic("nevertheless") is None
    assert assign_topic("") is None
    assert assign_topic(None) is None


def test_only_whole_word_matches():
    # 'carpet' contains 'car' but must not be tagged transport
    assert assign_topic("a soft carpet") is None


def test_every_result_is_a_declared_topic():
    for gloss in ("house", "train", "school", "money", "doctor"):
        t = assign_topic(gloss)
        assert t is None or t in TOPICS
