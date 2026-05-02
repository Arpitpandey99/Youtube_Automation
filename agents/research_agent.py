"""
Research Agent — Web research → verified fact sheet with sources.

Bridge between topic_agent and script_agent. Takes a topic, produces a
structured fact sheet with sourced key facts, narrative arc, technical terms,
and common misconceptions. This is the single biggest differentiator between
"AI slop about UPI" and "actually-correct video about UPI."

Fact sheets are cached in data/fact_sheets/<topic_slug>.json for 90 days.

# SCHEMA: Uses no new tables. Writes to filesystem (data/fact_sheets/).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FactSheet:
    """Structured research output for a single topic.

    Attributes:
        topic: The researched topic string.
        key_facts: List of dicts with 'fact', 'source_url', 'confidence' keys.
        narrative_arc: Dict with 'hook_angle', 'problem', 'mechanism', 'resolution'.
        technical_terms: List of dicts with 'term' and 'explanation' keys.
        common_misconceptions: List of misconception strings.
        credibility_signals: List of authoritative source names.
    """
    topic: str = ""
    key_facts: list[dict[str, Any]] = field(default_factory=list)
    narrative_arc: dict[str, str] = field(default_factory=dict)
    technical_terms: list[dict[str, str]] = field(default_factory=list)
    common_misconceptions: list[str] = field(default_factory=list)
    credibility_signals: list[str] = field(default_factory=list)


def research(topic: str, cluster_context: dict | None = None) -> dict:
    """Research a topic and produce a verified fact sheet.

    Inputs:
        topic: The topic string to research (e.g. "How UPI works").
        cluster_context: Optional dict with cluster metadata for context
                         (cluster_name, theme, related_topics).

    Outputs:
        dict matching the FactSheet structure with keys:
            topic, key_facts, narrative_arc, technical_terms,
            common_misconceptions, credibility_signals.

    Implementation plan:
        1. Check cache (data/fact_sheets/<slug>.json, 90-day TTL)
        2. If miss: run 5-8 web searches via rate_limiter
        3. GPT-4o-mini synthesis with strict JSON schema
        4. Validate and cache result
        5. Wrapped in @budget_guard("openai", 500)
    """
    # TODO: Implement web search + GPT synthesis
    # TODO: Add caching with 90-day TTL
    # TODO: Add @budget_guard decorators
    raise NotImplementedError("research_agent.research() not yet implemented")


def _load_cached_fact_sheet(topic_slug: str) -> dict | None:
    """Load a cached fact sheet if it exists and is within the 90-day TTL.

    Inputs:
        topic_slug: URL-safe slug derived from the topic string.

    Outputs:
        dict with fact sheet data, or None if cache miss or expired.
    """
    # TODO: Check data/fact_sheets/<topic_slug>.json
    # TODO: Validate TTL (90 days)
    raise NotImplementedError


def _cache_fact_sheet(topic_slug: str, fact_sheet: dict) -> str:
    """Write a fact sheet to the cache directory.

    Inputs:
        topic_slug: URL-safe slug for the filename.
        fact_sheet: The fact sheet dict to cache.

    Outputs:
        str path to the cached file.
    """
    # TODO: Write to data/fact_sheets/<topic_slug>.json
    raise NotImplementedError


def _slugify(topic: str) -> str:
    """Convert a topic string to a filesystem-safe slug.

    Inputs:
        topic: Raw topic string (e.g. "How UPI works?").

    Outputs:
        str slug (e.g. "how-upi-works").
    """
    # TODO: Implement slug conversion
    raise NotImplementedError
