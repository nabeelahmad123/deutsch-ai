"""Approximate topic tag for a word, from its English gloss.

Keyword lookup only -- NOT a classifier. Most words match nothing and stay
``None`` (general vocabulary); that is expected and correct. The tag exists so
``get_new_words(topic=...)`` (MCP server #1) and the session composer have a
coarse thematic filter aligned with ``users.target`` (work / travel / exam).

Document as an approximation (CLAUDE.md section 6): a gloss-keyword hit is a
hint, not ground truth.
"""

from __future__ import annotations

import re

# Ordered: the first topic with a keyword hit wins. Keep lists short and
# high-precision -- a wrong tag is worse than no tag here.
_TOPIC_KEYWORDS_RAW: tuple[tuple[str, str], ...] = (
    (
        "work",
        "work job office employee employer colleague salary wage company business"
        " manager meeting contract career profession staff boss customer client",
    ),
    (
        "travel",
        "travel journey trip flight airport hotel luggage passport ticket tourist"
        " vacation holiday abroad border map suitcase arrival departure",
    ),
    (
        "transport",
        "car train bus bicycle bike subway tram taxi road street traffic drive"
        " railway station engine wheel highway",
    ),
    (
        "food",
        "food eat drink meal bread meat fruit vegetable cook kitchen restaurant"
        " breakfast lunch dinner coffee tea wine beer sugar salt cheese soup recipe"
        " hungry thirsty taste",
    ),
    (
        "home",
        "house home room bedroom bathroom door window wall roof furniture table chair"
        " bed garden apartment flat floor stairs key",
    ),
    (
        "health",
        "health doctor hospital medicine illness sick disease pain nurse patient"
        " pharmacy injury wound fever treatment healthy heal",
    ),
    (
        "body",
        "head hand arm leg foot eye ear nose mouth tooth hair finger shoulder knee"
        " heart skin bone blood brain",
    ),
    (
        "education",
        "school teacher pupil student class lesson book read write learn study"
        " university exam homework pencil pen knowledge education library language",
    ),
    (
        "nature",
        "tree flower plant forest mountain river lake sea ocean sky sun moon star"
        " rain snow wind weather animal bird fish grass stone field",
    ),
    (
        "family",
        "family mother father parent child son daughter brother sister grandmother"
        " grandfather husband wife uncle aunt cousin baby marriage",
    ),
    (
        "money",
        "money price cost buy sell pay bank cash coin expensive cheap account credit"
        " debt tax budget wealth poor rich",
    ),
    (
        "time",
        "time day week month year hour minute morning evening night today tomorrow"
        " yesterday clock calendar season early late",
    ),
    (
        "communication",
        "speak talk say tell ask answer letter phone call message email news"
        " newspaper conversation word question",
    ),
    (
        "clothing",
        "clothes shirt trousers pants dress skirt shoe jacket coat hat sock glove"
        " wear fashion pocket button sleeve",
    ),
)

_TOPIC_KEYWORDS: tuple[tuple[str, frozenset[str]], ...] = tuple(
    (topic, frozenset(words.split())) for topic, words in _TOPIC_KEYWORDS_RAW
)

TOPICS: tuple[str, ...] = tuple(t for t, _ in _TOPIC_KEYWORDS)

_WORD_RE = re.compile(r"[a-z]+")


def assign_topic(translation_en: str | None, lemma: str | None = None) -> str | None:
    """Return a topic slug, or None if nothing matches (the common case)."""
    if not translation_en:
        return None
    tokens = set(_WORD_RE.findall(translation_en.lower()))
    for topic, keywords in _TOPIC_KEYWORDS:
        if tokens & keywords:
            return topic
    return None
