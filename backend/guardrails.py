"""Cheap guardrails that run before and after the LLM call.

Layer 1 (input): block prompt-injection attempts and clearly dangerous requests
without spending tokens. Layer 2 lives in the system prompt (context.py).
Layer 3 (output): stop the model from echoing its own instructions.

This is a defence-in-depth filter, not a guarantee: it catches the common attacks,
and the system prompt covers what the patterns miss.
"""

import re
import unicodedata
from typing import Optional

REFUSAL = (
    "I can't help with that. I'm happy to talk about my background, skills "
    "and projects, so ask me about those instead."
)

SELF_HARM_REPLY = (
    "I'm really sorry you're feeling this way, but I'm not the right one to help with this. "
    "Please reach out to someone you trust or a local crisis line "
    "(in the EU you can call 112, in the US call or text 988)."
)

# Attempts to override or extract the instructions
_INJECTION = [
    r"\b(ignore|disregard|forget|override|bypass|skip|drop)\b.{0,50}\b(instruction|prompt|rule|guideline|direction|restriction|programming|training)s?\b",
    r"\b(reveal|show|print|repeat|output|display|leak|dump|recite|tell me)\b.{0,40}\b(system prompt|initial prompt|hidden (prompt|instruction)s?|your (system|initial|original|hidden) (prompt|instruction)s?|your (instruction|rule)s)\b",
    r"\bwhat (are|were|is) your (instruction|rule|system prompt|initial prompt)s?\b",
    r"\b(jailbreak|jailbroken|dan mode|developer mode|do anything now|prompt injection)\b",
    r"\b(pretend|act|behave|roleplay|role-play)\b.{0,30}\b(unrestricted|unfiltered|uncensored|jailbroken|no (rules|restrictions|limits)|without (rules|restrictions|limits))\b",
    r"\byou are (no longer|not) (bound|restricted|limited)\b",
    r"\b(new|updated|real) (instruction|rule|system prompt)s?\s*:",
    r"\bfrom now on,? you (are|will|must|can)\b",
    r"\b(system|developer|admin) (override|mode|message|command)\b",
]

# Clearly dangerous or illegal requests
_DANGEROUS = [
    r"\b(how to|how do i|how can i|ways to|steps to|instructions? (for|to)|teach me|show me how)\b.{0,40}\b(make|build|create|synthesi[sz]e|cook|assemble)\b.{0,40}\b(bomb|explosive|molotov|napalm|thermite|nerve agent|bioweapon|chemical weapon|meth|methamphetamine|fentanyl|cocaine|heroin|ghost gun)\b",
    r"\b(write|create|build|make|generate|code|give me)\b.{0,40}\b(malware|ransomware|keylogger|trojan|computer virus|botnet|ddos|reverse shell|exploit code|phishing (page|email|kit))\b",
    r"\b(hack|break into|crack|steal|phish)\b.{0,40}\b(account|password|wifi|wi-fi|bank|database|someone|credentials|credit card)s?\b",
    r"\b(child|minor|underage|kid)s?\b.{0,40}\b(sexual|porn|nude|naked|erotic)\b",
    r"\b(how to|ways to|best way to)\b.{0,30}\b(kill|poison|stalk|harass|doxx?)\b.{0,20}\b(someone|a person|him|her|them|my (neighbou?r|boss|ex|wife|husband))\b",
]

_SELF_HARM = [
    r"\b(how to|ways to|best way to|help me)\b.{0,30}\b(kill myself|commit suicide|end my life|hurt myself|self[- ]harm)\b",
    r"\bi want to (die|kill myself|end it all)\b",
]

# Fragments that only appear in our own system prompt
_LEAK_MARKERS = [
    "# your role",
    "## important context",
    "critical rules that you must follow",
    "## your task",
    "for reference, here is the current date",
]

_INJECTION_RE = [re.compile(p, re.IGNORECASE | re.DOTALL) for p in _INJECTION]
_DANGEROUS_RE = [re.compile(p, re.IGNORECASE | re.DOTALL) for p in _DANGEROUS]
_SELF_HARM_RE = [re.compile(p, re.IGNORECASE | re.DOTALL) for p in _SELF_HARM]


def _normalise(text: str) -> str:
    """Fold unicode tricks (full-width letters, zero-width chars) and whitespace."""
    text = unicodedata.normalize("NFKC", text)
    text = "".join(c for c in text if unicodedata.category(c) not in ("Cf", "Cc") or c in "\n\t ")
    return re.sub(r"\s+", " ", text).strip()


def check_input(message: str) -> Optional[str]:
    """Return a canned reply if the message should be blocked, else None."""
    text = _normalise(message)
    if any(r.search(text) for r in _SELF_HARM_RE):
        return SELF_HARM_REPLY
    if any(r.search(text) for r in _INJECTION_RE):
        return REFUSAL
    if any(r.search(text) for r in _DANGEROUS_RE):
        return REFUSAL
    return None


def check_output(response: str) -> str:
    """Replace the reply if it leaks the system prompt."""
    lowered = response.lower()
    if any(marker in lowered for marker in _LEAK_MARKERS):
        return REFUSAL
    return response
