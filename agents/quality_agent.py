"""
Quality Agent — LLM-as-judge that scores scripts before asset generation.

Evaluates scripts on a 4-axis rubric (hook, narrative, specificity, hinglish),
each scored 0-25 for a total of 0-100. Rejects below-threshold scripts before
they consume image/TTS budget.

Rubric loaded from config/quality_rubric.yaml. Thresholds:
    >= 80: auto-approve
    70-79: flag for human review in Telegram
    < 70:  auto-reject, regenerate with rewrite_suggestions (max 3 retries)
"""

from __future__ import annotations

import json
import os
import re
import logging
from dataclasses import dataclass, field, asdict

import yaml
from openai import OpenAI

from agents.budget_guard import budget_guard, log_cost
from agents.db import insert_quality_score

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUBRIC_PATH = os.path.join(BASE_DIR, "config", "quality_rubric.yaml")


@dataclass
class QualityScore:
    """Result of quality assessment for a script."""
    total: int = 0
    hook: int = 0
    narrative: int = 0
    specificity: int = 0
    hinglish: int = 0
    verdict: str = "reject"
    flags: list[str] = field(default_factory=list)
    rewrite_suggestions: list[str] = field(default_factory=list)


def _load_rubric() -> dict:
    """Load the quality rubric from config/quality_rubric.yaml."""
    if not os.path.exists(RUBRIC_PATH):
        logger.warning("Rubric not found at %s, using defaults", RUBRIC_PATH)
        return {
            "thresholds": {"approve": 80, "flag_for_review": 70, "max_retries": 3},
            "axes": {
                "hook": {"weight": 25, "description": "Does the first 8 seconds stop scrolling?"},
                "narrative": {"weight": 25, "description": "Problem → mechanism → resolution arc?"},
                "specificity": {"weight": 25, "description": "Concrete numbers, names, dates?"},
                "hinglish": {"weight": 25, "description": "Natural Hinglish, not robotic?"},
            },
        }
    with open(RUBRIC_PATH) as f:
        return yaml.safe_load(f)


def _determine_verdict(total: int, rubric: dict) -> str:
    """Map a total score to a verdict string."""
    thresholds = rubric.get("thresholds", {})
    if total >= thresholds.get("approve", 80):
        return "approve"
    elif total >= thresholds.get("flag_for_review", 70):
        return "flag_for_review"
    return "reject"


def _build_judge_prompt(script: dict, rubric: dict) -> str:
    """Build the LLM-as-judge prompt from script and rubric."""
    # Format rubric axes for the prompt
    axes_text = ""
    for axis_name, axis_config in rubric.get("axes", {}).items():
        axes_text += f"\n### {axis_name} (0-{axis_config['weight']})\n"
        axes_text += f"Question: {axis_config['description']}\n"
        criteria = axis_config.get("criteria", [])
        if criteria:
            axes_text += "Criteria:\n"
            for c in criteria:
                axes_text += f"  - {c}\n"
        scoring = axis_config.get("scoring", {})
        if scoring:
            axes_text += "Scoring guide:\n"
            for range_str, desc in scoring.items():
                axes_text += f"  {range_str}: {desc}\n"

    # Format script for evaluation
    script_json = json.dumps(script, indent=2, ensure_ascii=False)

    return f"""You are a YouTube content quality judge evaluating a Hinglish tech-explainer script.

Score the script on these 4 axes (each 0-25, total 0-100):
{axes_text}

SCRIPT TO EVALUATE:
{script_json}

Return a JSON object with exactly these keys:
{{
  "hook": <0-25>,
  "narrative": <0-25>,
  "specificity": <0-25>,
  "hinglish": <0-25>,
  "total": <sum of above>,
  "flags": ["<issue 1>", "<issue 2>"],
  "rewrite_suggestions": ["<suggestion 1>", "<suggestion 2>"]
}}

Rules:
- Be a strict but fair judge. Most average scripts score 60-75.
- Only score 80+ if genuinely strong on all axes.
- flags: list specific problems (empty list if none).
- rewrite_suggestions: actionable improvements the script writer can apply.
  Include these ONLY if total < 80. If total >= 80, return empty list.
- Return ONLY the JSON object, no markdown formatting."""


