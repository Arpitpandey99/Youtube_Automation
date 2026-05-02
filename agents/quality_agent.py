"""
Quality Agent — LLM-as-judge that scores scripts before asset generation.

Evaluates scripts on a 4-axis rubric (hook, narrative, specificity, hinglish),
each scored 0-25 for a total of 0-100. Rejects below-threshold scripts before
they consume image/TTS budget. The AI slop firewall.

Rubric is loaded from config/quality_rubric.yaml so it can be tuned without
code changes.

Thresholds:
    >= 80: auto-approve, proceed to asset generation
    70-79: flag for human review in Telegram
    < 70:  auto-reject, regenerate with rewrite_suggestions (max 3 retries)

# SCHEMA: Writes to quality_scores table.
#   CREATE TABLE quality_scores (
#     id INTEGER PRIMARY KEY,
#     run_id TEXT NOT NULL,
#     total INTEGER, hook INTEGER, narrative INTEGER,
#     specificity INTEGER, hinglish INTEGER,
#     verdict TEXT, flags TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP
#   );
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class QualityScore:
    """Result of quality assessment for a script.

    Attributes:
        total: Overall score 0-100.
        hook: Hook quality 0-25 (does first 8 sec stop scrolling).
        narrative: Narrative arc 0-25 (problem → mechanism → resolution).
        specificity: Concrete specificity 0-25 (numbers, names, dates).
        hinglish: Natural Hinglish quality 0-25 (not robotic).
        verdict: 'approve' | 'flag_for_review' | 'reject'.
        flags: List of specific issues found.
        rewrite_suggestions: List of suggestions for script_agent retry.
    """
    total: int = 0
    hook: int = 0
    narrative: int = 0
    specificity: int = 0
    hinglish: int = 0
    verdict: str = "reject"
    flags: list[str] = field(default_factory=list)
    rewrite_suggestions: list[str] = field(default_factory=list)


def score(script: dict, run_id: str = "") -> QualityScore:
    """Score a script using the LLM-as-judge rubric.

    Inputs:
        script: The script dict from script_agent (title, intro_hook, scenes, outro).
        run_id: Pipeline run identifier for DB tracking.

    Outputs:
        QualityScore with total (0-100), per-axis breakdown, verdict, and
        rewrite_suggestions if rejected.

    Implementation plan:
        1. Load rubric from config/quality_rubric.yaml
        2. Build LLM prompt with rubric + script JSON
        3. Call GPT-4o-mini with strict JSON response schema
        4. Parse response into QualityScore
        5. Write to quality_scores DB table
        6. Return QualityScore
    """
    # TODO: Load rubric from config/quality_rubric.yaml
    # TODO: GPT-4o-mini LLM-as-judge call
    # TODO: Write to quality_scores table
    # TODO: Wrap in @budget_guard("openai", 500)
    raise NotImplementedError("quality_agent.score() not yet implemented")


def _load_rubric() -> dict:
    """Load the quality rubric from config/quality_rubric.yaml.

    Outputs:
        dict with rubric axes and scoring criteria.
    """
    # TODO: Load and parse YAML rubric
    raise NotImplementedError


def _determine_verdict(total: int) -> str:
    """Map a total score to a verdict string.

    Inputs:
        total: Score 0-100.

    Outputs:
        'approve' (>=80), 'flag_for_review' (70-79), or 'reject' (<70).
    """
    if total >= 80:
        return "approve"
    elif total >= 70:
        return "flag_for_review"
    return "reject"
