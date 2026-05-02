"""
Smoke tests for quality_agent.

Tests the scoring logic, verdict thresholds, and rubric loading without
making actual API calls (mocks the OpenAI client).
"""

import json
import pytest
from unittest.mock import patch, MagicMock

from agents.quality_agent import score, QualityScore, _determine_verdict, _load_rubric


# --- Test data ---

GOOD_SCRIPT = {
    "title": "UPI kaise kaam karta hai? Pure backend ki kahani",
    "intro_hook": "Kya aapko pata hai ki har second 3,000+ UPI transactions hote hain India mein? Lekin ye actually kaise kaam karta hai?",
    "scenes": [
        {
            "scene_number": 1,
            "narration": "2016 mein jab UPI launch hua, tab India ke sirf 2% log digital payments use karte the. Aaj 2026 mein, 350 million se zyada log har mahine UPI use karte hain. Ye change kaise hua? Iska jawab hai ek simple idea — Virtual Payment Address ya VPA.",
            "visual_description": "Infographic showing India's digital payment growth from 2016 to 2026, with a VPA address highlighted"
        },
        {
            "scene_number": 2,
            "narration": "Jab aap Google Pay ya PhonePe se paise bhejte ho, toh pehle aapka phone ek encrypted request NPCI ke server ko bhejta hai. NPCI matlab National Payments Corporation of India — ye RBI ka payment backbone hai jo 2008 mein bana tha.",
            "visual_description": "Animated diagram showing phone → NPCI server → bank, with encryption symbols"
        },
        {
            "scene_number": 3,
            "narration": "NPCI ka system har second 10,000 transactions handle kar sakta hai. December 2025 mein ek din mein 500 million transactions process hue — matlab har second 5,787 transactions. Ye sab real-time settlement hota hai, T+0.",
            "visual_description": "Dashboard showing live transaction counter with real-time numbers ticking up"
        },
    ],
    "outro": "Toh next time jab aap UPI se chai ke paise bhejo, yaad rakhna — peechhe NPCI ka 10,000 TPS system kaam kar raha hai!"
}

BAD_SCRIPT = {
    "title": "UPI ke baare mein jaaniye",
    "intro_hook": "Aaj hum baat karenge UPI ke baare mein.",
    "scenes": [
        {
            "scene_number": 1,
            "narration": "UPI bahut important hai. India mein bahut log UPI use karte hain. Ye kaafi useful technology hai.",
            "visual_description": "A phone showing UPI app"
        },
        {
            "scene_number": 2,
            "narration": "UPI se aap paise bhej sakte ho. Ye bahut fast hai. Aur free bhi hai.",
            "visual_description": "Two phones exchanging money"
        },
    ],
    "outro": "Toh UPI bahut acchi technology hai. Thank you for watching."
}


# --- Mock config ---

MOCK_CONFIG = {
    "openai": {"api_key": "sk-test-key", "model": "gpt-4o-mini"},
}


# --- Tests ---

class TestDetermineVerdict:
    def test_approve(self):
        rubric = _load_rubric()
        assert _determine_verdict(85, rubric) == "approve"
        assert _determine_verdict(80, rubric) == "approve"
        assert _determine_verdict(100, rubric) == "approve"

    def test_flag_for_review(self):
        rubric = _load_rubric()
        assert _determine_verdict(75, rubric) == "flag_for_review"
        assert _determine_verdict(70, rubric) == "flag_for_review"
        assert _determine_verdict(79, rubric) == "flag_for_review"

    def test_reject(self):
        rubric = _load_rubric()
        assert _determine_verdict(69, rubric) == "reject"
        assert _determine_verdict(50, rubric) == "reject"
        assert _determine_verdict(0, rubric) == "reject"


class TestLoadRubric:
    def test_rubric_loads(self):
        rubric = _load_rubric()
        assert "thresholds" in rubric
        assert "axes" in rubric
        assert len(rubric["axes"]) == 4
        assert "hook" in rubric["axes"]
        assert "narrative" in rubric["axes"]
        assert "specificity" in rubric["axes"]
        assert "hinglish" in rubric["axes"]

    def test_rubric_thresholds(self):
        rubric = _load_rubric()
        assert rubric["thresholds"]["approve"] == 80
        assert rubric["thresholds"]["flag_for_review"] == 70
        assert rubric["thresholds"]["max_retries"] == 3


class TestScoreWithMock:
    """Tests that use a mocked OpenAI client."""

    def _mock_judge_response(self, hook, narrative, specificity, hinglish,
                              flags=None, suggestions=None):
        """Create a mock OpenAI response with given scores."""
        result = {
            "hook": hook,
            "narrative": narrative,
            "specificity": specificity,
            "hinglish": hinglish,
            "total": hook + narrative + specificity + hinglish,
            "flags": flags or [],
            "rewrite_suggestions": suggestions or [],
        }
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(result)
        return mock_response

    @patch("agents.quality_agent.OpenAI")
    @patch("agents.quality_agent.log_cost")
    def test_good_script_approved(self, mock_log, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = self._mock_judge_response(
            hook=22, narrative=21, specificity=20, hinglish=21
        )

        result = score(GOOD_SCRIPT, MOCK_CONFIG)

        assert isinstance(result, QualityScore)
        assert result.total == 84
        assert result.verdict == "approve"
        assert result.hook == 22

    @patch("agents.quality_agent.OpenAI")
    @patch("agents.quality_agent.log_cost")
    def test_bad_script_rejected(self, mock_log, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = self._mock_judge_response(
            hook=8, narrative=10, specificity=5, hinglish=12,
            flags=["Generic hook", "No specific facts"],
            suggestions=["Add concrete numbers", "Create an information gap in the hook"],
        )

        result = score(BAD_SCRIPT, MOCK_CONFIG)

        assert isinstance(result, QualityScore)
        assert result.total == 35
        assert result.verdict == "reject"
        assert len(result.flags) == 2
        assert len(result.rewrite_suggestions) == 2

    @patch("agents.quality_agent.OpenAI")
    @patch("agents.quality_agent.log_cost")
    def test_borderline_script_flagged(self, mock_log, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = self._mock_judge_response(
            hook=18, narrative=19, specificity=17, hinglish=19,
            flags=["Hook could be stronger"],
        )

        result = score(GOOD_SCRIPT, MOCK_CONFIG)

        assert result.total == 73
        assert result.verdict == "flag_for_review"

    @patch("agents.quality_agent.OpenAI")
    @patch("agents.quality_agent.log_cost")
    def test_scores_clamped_to_range(self, mock_log, mock_openai_cls):
        """Ensure scores are clamped to 0-25 even if LLM returns out of range."""
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = self._mock_judge_response(
            hook=30, narrative=-5, specificity=25, hinglish=25
        )

        result = score(GOOD_SCRIPT, MOCK_CONFIG)

        assert result.hook == 25  # clamped from 30
        assert result.narrative == 0  # clamped from -5
        assert result.total == 75  # 25 + 0 + 25 + 25


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