@budget_guard(provider="openai")
def _judge(config: dict, script: dict, rubric: dict) -> dict:
    """Call GPT-4o-mini to judge the script."""
    prompt = _build_judge_prompt(script, rubric)

    client = OpenAI(api_key=config["openai"]["api_key"])
    response = client.chat.completions.create(
        model=config["openai"].get("model", "gpt-4o-mini"),
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,  # Low temperature for consistent scoring
        max_tokens=800,
    )

    content = response.choices[0].message.content.strip()
    # Strip markdown fences if present
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\n?", "", content)
        content = re.sub(r"\n?```$", "", content)

    result = json.loads(content)

    # Estimate cost: ~2000 input + 500 output tokens for GPT-4o-mini
    estimated_cost = 0.013 * 2.0 + 0.050 * 0.5  # INR ~0.051
    return result, estimated_cost


def score(script: dict, config: dict, run_id: str = "") -> QualityScore:
    """Score a script using the LLM-as-judge rubric.

    Args:
        script: The script dict from script_agent (title, intro_hook, scenes, outro).
        config: Pipeline config dict (needs openai.api_key).
        run_id: Pipeline run identifier for DB tracking.

    Returns:
        QualityScore with total (0-100), per-axis breakdown, verdict, and
        rewrite_suggestions if rejected.
    """
    rubric = _load_rubric()

    print(f"  Quality: scoring script '{script.get('title', 'untitled')}'...")
    result = _judge(config, script, rubric)

    # Clamp scores to valid ranges
    hook = max(0, min(25, int(result.get("hook", 0))))
    narrative = max(0, min(25, int(result.get("narrative", 0))))
    specificity = max(0, min(25, int(result.get("specificity", 0))))
    hinglish = max(0, min(25, int(result.get("hinglish", 0))))
    total = hook + narrative + specificity + hinglish

    verdict = _determine_verdict(total, rubric)

    qs = QualityScore(
        total=total,
        hook=hook,
        narrative=narrative,
        specificity=specificity,
        hinglish=hinglish,
        verdict=verdict,
        flags=result.get("flags", []),
        rewrite_suggestions=result.get("rewrite_suggestions", []),
    )

    print(f"  Quality: {total}/100 — hook:{hook} narrative:{narrative} "
          f"specificity:{specificity} hinglish:{hinglish} → {verdict}")

    # Write to DB
    if run_id:
        insert_quality_score(
            run_id=run_id,
            total=total,
            hook=hook,
            narrative=narrative,
            specificity=specificity,
            hinglish=hinglish,
            verdict=verdict,
            flags=qs.flags,
        )

    return qs


def score_with_retry(
    script_generator,
    config: dict,
    topic_data: dict,
    fact_sheet: dict,
    run_id: str = "",
    max_retries: int = 3,
) -> tuple[dict, QualityScore]:
    """Score a script and retry generation if rejected.

    Args:
        script_generator: Callable(config, topic_data, fact_sheet, suggestions) -> script dict.
        config: Pipeline config dict.
        topic_data: Topic data from topic_agent.
        fact_sheet: Research fact sheet from research_agent.
        run_id: Pipeline run identifier.
        max_retries: Maximum number of regeneration attempts.

    Returns:
        Tuple of (final_script, final_quality_score).
        If all retries exhausted, returns the last script with its score
        (verdict will still be 'reject').
    """
    rubric = _load_rubric()
    max_retries = rubric.get("thresholds", {}).get("max_retries", max_retries)

    suggestions = []
    for attempt in range(1, max_retries + 1):
        script = script_generator(config, topic_data, fact_sheet, suggestions)
        qs = score(script, config, run_id=f"{run_id}_attempt{attempt}")

        if qs.verdict in ("approve", "flag_for_review"):
            return script, qs

        if attempt < max_retries:
            print(f"  Quality: rejected (attempt {attempt}/{max_retries}), retrying...")
            suggestions = qs.rewrite_suggestions
        else:
            print(f"  Quality: rejected after {max_retries} attempts. Returning last script.")

    return script, qs
