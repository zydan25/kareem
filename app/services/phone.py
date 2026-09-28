import unicodedata

def normalize_phone(value):
    """Return a stable phone representation for employee login matching."""
    value = str(value or "").strip()
    out = []
    for char in value:
        digit = unicodedata.digit(char, None)
        if digit is not None:
            out.append(str(digit))
            continue
        if char == "+" and not out:
            out.append(char)
            continue
    normalized = "".join(out)
    if normalized.startswith("00") and len(normalized) > 2:
        normalized = "+" + normalized[2:]
    return normalized