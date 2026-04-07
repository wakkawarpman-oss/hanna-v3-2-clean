"""
translit.py — Latin ↔ Cyrillic transliteration helpers.

Used by adapters that search Russian/Ukrainian leak databases where
names may appear in Cyrillic.
"""
from __future__ import annotations

_LATIN_TO_CYR = {
    "a": "а", "b": "б", "v": "в", "g": "г", "d": "д",
    "e": "е", "zh": "ж", "z": "з", "i": "і", "y": "й",
    "k": "к", "l": "л", "m": "м", "n": "н", "o": "о",
    "p": "п", "r": "р", "s": "с", "t": "т", "u": "у",
    "f": "ф", "kh": "х", "ts": "ц", "ch": "ч", "sh": "ш",
    "shch": "щ", "yu": "ю", "ya": "я", "h": "г",
    "nn": "нн",
}

_NAME_VARIANTS = {
    "hanna": ["ганна", "ханна", "анна"],
    "anna": ["анна", "ганна"],
    "dosenko": ["досенко", "дозенко"],
}


def transliterate_to_cyrillic(latin_name: str) -> list[str]:
    """Generate Cyrillic variants of a Latin name for leak searching."""
    results: list[str] = []
    parts = latin_name.lower().split()

    cyrillic_parts_options: list[list[str]] = []
    for part in parts:
        if part in _NAME_VARIANTS:
            cyrillic_parts_options.append(_NAME_VARIANTS[part])
        else:
            cyr = _simple_transliterate(part)
            cyrillic_parts_options.append([cyr] if cyr else [part])

    if len(cyrillic_parts_options) == 2:
        for first in cyrillic_parts_options[0]:
            for last in cyrillic_parts_options[1]:
                results.append(f"{first.capitalize()} {last.capitalize()}")
                if len(results) >= 6:
                    return results
    elif len(cyrillic_parts_options) == 1:
        results = [v.capitalize() for v in cyrillic_parts_options[0]]
    else:
        cyr = _simple_transliterate(latin_name)
        if cyr:
            results.append(cyr)

    return results[:6]


def _simple_transliterate(text: str) -> str:
    """Simple Latin → Cyrillic transliteration."""
    result: list[str] = []
    i = 0
    text_lower = text.lower()
    while i < len(text_lower):
        matched = False
        for length in (4, 3, 2):
            chunk = text_lower[i : i + length]
            if chunk in _LATIN_TO_CYR:
                result.append(_LATIN_TO_CYR[chunk])
                i += length
                matched = True
                break
        if not matched:
            ch = text_lower[i]
            if ch in _LATIN_TO_CYR:
                result.append(_LATIN_TO_CYR[ch])
            else:
                result.append(ch)
            i += 1
    return "".join(result)


# Backward-compatible alias used by deep_recon.py internal references
_transliterate_to_cyrillic = transliterate_to_cyrillic
