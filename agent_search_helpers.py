"""
Agent-facing search helper functions for Bedesten tools.

This module intentionally has no third-party dependencies so its routing decisions
can be tested without starting FastMCP or making network calls.
"""
import re
from typing import Optional


BED_REGULATION_TYPE_ORDER = ["KKY", "CB_YONETMELIK", "YONETMELIK", "UY"]
BED_REGULATION_TYPES = set(BED_REGULATION_TYPE_ORDER)

REGULATION_QUERY_STOP_WORDS = {
    "yonetmelik", "yonetmeligi", "yönetmelik", "yönetmeliği",
    "hakkinda", "hakkında", "iliskin", "ilişkin", "dair",
    "usul", "esas", "esaslar", "esaslari", "esasları",
    "ve", "ile",
}


def looks_like_full_text_query(value: str) -> bool:
    """Return True when a query uses syntax that belongs in Bedesten phrase search."""
    query = (value or "").strip()
    if not query:
        return False
    return bool(
        re.search(r"\b(?:AND|OR|NOT)\b", query)
        or re.search(r'["()~^]', query)
        or re.search(r"(^|\s)[+-]\S+", query)
    )


def looks_like_short_code_query(value: str) -> bool:
    """Detect short/code-like Turkish regulation names without expanding them."""
    query = (value or "").strip()
    if not query:
        return False
    tokens = [t for t in re.split(r"\s+", query) if t]
    if len(tokens) > 3:
        return False
    code_tokens = 0
    for token in tokens:
        cleaned = re.sub(r"[^0-9A-Za-zÇĞİÖŞÜçğıöşü-]", "", token)
        letters = re.sub(r"[^A-Za-zÇĞİÖŞÜçğıöşü]", "", cleaned)
        if not cleaned or len(cleaned) > 16:
            continue
        if "-" in cleaned and letters and letters.upper() == letters:
            code_tokens += 1
        elif len(letters) >= 2 and letters.upper() == letters:
            code_tokens += 1
    return code_tokens > 0


def simplify_regulation_query(value: str) -> str:
    """Remove generic regulation filler words while preserving domain terms."""
    query = (value or "").strip()
    if not query:
        return ""
    normalized = re.sub(r"[\"'()]", " ", query)
    words = [w for w in re.split(r"\s+", normalized) if w]
    kept = [
        word for word in words
        if word.casefold().strip(".,;:/") not in REGULATION_QUERY_STOP_WORDS
    ]
    simplified = " ".join(kept).strip()
    return simplified if simplified and simplified != query else ""


def resolve_bedesten_query_fields(
    *,
    phrase: str = "",
    mevzuat_adi: str = "",
    mevzuat_no: Optional[str] = None,
    aranacak_ifade: Optional[str] = None,
) -> tuple[str, str, list[str]]:
    """Normalize agent-friendly search input into Bedesten title/full-text fields."""
    phrase = (phrase or "").strip()
    mevzuat_adi = (mevzuat_adi or "").strip()
    notes: list[str] = []
    fallback = (aranacak_ifade or "").strip()

    if mevzuat_adi and looks_like_full_text_query(mevzuat_adi):
        if phrase:
            phrase = f"{phrase} {mevzuat_adi}".strip()
        else:
            phrase = mevzuat_adi
        mevzuat_adi = ""
        notes.append("Moved full-text style title query to phrase.")

    if fallback and not phrase and not mevzuat_adi and not mevzuat_no:
        if looks_like_full_text_query(fallback):
            phrase = fallback
            notes.append("Interpreted aranacak_ifade as phrase.")
        else:
            mevzuat_adi = fallback
            notes.append("Interpreted aranacak_ifade as mevzuat_adi.")
    elif fallback:
        notes.append("Ignored aranacak_ifade because phrase, mevzuat_adi, or mevzuat_no was provided.")

    return phrase, mevzuat_adi, notes


def build_bedesten_search_desc(phrase: str = "", mevzuat_adi: str = "") -> str:
    """Build a compact human/agent-readable label for Bedesten search inputs."""
    parts = []
    if phrase:
        parts.append(f"phrase='{phrase}'")
    if mevzuat_adi:
        parts.append(f"title='{mevzuat_adi}'")
    return " + ".join(parts)


def validate_regulation_types(mevzuat_tur: Optional[str]) -> tuple[Optional[list[str]], Optional[str]]:
    if not mevzuat_tur:
        return list(BED_REGULATION_TYPE_ORDER), None

    tur_list = [t.strip().upper() for t in mevzuat_tur.split(",") if t.strip()]
    invalid = [t for t in tur_list if t not in BED_REGULATION_TYPES]
    if invalid or not tur_list:
        return None, (
            f"Invalid mevzuat_tur for search_yonetmelik: '{mevzuat_tur}'. "
            f"Allowed regulation types: {', '.join(BED_REGULATION_TYPE_ORDER)}"
        )
    return tur_list, None


def format_bedesten_search_result(
    result,
    *,
    search_desc: str,
    mevzuat_tur: Optional[str],
    page: int,
    notes: Optional[list[str]] = None,
    tried: Optional[list[str]] = None,
    no_results_guidance: Optional[str] = None,
) -> str:
    notes = notes or []
    tried = tried or []

    if result.error_message:
        return f"Search error: {result.error_message}"

    type_suffix = f" (type: {mevzuat_tur})" if mevzuat_tur else ""
    if not result.documents:
        output = [f"No results found for {search_desc or 'browse'}{type_suffix}"]
        if notes:
            output.extend(notes)
        if tried:
            output.append("Tried strategies:")
            output.extend(f"- {item}" for item in tried)
        if no_results_guidance:
            output.append(no_results_guidance)
        return "\n".join(output)

    output = []
    if search_desc:
        output.append(f"Search: {search_desc}" + (f" | Type: {mevzuat_tur}" if mevzuat_tur else ""))
    else:
        output.append(f"Browse" + (f" | Type: {mevzuat_tur}" if mevzuat_tur else " | All types"))
    output.append(f"Results: {result.total_results} total (page {page})")
    if notes:
        output.extend(notes)
    if tried:
        output.append("Tried strategies:")
        output.extend(f"- {item}" for item in tried)
    output.append("Use mevzuatId with search_within_mevzuat, get_mevzuat_madde_tree, or get_mevzuat_content.")
    output.append("")

    for doc in result.documents:
        tur_name = ""
        if isinstance(doc.mevzuat_tur, dict):
            tur_name = doc.mevzuat_tur.get("description", doc.mevzuat_tur.get("name", ""))
        elif isinstance(doc.mevzuat_tur, str):
            tur_name = doc.mevzuat_tur

        line = f"- [{doc.mevzuat_no}] {doc.mevzuat_adi}"
        if tur_name:
            line += f" ({tur_name})"
        line += f" | mevzuatId: {doc.mevzuat_id}"
        if doc.resmi_gazete_tarihi:
            rg = doc.resmi_gazete_tarihi
            if "T" in rg:
                rg = rg.split("T")[0]
            line += f" | RG: {rg}"
        if doc.gerekce_id:
            line += f" | gerekceId: {doc.gerekce_id}"
        output.append(line)

    return "\n".join(output)
