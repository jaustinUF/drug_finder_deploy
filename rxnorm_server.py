# FastMCP-based MCP server for RxNorm API
# Tools:
#   1) search_drugs(query, limit=5)
#   2) get_drug_properties(rxcui)

import json
from typing import List, Dict, Any, Optional
import requests
from mcp.server.fastmcp import FastMCP
import logging
logging.disable(logging.CRITICAL)

mcp = FastMCP("rxnorm")

def _clip_limit(n: Optional[int], lo: int = 1, hi: int = 50, default: int = 5) -> int:
    try:
        n = int(n) if n is not None else default
        return max(lo, min(n, hi))
    except Exception:
        return default

# original two tools
@mcp.tool()
def search_drugs(query: str, limit: int = 5) -> str:
    """
    Search RxNorm for drug concepts by brand or generic name.
    Args:
      query: e.g., "Tylenol" or "acetaminophen"
      limit: max number of results to return (1–50, default 5)
    Returns:
      Pretty-printed JSON string: {"query": "...", "results": [ {...}, ... ]}
    """
    q = (query or "").strip()
    if not q:
        return json.dumps({"error": "query is required"}, indent=2)

    lim = _clip_limit(limit)

    # RxNorm "drugs" endpoint groups results in conceptGroup[].conceptProperties[]
    url = "https://rxnav.nlm.nih.gov/REST/drugs.json"
    try:
        r = requests.get(url, params={"name": q}, timeout=20)
        r.raise_for_status()
        data = r.json() or {}
    except requests.RequestException as e:
        return json.dumps({"error": f"HTTP error contacting RxNorm: {e}"}, indent=2)

    results: List[Dict[str, Any]] = []
    drug_group = (data.get("drugGroup") or {})
    for grp in (drug_group.get("conceptGroup") or []):
        for c in (grp.get("conceptProperties") or []):
            results.append({
                "rxcui": c.get("rxcui"),
                "name": c.get("name"),
                "synonym": c.get("synonym"),
                "tty": c.get("tty"),
            })

    return json.dumps({"query": q, "results": results[:lim]}, indent=2)

@mcp.tool()
def get_drug_properties(rxcui: str) -> str:
    """
    Fetch RxNorm properties for a given RXCUI.
    Args:
      rxcui: RxNorm Concept Unique Identifier (string or int)
    Returns:
      Pretty-printed JSON string with RxNorm properties, or an error message.
    """
    rx = str(rxcui or "").strip()
    if not rx:
        return json.dumps({"error": "rxcui is required"}, indent=2)

    url = f"https://rxnav.nlm.nih.gov/REST/rxcui/{rx}/properties.json"
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        data = r.json() or {}
    except requests.RequestException as e:
        return json.dumps({"error": f"HTTP error contacting RxNorm: {e}"}, indent=2)

    props = (data.get("properties") or {})
    return json.dumps({"rxcui": rx, "properties": props}, indent=2)

# additional six tools
# Upgrade_2 MCP tool additions: consumer-friendly RxNorm tools
@mcp.tool()
def get_spelling_suggestions(name: str) -> str:
    """
    Purpose: Suggest corrected drug names for a possibly misspelled input.
    When to use: User typed a name that may be misspelled or incomplete.
    Inputs:
      name: str – free-text drug/brand/ingredient name (may include typos).
    Returns:
      JSON string: {"query": str, "suggestions": [str, ...]}
    Notes:
      - This does not resolve to RxCUI. Use `find_rxcui` after getting suggestions.
      - Keep output consumer-friendly (surface only the suggestion strings).
    Example:
      input: "ibuprfen" → {"query":"ibuprfen","suggestions":["ibuprofen", ...]}
    """
    if not name or not name.strip():
        return json.dumps({"error": "name is required"}, indent=2)
    url = "https://rxnav.nlm.nih.gov/REST/spellingsuggestions.json"
    try:
        r = requests.get(url, params={"name": name}, timeout=20)
        r.raise_for_status()
        data = r.json() or {}
    except requests.RequestException as e:
        return json.dumps({"query": name, "error": f"HTTP error contacting RxNorm: {e}"}, indent=2)

    suggestions = (
        (data.get("suggestionGroup") or {})
        .get("suggestionList") or {}
    ).get("suggestion") or []
    return json.dumps({"query": name, "suggestions": suggestions}, indent=2)


