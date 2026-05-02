"""
Research Agent — Web research → verified fact sheet with sources.

Bridge between topic_agent and script_agent. Takes a topic, produces a
structured fact sheet with sourced key facts, narrative arc, technical terms,
and common misconceptions.

Fact sheets are cached in data/fact_sheets/<topic_slug>.json for 90 days.
"""

from __future__ import annotations

import json
import os
import re
import time
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Any

from openai import OpenAI

from agents.budget_guard import budget_guard, log_cost

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FACT_SHEETS_DIR = os.path.join(BASE_DIR, "data", "fact_sheets")
CACHE_TTL_DAYS = 90


@dataclass
class FactSheet:
    """Structured research output for a single topic."""
    topic: str = ""
    key_facts: list[dict[str, Any]] = field(default_factory=list)
    narrative_arc: dict[str, str] = field(default_factory=dict)
    technical_terms: list[dict[str, str]] = field(default_factory=list)
    common_misconceptions: list[str] = field(default_factory=list)
    credibility_signals: list[str] = field(default_factory=list)
    researched_at: str = ""


def _slugify(topic: str) -> str:
    """Convert a topic string to a filesystem-safe slug."""
    slug = topic.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:80]


def _load_cached(topic_slug: str) -> dict | None:
    """Load a cached fact sheet if within TTL."""
    path = os.path.join(FACT_SHEETS_DIR, f"{topic_slug}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        researched_at = data.get("researched_at", "")
        if researched_at:
            dt = datetime.fromisoformat(researched_at)
            if datetime.now() - dt < timedelta(days=CACHE_TTL_DAYS):
                logger.info("Cache hit for topic: %s", topic_slug)
                return data
            logger.info("Cache expired for topic: %s", topic_slug)
        return None
    except (json.JSONDecodeError, ValueError):
        return None


def _save_cache(topic_slug: str, fact_sheet: dict) -> str:
    """Write a fact sheet to the cache directory."""
    os.makedirs(FACT_SHEETS_DIR, exist_ok=True)
    path = os.path.join(FACT_SHEETS_DIR, f"{topic_slug}.json")
    with open(path, "w") as f:
        json.dump(fact_sheet, f, indent=2, ensure_ascii=False)
    return path


def _web_search(query: str, config: dict) -> list[dict]:
    """Run a web search and return results.

    Uses the Serper API (serper.dev) if configured, otherwise falls back
    to a simple DuckDuckGo scrape via the duckduckgo-search library.
    """
    # Try Serper API first (higher quality)
    serper_key = config.get("serper", {}).get("api_key", "")
    if serper_key:
        return _search_serper(query, serper_key)

    # Fallback: duckduckgo-search (free, no API key)
    return _search_ddg(query)


def _search_serper(query: str, api_key: str) -> list[dict]:
    """Search via Serper.dev API."""
    import requests
    resp = requests.post(
        "https://google.serper.dev/search",
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        json={"q": query, "num": 5},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    results = []
    for item in data.get("organic", [])[:5]:
        results.append({
            "title": item.get("title", ""),
            "snippet": item.get("snippet", ""),
            "url": item.get("link", ""),
        })
    return results


def _search_ddg(query: str) -> list[dict]:
    """Search via duckduckgo-search library (free, no key)."""
    try:
        from duckduckgo_search import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=5):
                results.append({
                    "title": r.get("title", ""),
                    "snippet": r.get("body", ""),
                    "url": r.get("href", ""),
                })
        return results
    except ImportError:
        logger.warning("duckduckgo-search not installed. Returning empty results.")
        return []
    except Exception as e:
        logger.warning("DuckDuckGo search failed: %s", e)
        return []


def _build_search_queries(topic: str, cluster_context: dict | None) -> list[str]:
    """Generate 5-8 search queries for comprehensive research."""
    queries = [
        f"{topic} how it works explained",
        f"{topic} technical architecture",
        f"{topic} India statistics facts 2024 2025",
        f"{topic} common misconceptions",
        f"{topic} history origin",
    ]
    # Add context-aware queries if cluster info available
    if cluster_context:
        theme = cluster_context.get("theme", "")
        if theme:
            queries.append(f"{topic} {theme} technical details")
    # Add a Hindi-context query for Indian-specific nuance
    queries.append(f"{topic} India kaise kaam karta hai")
    return queries[:8]


SYNTHESIS_PROMPT = """You are a research analyst preparing a fact sheet for a Hinglish tech-explainer YouTube video.

Given the search results below, produce a structured fact sheet in JSON format.

TOPIC: {topic}

SEARCH RESULTS:
{search_results}

Produce a JSON object with exactly these keys:
{{
  "topic": "<the topic>",
  "key_facts": [
    {{"fact": "<specific, verifiable fact>", "source_url": "<URL if available>", "confidence": <0.0-1.0>}}
  ],
  "narrative_arc": {{
    "hook_angle": "<surprising fact or question to open with>",
    "problem": "<what problem does this solve / why does it matter>",
    "mechanism": "<how it actually works, step by step>",
    "resolution": "<the 'aha' moment or current state>"
  }},
  "technical_terms": [
    {{"term": "<technical term>", "explanation": "<simple explanation>"}}
  ],
  "common_misconceptions": ["<misconception 1>", "<misconception 2>"],
  "credibility_signals": ["<authoritative source 1>", "<authoritative source 2>"]
}}

Rules:
- Include 5-10 key facts with specific numbers, dates, or names
- Every fact should be verifiable from the search results
- Confidence should be 0.9+ only if multiple sources confirm it
- Include at least 3 technical terms
- Include at least 2 misconceptions
- Credibility signals = names of authoritative sources (RBI, NPCI, IEEE, etc.)
- All content in English (the script agent will convert to Hinglish later)

Return ONLY the JSON object, no markdown formatting."""


@budget_guard(provider="openai")
def _synthesize(config: dict, topic: str, all_results: list[dict]) -> dict:
    """Synthesize search results into a structured fact sheet via GPT."""
    # Format search results for the prompt
    formatted = []
    for i, r in enumerate(all_results, 1):
        formatted.append(
            f"[{i}] {r.get('title', 'No title')}\n"
            f"    URL: {r.get('url', 'N/A')}\n"
            f"    {r.get('snippet', 'No snippet')}"
        )
    search_text = "\n\n".join(formatted) if formatted else "(No search results available)"

    prompt = SYNTHESIS_PROMPT.format(topic=topic, search_results=search_text)

    client = OpenAI(api_key=config["openai"]["api_key"])
    response = client.chat.completions.create(
        model=config["openai"].get("model", "gpt-4o-mini"),
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=2000,
    )

    content = response.choices[0].message.content.strip()
    # Strip markdown fences if present
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\n?", "", content)
        content = re.sub(r"\n?```$", "", content)

    fact_sheet = json.loads(content)

    # Estimate cost: ~1500 input + 1500 output tokens for GPT-4o-mini
    estimated_cost = 0.013 * 1.5 + 0.050 * 1.5  # INR
    return fact_sheet, estimated_cost


def research(topic: str, config: dict, cluster_context: dict | None = None) -> dict:
    """Research a topic and produce a verified fact sheet.

    Args:
        topic: The topic string to research (e.g. "How UPI works").
        config: Pipeline config dict (needs openai.api_key).
        cluster_context: Optional dict with cluster metadata for context.

    Returns:
        dict matching the FactSheet structure.
    """
    slug = _slugify(topic)

    # Check cache first
    cached = _load_cached(slug)
    if cached:
        print(f"  Research: cache hit for '{topic}'")
        return cached

    print(f"  Research: running web search for '{topic}'...")

    # Build and execute search queries
    queries = _build_search_queries(topic, cluster_context)
    all_results = []

    for q in queries:
        try:
            results = _web_search(q, config)
            all_results.extend(results)
            time.sleep(0.5)  # Be polite to search APIs
        except Exception as e:
            logger.warning("Search failed for '%s': %s", q, e)

    # Deduplicate by URL
    seen_urls = set()
    unique_results = []
    for r in all_results:
        url = r.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_results.append(r)

    print(f"  Research: {len(unique_results)} unique results from {len(queries)} queries")

    # Synthesize via GPT
    print(f"  Research: synthesizing fact sheet...")
    fact_sheet = _synthesize(config, topic, unique_results)
    fact_sheet["researched_at"] = datetime.now().isoformat()

    # Cache the result
    path = _save_cache(slug, fact_sheet)
    print(f"  Research: cached to {path}")

    return fact_sheet
