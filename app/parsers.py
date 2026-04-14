import logging
import re

from .models import NIDData

logger = logging.getLogger(__name__)

_MONTHS = ("", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _yyyymmdd_to_readable(value: str) -> str:
    """Convert YYYYMMDD → 'DD Mon YYYY'. Returns original string on failure."""
    if len(value) == 8 and value.isdigit():
        year, month, day = value[:4], value[4:6], value[6:8]
        try:
            return f"{day} {_MONTHS[int(month)]} {year}"
        except (IndexError, ValueError):
            pass
    return value


def parse_machine_readable_zone(data: str) -> NIDData:
    """
    Parse MRZ-style barcode (ASCII GS/RS delimited format).

    Field codes:
    - NM: Name
    - NW: Smart Card Number (NID)
    - OL: Old NID Card Number
    - BR: Birth Date (YYYYMMDD)
    - DT: Date of Issue (YYYYMMDD)
    - BG: Blood Group
    - PE: Permanent Address Code
    - PR: Present Address Code
    - VA: Validity Period
    """
    nid = NIDData()
    for part in data.replace("\x1e", "\x1d").split("\x1d"):
        if len(part) < 2:
            continue
        code, value = part[:2].upper(), part[2:].strip()
        if code == "NM":
            nid.name = value
        elif code == "NW":
            nid.nid_number = value
        elif code == "OL":
            nid.old_nid = value
        elif code == "BR":
            nid.date_of_birth = _yyyymmdd_to_readable(value)
        elif code == "DT":
            nid.issue_date = _yyyymmdd_to_readable(value)
        elif code == "BG":
            nid.blood_group = value
    return nid


_DIGITAL_NID_PATTERNS: dict[str, re.Pattern[str]] = {
    tag: re.compile(rf"<{tag}>(.*?)</{tag}>", re.IGNORECASE)
    for tag in ("pin", "name", "DOB", "F", "FP", "TYPE", "V")
}


def parse_digital_nid(data: str) -> NIDData:
    """
    Parse XML-style digital NID barcode.

    Tags: pin=NID, name=Name, DOB=Birth Date, F/FP=Fingerprint,
          TYPE=Card type, V=Version
    """
    def _get(tag: str) -> str | None:
        m = _DIGITAL_NID_PATTERNS[tag].search(data)
        return m.group(1).strip() if m else None

    nid = NIDData()
    if pin := _get("pin"):
        nid.nid_number = pin
        nid.pin = pin
    nid.name = _get("name")
    nid.date_of_birth = _get("DOB")
    nid.fingerprint = _get("F") or _get("FP")
    nid.type = _get("TYPE")
    nid.version = _get("V")
    return nid


def parse_barcode_data(raw: str) -> tuple[NIDData, str]:
    """Auto-detect barcode format and dispatch to the correct parser."""
    if any(tag in raw for tag in ("<pin>", "<name>", "<DOB>")):
        return parse_digital_nid(raw), "digital_nid"
    if "\x1d" in raw or "\x1e" in raw:
        return parse_machine_readable_zone(raw), "machine_readable"
    logger.warning("Unknown barcode format. Preview: %.60s", raw)
    return NIDData(), "unknown"
