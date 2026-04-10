"""
Retention Optimization Engine — provides structured script prompts
optimized for maximum YouTube viewer retention.
"""


def get_retention_structure_prompt(content_type: str, duration_seconds: int = 180) -> str:
    """Return a script structure prompt optimized for YouTube retention.

    Injects timing-based structure into GPT prompt for script generation.
    """
    if content_type == "shorts":
        return """
RETENTION OPTIMIZATION — YouTube Shorts structure (max 60 seconds):
Follow this EXACT timing structure for maximum viewer retention:

SCENE 1 (0-5 seconds) — THE HOOK:
  - Pattern interrupt: surprising visual + bold claim or question
  - Must grab attention in first 2 seconds
  - Example: "Did you know [SHOCKING FACT]?!" with dramatic visual

SCENE 2 (5-20 seconds) — CURIOSITY BUILD:
  - "But here's the crazy part..." or "Wait, it gets even better..."
  - Tease what's coming without revealing the answer
  - Build anticipation — make viewers NEED to keep watching

SCENE 3 (20-50 seconds) — CORE EXPLANATION:
  - Deliver the main content with 2 mini-hooks embedded
  - After every 10 seconds, add a micro-question: "And guess what happens next?"
  - Keep energy HIGH — use exclamations and rhetorical questions

SCENE 4 (50-60 seconds) — CLIFFHANGER + CTA:
  - "Next time we'll discover something even MORE amazing..."
  - End with a question that makes viewers want to watch the next video
  - "Follow for Part 2!" or "Which fact surprised you the most?"

IMPORTANT: Each scene narration MUST fit within its time window. Keep sentences short and punchy.
"""

    if content_type == "lullaby":
        return """
RETENTION OPTIMIZATION — Lullaby structure (gentle, calming flow):

SCENE 1 (0-15 seconds) — GENTLE OPENING:
  - Soft, warm greeting — like a parent saying goodnight
  - Set the calm, dreamy atmosphere

SCENE 2 (15-60 seconds) — STORY/IMAGERY:
  - Paint a peaceful scene: stars, moonlight, gentle animals
  - Use soothing repetition and rhythm

SCENE 3 (60-120 seconds) — DEEPENING CALM:
  - Slower pace, softer words
  - Gentle repetition of key phrases
  - Voice should feel like a warm blanket

SCENE 4 (120-180 seconds) — DRIFT TO SLEEP:
  - Whisper-quiet closing
  - "Goodnight... sweet dreams..."
  - Longest pauses between phrases

IMPORTANT: Lullabies should get progressively slower and softer. No sudden energy changes.
"""

    if content_type == "poem":
        return """
RETENTION OPTIMIZATION — Poem structure (rhythmic engagement):

SCENE 1 — CATCHY OPENING VERSE:
  - Start with the most memorable rhyme
  - Set the rhythm and energy level

SCENES 2-3 — BUILD THE THEME:
  - Each verse explores a new aspect of the topic
  - Maintain consistent rhyme scheme (AABB or ABAB)
  - Add a "chorus" verse that repeats for sing-along effect

SCENE 4 — CHORUS REPEAT:
  - Repeat the catchiest verse — kids love repetition
  - This is where they'll start singing along

SCENES 5-6 — FINALE:
  - Build to the most fun/exciting verse
  - End with the chorus one more time
  - Close with an inviting CTA rhyme

IMPORTANT: Poems must maintain rhythm. Every line should have a similar syllable count.
"""

    # Default: long-form video (2-3 minutes)
    return f"""
RETENTION OPTIMIZATION — Long-form video structure ({duration_seconds // 60} minutes):
Follow this EXACT timing structure for maximum viewer retention:

SCENE 1 (0-10 seconds) — PATTERN INTERRUPT HOOK:
  - Start with the MOST surprising fact or question
  - Bold visual + high energy narration
  - Promise what viewers will learn: "Today you'll discover..."

SCENE 2 (10-30 seconds) — TEASE & PREVIEW:
  - Preview 2-3 amazing things coming in the video
  - "We'll find out WHY... HOW... and the MOST incredible part..."
  - Build curiosity without giving away the answers

SCENE 3 (30-70 seconds) — FIRST CONTENT BLOCK:
  - Deliver the first big fact with enthusiasm
  - End with a mini-hook: "But that's not even the craziest part..."

SCENE 4 (70-110 seconds) — SECOND CONTENT BLOCK:
  - Another amazing fact, building on the first
  - Include a surprise twist: "And here's something nobody expected..."

SCENE 5 (110-150 seconds) — THIRD CONTENT BLOCK + CALLBACK:
  - Third fact + callback to the hook promise
  - "Remember when I said [hook reference]? Here's why..."

SCENE 6 (150-{duration_seconds} seconds) — PAYOFF + CTA:
  - Deliver the biggest revelation / most fun fact
  - Satisfying conclusion that delivers on the hook's promise
  - CTA: "Which fact amazed you the most? Like and subscribe for more!"

IMPORTANT: Each scene MUST end with a reason to keep watching. Never let energy drop.
The first 30 seconds determine if viewers stay — make them UNMISSABLE.
"""