@mcp.tool()
def find_rxcui(name: str, do_approximate_if_none: bool = True, max_entries: int = 10) -> str:
    """
    Purpose: Resolve a drug/brand/ingredient name to one or more RxCUIs, with optional approximate fallback.
    When to use: You have only a text name and need canonical RxCUI(s).
    Inputs:
      name: str – free-text name (ingredient, brand, etc.).
      do_approximate_if_none: bool – if True, use approximateTerm when exact lookup returns none.
      max_entries: int – cap on approximate candidates (default 10).
    Returns:
      JSON string:
        {
          "query": str,
          "exact": [{"rxcui": str}],
          "approximate": [{"rxcui": str, "score": int, "rank": int, "name": str}]  # present only if used
        }
    Notes:
      - Prefer `exact` hits; use `approximate` to suggest likely matches to the user.
      - Follow-up calls: `get_rxterms_info` for display fields; `get_all_related_info` for brand/generic/forms.
    Example:
      input: "benadryl" → exact=[{"rxcui":"..."}]  (approximate omitted)
    """
    if not name or not name.strip():
        return json.dumps({"error": "name is required"}, indent=2)

    # Exact
    url_exact = "https://rxnav.nlm.nih.gov/REST/rxcui.json"
    try:
        r = requests.get(url_exact, params={"name": name}, timeout=20)
        r.raise_for_status()
        data = r.json() or {}
    except requests.RequestException as e:
        return json.dumps({"query": name, "error": f"HTTP error contacting RxNorm: {e}"}, indent=2)

    ids = ((data.get("idGroup") or {}).get("rxnormId") or [])
    exact = [{"rxcui": rid} for rid in ids] if ids else []

    response: Dict[str, Any] = {"query": name, "exact": exact}

    # Approximate fallback
    if not exact and do_approximate_if_none:
        url_apx = "https://rxnav.nlm.nih.gov/REST/approximateTerm.json"
        try:
            r2 = requests.get(
                url_apx,
                params={"term": name, "maxEntries": int(max_entries or 10), "option": 1},
                timeout=20,
            )
            r2.raise_for_status()
            apx = r2.json() or {}
        except requests.RequestException as e:
            response["approximate_error"] = f"HTTP error contacting RxNorm: {e}"
            return json.dumps(response, indent=2)

        candidates = ((apx.get("approximateGroup") or {}).get("candidate") or [])
        approx_list: List[Dict[str, Any]] = []
        for c in candidates:
            approx_list.append({
                "rxcui": c.get("rxcui"),
                "score": c.get("score"),
                "rank": c.get("rank"),
                "name": c.get("name")
            })
        response["approximate"] = approx_list

    return json.dumps(response, indent=2)


@mcp.tool()
def get_all_related_info(rxcui: str, filter_tty: Optional[str] = None) -> str:
    """
    Purpose: Fetch related RxNorm concepts for an RxCUI (brand/generic, forms, strengths), grouped by TTY.
    When to use: You have an RxCUI and want the ecosystem around it for display/navigation.
    Inputs:
      rxcui: str – RxNorm Concept Unique Identifier.
      filter_tty: Optional[str] – space-separated TTYs to include (e.g., "SCD SBD IN BN DF").
    Returns:
      JSON string: {"rxcui": str, "related": { "<TTY>": [{"rxcui": str, "name": str, "tty": str, "synonym": str?}], ... }}
    Notes:
      - Common consumer TTYs: IN (ingredient), BN (brand name), SCD/SBD (clinical/branded drugs), DF (dose form).
      - Pair with `get_rxterms_info` to render friendly names/strength/route; pair with history for obsolete checks.
    Example:
      input: rxcui="..." → related = { "IN": [...], "SCD": [...], "SBD": [...] }
    """
    if not rxcui or not rxcui.strip():
        return json.dumps({"error": "rxcui is required"}, indent=2)

    url = f"https://rxnav.nlm.nih.gov/REST/rxcui/{rxcui}/allrelated.json"
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        data = r.json() or {}
    except requests.RequestException as e:
        return json.dumps({"rxcui": rxcui, "error": f"HTTP error contacting RxNorm: {e}"}, indent=2)

    groups = ((data.get("allRelatedGroup") or {}).get("conceptGroup") or [])
    allowed = set((filter_tty or "").split()) if filter_tty else None

    out: Dict[str, List[Dict[str, Any]]] = {}
    for g in groups:
        tty = g.get("tty")
        if allowed and tty not in allowed:
            continue
        concepts = g.get("conceptProperties") or []
        compacts = []
        for c in concepts:
            compacts.append({
                "rxcui": c.get("rxcui"),
                "name": c.get("name"),
                "tty": c.get("tty"),
                "synonym": c.get("synonym"),
            })
        if compacts:
            out[tty] = compacts

    return json.dumps({"rxcui": rxcui, "related": out}, indent=2)


