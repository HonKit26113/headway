"""One-line plain-language explanation of a score, via Gemini. Best-effort only."""
import logging

import requests

import config

logger = logging.getLogger(__name__)

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-3.8-flash:generateContent"
)
TIMEOUT_S = 20


def generate_summary(score: float, factors: list, campus: str) -> str | None:
    """A single plain-English sentence explaining the score, or None on any failure."""
    if not config.GEMINI_API_KEY:
        return None

    factor_lines = "\n".join(f"- {f.label}: {f.value}" for f in factors)
    prompt = (
        f"A transit score of {score}/10 (10 = best) for commuting to {campus.upper()} "
        f"was computed from these factors:\n{factor_lines}\n\n"
        "Write ONE short, plain-English sentence (under 20 words) explaining why it "
        "scored this way, in a natural conversational tone. No markdown, no quotes, "
        "just the sentence."
    )

    try:
        resp = requests.post(
            GEMINI_URL,
            params={"key": config.GEMINI_API_KEY},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "thinkingConfig": {"thinkingBudget": 0},
                    "maxOutputTokens": 100,
                },
            },
            timeout=TIMEOUT_S,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        return text.strip().strip('"')
    except Exception:
        logger.exception("Gemini summary generation failed")
        return None
