"""Stable language selection, independent of measurement identity."""
LANGUAGES = ("en-GB", "nb-NO", "nn-NO", "de-DE")
DEFAULT_LANGUAGE = "en-GB"
_ALIASES = {"en": "en-GB", "nb": "nb-NO", "no": "nb-NO", "nn": "nn-NO", "de": "de-DE"}

def resolve_language(configured="auto", accept_language=""):
    """Explicit selection wins; otherwise use browser language then English."""
    def match(value):
        tag = value.strip().replace("_", "-").lower()
        return next((lang for lang in LANGUAGES if lang.lower() == tag), None) or _ALIASES.get(tag.split("-")[0])
    if configured != "auto":
        return match(configured) or DEFAULT_LANGUAGE if isinstance(configured, str) else DEFAULT_LANGUAGE
    candidates = []
    for item in (accept_language or "").split(","):
        tag, *params = item.split(";")
        try:
            weight = next((float(p.strip()[2:]) for p in params if p.strip().startswith("q=")), 1.0)
        except ValueError:
            continue
        if 0 < weight <= 1:
            candidates.append((weight, tag))
    for _, tag in sorted(candidates, key=lambda item: -item[0]):
        language = match(tag)
        if language:
            return language
    return DEFAULT_LANGUAGE
