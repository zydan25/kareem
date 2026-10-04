import unicodedata

PASSWORD_FORMAT_CHARS = "\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\ufeff"

def strip_password_formatting(value):
    """Remove invisible bidi/formatting marks often copied with phone text."""
    return "".join(char for char in str(value or "") if char not in PASSWORD_FORMAT_CHARS)

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