@mcp.tool()
def get_ndc_properties(ndc: str) -> str:
    """
    Purpose: Given a package NDC (10/11-digit, hyphens allowed), return human-readable product/package properties.
    When to use: The user provides an NDC from a bottle/box; use before name-based search.
    Inputs:
      ndc: str – NDC with or without hyphens (e.g., "12345-6789-01" or "12345678901").
    Returns:
      JSON string: {"ndc": str, "data": { ...RxNav ndcproperties... }}
    Notes:
      - Surfaces active/obsolete status when available.
      - If you need the current concept, follow with `get_rxcui_history_status` using a returned RxCUI (if present).
    Example:
      input: "0054-0450-25" → {"ndc":"0054-0450-25","data":{...}}
    """
    if not ndc or not ndc.strip():
        return json.dumps({"error": "ndc is required"}, indent=2)

    url = "https://rxnav.nlm.nih.gov/REST/ndcproperties.json"
    try:
        r = requests.get(url, params={"ndc": ndc}, timeout=20)
        r.raise_for_status()
        data = r.json() or {}
    except requests.RequestException as e:
        return json.dumps({"ndc": ndc, "error": f"HTTP error contacting RxNorm: {e}"}, indent=2)

    return json.dumps({"ndc": ndc, "data": data}, indent=2)


@mcp.tool()
def get_rxcui_history_status(rxcui: str) -> str:
    """
    Purpose: Check whether an RxCUI is Active/Obsolete/Remapped and provide the remap target if present.
    When to use: Before presenting details, or when an ID looks outdated.
    Inputs:
      rxcui: str – RxNorm CUI to evaluate.
    Returns:
      JSON string: {"rxcui": str, "data": { ...RxNav historystatus... }}
    Notes:
      - If status is REMAPPED, prefer the replacement RxCUI in follow-up lookups.
      - Use alongside `get_rxterms_info` to display the current, consumer-friendly name.
    Example:
      input: "12345" → {"rxcui":"12345","data":{"historystatus":"REMAPPED","remappedTo":"..."}}
    """
    if not rxcui or not rxcui.strip():
        return json.dumps({"error": "rxcui is required"}, indent=2)

    url = f"https://rxnav.nlm.nih.gov/REST/rxcui/{rxcui}/historystatus.json"
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        data = r.json() or {}
    except requests.RequestException as e:
        return json.dumps({"rxcui": rxcui, "error": f"HTTP error contacting RxNorm: {e}"}, indent=2)

    return json.dumps({"rxcui": rxcui, "data": data}, indent=2)


@mcp.tool()
def get_rxterms_info(rxcui: str) -> str:
    """
    Purpose: Retrieve consumer-friendly display fields (name, strength, route, dose form) from RxTerms.
    When to use: Build the UI card for a known RxCUI or one chosen from related concepts.
    Inputs:
      rxcui: str – RxNorm CUI.
    Returns:
      JSON string: {"rxcui": str, "rxtermsInfo": { "displayName": str, "strength": str?, "route": str?, "doseForm": str?, ... }}
    Notes:
      - RxTerms may be missing for non-prescribable concepts; fall back to `get_all_related_info` names if needed.
      - Prefer this for titles/labels shown to non-professionals.
    Example:
      input: rxcui="..." → {"rxcui":"...","rxtermsInfo":{"displayName":"Ibuprofen 200 mg oral tablet", ...}}
    """
    if not rxcui or not rxcui.strip():
        return json.dumps({"error": "rxcui is required"}, indent=2)

    url = f"https://rxnav.nlm.nih.gov/REST/RxTerms/rxcui/{rxcui}/allinfo.json"
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        data = r.json() or {}
    except requests.RequestException as e:
        return json.dumps({"rxcui": rxcui, "error": f"HTTP error contacting RxTerms: {e}"}, indent=2)

    info = data.get("rxtermsInfo") or data
    return json.dumps({"rxcui": rxcui, "rxtermsInfo": info}, indent=2)

if __name__ == "__main__":
    # Same transport your research server uses.
    mcp.run(transport="stdio")
