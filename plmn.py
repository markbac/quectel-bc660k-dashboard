"""Operator names for PLMN codes (MCC followed by a 2 or 3 digit MNC).

A BC660K reports the serving operator and the scan results as numeric PLMNs
(``23415``) and leaves the names empty. This small table covers the networks
the dashboard is most likely to meet. Unknown codes fall back to ``PLMN <code>``.
"""
import re
from typing import Optional

OPERATORS = {
    # United Kingdom
    "23402": "O2 UK", "23410": "O2 UK", "23411": "O2 UK",
    "23415": "Vodafone UK", "23420": "Three UK",
    "23430": "EE", "23431": "EE", "23432": "EE", "23433": "EE",
    # Ireland
    "27201": "Vodafone Ireland", "27202": "Three Ireland", "27203": "Eir", "27205": "Three Ireland",
    # Germany
    "26201": "Telekom Germany", "26202": "Vodafone Germany", "26203": "O2 Germany", "26207": "O2 Germany",
    # France
    "20801": "Orange France", "20810": "SFR", "20815": "Free Mobile", "20820": "Bouygues Telecom",
    # Netherlands
    "20404": "Vodafone Netherlands", "20408": "KPN", "20420": "Odido",
    # Finland
    "24403": "DNA", "24405": "Elisa", "24412": "DNA", "24491": "Telia Finland",
    # Sweden
    "24001": "Telia Sweden", "24002": "Tre Sweden",
}

_PLMN = re.compile(r"(?:PLMN )?(\d{5,6})")


def operator_name(plmn: str) -> Optional[str]:
    """The operator name for ``plmn`` (``"23415"``), or ``None`` if it is not known."""
    return OPERATORS.get(plmn)


def display_operator(value: Optional[str]) -> Optional[str]:
    """Turn a stored carrier such as ``23415`` or ``PLMN 23415`` into a name where known.

    Anything else, including names the network reported itself, is returned as it is.
    """
    if not value:
        return value
    match = _PLMN.fullmatch(value)
    if not match:
        return value
    return operator_name(match.group(1)) or f"PLMN {match.group(1)}"
