"""PII masking. Applied in the server, so raw values never leave it. Fails closed."""
import re

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def mask_email(value: str | None) -> str | None:
    if value is None:
        return None
    if not _EMAIL.match(value):
        return "***"
    local, domain = value.split("@", 1)
    return f"{local[0]}***@{domain}"


def mask_phone(value: str | None) -> str | None:
    if value is None:
        return None
    digits = [c for c in value if c.isdigit()]
    if len(digits) < 6:
        return "***"
    keep_from = len(digits) - 2  # keep only the last two digits
    out, seen = [], 0
    for c in value:
        if c.isdigit():
            out.append(c if seen >= keep_from else "*")
            seen += 1
        else:
            out.append(c)
    return "".join(out)
