ARABIC_DIGITS = str.maketrans({
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
    "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
    "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
    "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
})

def normalize_phone(value):
    """Return a stable phone representation for employee login matching."""
    value = str(value or "").strip().translate(ARABIC_DIGITS)
    for char in (" ", "-", "(", ")", "."):
        value = value.replace(char, "")
    if value.startswith("00") and len(value) > 2:
        value = "+" + value[2:]
    return value
