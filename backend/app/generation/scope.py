"""Out-of-scope and greeting handling, deterministic and free.

Two things live here and neither touches grounding or refusal:

  SCOPE_MESSAGE      the copy shown when the copilot has nothing to answer:
                     what it is for, what it is not, examples, the route to an
                     assessment. The retrieval refusal (ABSTENTION_TEXT) stays
                     exactly what it was; the frontend renders this copy for it.
  is_trivial_input   a cheap check for empty, greeting-only or letterless
                     input. /ask answers those with SCOPE_MESSAGE before any
                     embedding or model call, creating no session and no trace.
                     Everything else goes through the unchanged pipeline.
"""

import re

SCOPE_TITLE = "Ask me about the EU AI Act"

SCOPE_MESSAGE = (
    "I answer questions about the EU AI Act: obligations, prohibited practices, "
    "and whether a system is high-risk, with every answer cited to the "
    "consolidated text. I am not a general chatbot, so questions you would put "
    "to a search engine or a general assistant will get this note rather than "
    "a guess."
)

SCOPE_EXAMPLES = (
    "What obligations apply to providers of high-risk AI systems?",
    "Is an AI system used for credit scoring high-risk?",
    "Which AI practices are prohibited outright?",
)

SCOPE_ASSESS_HINT = (
    "For your own system, run the assessment: it quotes the provisions that "
    "appear to apply and computes the fine ceilings. Informational, not legal advice."
)

_GREETINGS = {
    "hi",
    "hey",
    "hello",
    "hiya",
    "yo",
    "sup",
    "hola",
    "heya",
    "howdy",
    "good morning",
    "good afternoon",
    "good evening",
    "good day",
    "thanks",
    "thank you",
    "thx",
    "ty",
    "cheers",
    "ok",
    "okay",
    "k",
    "test",
    "testing",
    "ping",
    "help",
    "start",
    "hi there",
    "hello there",
    "hey there",
    "how are you",
    "how are you doing",
    "whats up",
    "what's up",
    "who are you",
    "what are you",
    "what can you do",
    "what do you do",
}

_LETTERS = re.compile(r"[a-zA-Z\u00C0-\u024F]")


def is_trivial_input(text: str) -> bool:
    """True for input no retrieval could ground: empty or punctuation-only,
    letterless, or a bare greeting / pleasantry (with optional trailing
    punctuation and a short tail such as a name). Deliberately narrow: a real
    question that happens to open with "hi" still goes to retrieval."""
    t = " ".join(text.strip().lower().split())
    t = re.sub(r"[\s!.,?;:]+$", "", t)
    if not t or not _LETTERS.search(t):
        return True
    if t in _GREETINGS:
        return True
    words = t.split()
    if (
        "?" not in text
        and 1 < len(words) <= 4
        and words[0] in {"hi", "hey", "hello", "hiya", "thanks"}
    ):
        return all(len(w) <= 12 for w in words)
    return False
