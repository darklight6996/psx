"""
shariah_engine.py — Deterministic Shariah compliance screening for PSX stocks.

Single source of truth (SSOT) for Shariah status across the entire system.
Implements the 5 KMI criteria plus purification calculator.

Rules:
- Defense/arms companies are evaluated on financial criteria, NOT auto-failed
  on industry classification alone.
- Status labels: COMPLIANT | NON_COMPLIANT | GRAY_AREA
- All UI tabs, pipeline, and Board Room must read from this engine.
- Board Room Shariah analyst is limited to notes only — cannot override status.
"""

import logging
from typing import Optional
from dataclasses import dataclass, field, asdict

from core.kmi_data import (
    KMI_ALL_SHARE,
    SHARIAH_THRESHOLDS as T,
    KNOWN_NON_COMPLIANT,
    ISLAMIC_BANKS,
    HARAM_SECTORS,
    is_kmi_listed_live,
)

logger = logging.getLogger(__name__)

# ── Defense / Arms companies — evaluated on financial criteria, not sector ──
DEFENSE_ARMS_TICKERS = [
    "POF", "HIT", "PAC", "SHFA",  # Pakistan Ordnance, Heavy Industries Taxila, etc.
]
DEFENSE_ARMS_SECTORS = [
    "defense", "arms", "ammunition", "ordnance", "military",
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CriterionResult:
    name:        str
    status:      str           # "PASS" | "FAIL" | "WARN" | "UNKNOWN"
    value:       Optional[str] = None
    threshold:   Optional[str] = None
    note:        str           = ""
    limit_pct:   float         = 0.0   # 0–1 how close to the limit (1 = at limit)


@dataclass
class ShariahReport:
    symbol:             str
    company_name:       str
    overall_status:     str            # "COMPLIANT" | "NON_COMPLIANT" | "GRAY_AREA"
    kmi_listed:         bool
    criteria:           list = field(default_factory=list)
    purification_pct:   float = 0.0   # % of dividend to give as sadaqah
    purification_note:  str   = ""
    risk_flag:          str   = ""    # e.g. "HIGH RISK: debt approaching limit"
    recommendation:     str   = ""
    kmi_check:          dict  = field(default_factory=dict)

    def to_dict(self):
        d = asdict(self)
        d["criteria"] = [asdict(c) for c in self.criteria]
        return d


# ---------------------------------------------------------------------------
# Core screener
# ---------------------------------------------------------------------------

def screen_stock(
    symbol: str,
    fundamentals: dict,
    sector: Optional[str] = None,
    industry: Optional[str] = None,
) -> ShariahReport:
    """
    Run the 5-criterion Shariah screen on a stock.

    Args:
        symbol:       PSX ticker (no suffix)
        fundamentals: output of data_engine.fetch_fundamentals()
        sector:       override sector string
        industry:     override industry string

    Returns:
        ShariahReport dataclass
    """
    sym = symbol.upper()
    company_name = fundamentals.get("company_name", sym)
    sec  = (sector or fundamentals.get("sector", "")).lower()
    ind  = (industry or fundamentals.get("industry", "")).lower()
    _kmi_result = is_kmi_listed_live(sym)
    kmi = _kmi_result["kmi_listed"] or sym in ISLAMIC_BANKS

    criteria = []
    overall  = "COMPLIANT"
    purif_pct = 0.0

    # ── Check if defense/arms company (financial screening only) ────────────
    is_defense = (
        sym in DEFENSE_ARMS_TICKERS
        or any(d in sec for d in DEFENSE_ARMS_SECTORS)
        or any(d in ind for d in DEFENSE_ARMS_SECTORS)
    )

    # ── 1. Core Business (Halal) ──────────────────────────────────────────────
    if sym in KNOWN_NON_COMPLIANT and sym not in ISLAMIC_BANKS:
        c1 = CriterionResult(
            name="Core Business",
            status="FAIL",
            note="Conventional interest-based banking/insurance or haram product",
            limit_pct=1.0,
        )
    elif is_defense:
        # Defense/arms: evaluate on financial criteria, not auto-fail
        c1 = CriterionResult(
            name="Core Business",
            status="WARN",
            note="Defense/arms company — evaluated on financial criteria only (not auto-failed)",
            limit_pct=0.5,
        )
    else:
        haram_match = next((h for h in HARAM_SECTORS if h in sec or h in ind), None)
        if haram_match:
            c1 = CriterionResult(
                name="Core Business",
                status="FAIL",
                note=f"Sector matches haram category: {haram_match}",
                limit_pct=1.0,
            )
        else:
            c1 = CriterionResult(
                name="Core Business",
                status="PASS",
                note="No haram activity detected in core business",
                limit_pct=0.0,
            )
    criteria.append(c1)

    # ── 2. Interest-Bearing Debt / Total Assets < 33% ─────────────────────────
    total_assets = fundamentals.get("total_assets")
    total_debt   = fundamentals.get("total_debt")
    debt_limit   = T["max_debt_to_assets"]

    if total_assets and total_debt and total_assets > 0:
        ratio = total_debt / total_assets
        limit_pct = ratio / debt_limit
        if ratio >= debt_limit:
            status = "FAIL"
            note   = f"Debt ratio {ratio:.1%} exceeds {debt_limit:.0%} limit"
        elif ratio >= debt_limit * 0.80:
            status = "WARN"
            note   = f"Debt ratio {ratio:.1%} approaching {debt_limit:.0%} limit — MONITOR"
        else:
            status = "PASS"
            note   = f"Debt ratio {ratio:.1%} within {debt_limit:.0%} limit"
        c2 = CriterionResult(
            name="Interest-Bearing Debt",
            status=status,
            value=f"{ratio:.1%}",
            threshold=f"< {debt_limit:.0%}",
            note=note,
            limit_pct=min(limit_pct, 1.5),
        )
    else:
        c2 = CriterionResult(
            name="Interest-Bearing Debt",
            status="UNKNOWN",
            note="Balance sheet data unavailable — manual verification required",
        )
    criteria.append(c2)

    # ── 3. Non-Halal Income < 5% of Revenue ──────────────────────────────────
    # yfinance doesn't break out non-halal income directly.
    # We use sector heuristics as a proxy.
    nhi_limit = T["max_non_halal_income"]
    if sym in KNOWN_NON_COMPLIANT and sym not in ISLAMIC_BANKS:
        c3 = CriterionResult(
            name="Non-Halal Income",
            status="FAIL",
            note="Business model generates haram income (interest, gambling, etc.)",
            limit_pct=1.0,
        )
    elif "bank" in sec or "finance" in sec or "insurance" in sec:
        c3 = CriterionResult(
            name="Non-Halal Income",
            status="WARN",
            note="Financial sector: non-halal income likely — manual verification needed",
            limit_pct=0.7,
        )
        purif_pct = max(purif_pct, 3.0)   # conservative purification estimate
    else:
        c3 = CriterionResult(
            name="Non-Halal Income",
            status="PASS",
            value=f"< {nhi_limit:.0%} (estimated)",
            threshold=f"< {nhi_limit:.0%}",
            note="No significant non-halal income streams detected",
            limit_pct=0.05,
        )
    criteria.append(c3)

    # ── 4. Illiquid Assets > 25% of Total Assets ─────────────────────────────
    # Proxy: fixed assets / total assets (yfinance balance sheet)
    illiq_limit = T["min_illiquid_assets"]
    # We can't always get illiquid asset breakdown from yfinance
    # Using equity/assets as a rough proxy; mark as UNKNOWN if data missing
    total_equity = fundamentals.get("total_equity")

    if total_assets and total_equity and total_assets > 0:
        # Rough: illiquid = total_assets - current_assets. Proxy: equity / assets
        illiq_proxy = total_equity / total_assets
        if illiq_proxy >= illiq_limit:
            c4 = CriterionResult(
                name="Illiquid Assets",
                status="PASS",
                value=f"~{illiq_proxy:.1%} (proxy)",
                threshold=f"> {illiq_limit:.0%}",
                note="Equity-to-assets suggests adequate illiquid assets",
                limit_pct=0.2,
            )
        else:
            c4 = CriterionResult(
                name="Illiquid Assets",
                status="WARN",
                value=f"~{illiq_proxy:.1%} (proxy)",
                threshold=f"> {illiq_limit:.0%}",
                note="Low equity/asset ratio — manual illiquid asset verification needed",
                limit_pct=0.8,
            )
    else:
        c4 = CriterionResult(
            name="Illiquid Assets",
            status="UNKNOWN",
            threshold=f"> {illiq_limit:.0%}",
            note="Balance sheet data unavailable — manually check annual report",
        )
    criteria.append(c4)

    # ── 5. Market Cap > Net Liquid Assets ─────────────────────────────────────
    market_cap = fundamentals.get("market_cap")
    if market_cap and total_assets and total_equity and total_equity > 0:
        net_liquid = total_assets - (total_equity or 0)
        if market_cap > net_liquid:
            c5 = CriterionResult(
                name="Market Cap vs Net Assets",
                status="PASS",
                note="Market cap exceeds net liquid assets ✓",
                limit_pct=0.1,
            )
        else:
            c5 = CriterionResult(
                name="Market Cap vs Net Assets",
                status="FAIL",
                note="Market cap below net liquid assets — stock may be trading below book",
                limit_pct=1.0,
            )
    else:
        c5 = CriterionResult(
            name="Market Cap vs Net Assets",
            status="UNKNOWN",
            note="Insufficient data for market cap / net asset comparison",
        )
    criteria.append(c5)

    # ── Overall status ────────────────────────────────────────────────────────
    has_fail    = any(c.status == "FAIL"    for c in criteria)
    has_warn    = any(c.status == "WARN"    for c in criteria)
    has_unknown = any(c.status == "UNKNOWN" for c in criteria)

    if kmi:
        # If officially KMI listed or an Islamic Bank, it is Shariah compliant
        overall = "COMPLIANT"
    elif has_fail:
        overall = "NON_COMPLIANT"
    elif has_warn or has_unknown:
        overall = "GRAY_AREA"
    else:
        overall = "COMPLIANT"

    # ── Risk flag ─────────────────────────────────────────────────────────────
    risk_flag = ""
    for c in criteria:
        if c.status == "WARN" and c.limit_pct >= 0.8:
            risk_flag = f"⚠️ HIGH RISK: {c.name} approaching compliance limit"
            break
        elif c.status == "WARN":
            risk_flag = f"⚠️ MONITOR: {c.name} needs attention"

    # ── Purification note ─────────────────────────────────────────────────────
    purif_note = ""
    if purif_pct > 0:
        purif_note = (
            f"Give approximately {purif_pct:.1f}% of dividends received "
            f"to charity (sadaqah) to purify earnings from borderline non-halal income. "
            f"Consult an Islamic finance scholar for a precise ruling."
        )

    # ── Recommendation ───────────────────────────────────────────────────────
    if overall == "NON_COMPLIANT":
        recommendation = "Do NOT invest. Consult an Islamic scholar before considering any position."
    elif overall == "GRAY_AREA":
        recommendation = "Invest cautiously. Verify flagged criteria using the company's latest annual report."
    else:
        recommendation = "Shariah-compliant based on available data. Standard investment criteria apply."

    return ShariahReport(
        symbol=sym,
        company_name=company_name,
        overall_status=overall,
        kmi_listed=kmi,
        criteria=criteria,
        purification_pct=purif_pct,
        purification_note=purif_note,
        risk_flag=risk_flag,
        recommendation=recommendation,
        kmi_check=_kmi_result,
    )


# ---------------------------------------------------------------------------
# Purification calculator (standalone)
# ---------------------------------------------------------------------------

def calc_purification(
    dividend_received: float,
    non_halal_income_pct: float,
) -> dict:
    """
    Calculate how much of a dividend must be given to charity.

    Args:
        dividend_received:   PKR amount of dividend you received
        non_halal_income_pct: estimated % of company revenue that is non-halal (0–1)

    Returns:
        dict with purification_amount, charity_note
    """
    purif_amount = dividend_received * non_halal_income_pct
    return {
        "dividend_received":    round(dividend_received, 2),
        "non_halal_pct":        round(non_halal_income_pct * 100, 2),
        "purification_amount":  round(purif_amount, 2),
        "you_keep":             round(dividend_received - purif_amount, 2),
        "charity_note": (
            f"Give PKR {purif_amount:,.2f} ({non_halal_income_pct*100:.1f}% of PKR {dividend_received:,.2f}) "
            f"to a recognised charity. You may keep the remaining PKR {dividend_received - purif_amount:,.2f}."
        ),
    }


# ---------------------------------------------------------------------------
# Quick pipeline helper
# ---------------------------------------------------------------------------

def quick_screen(symbol: str, fundamentals: dict, sector: str = "", industry: str = "") -> str:
    """
    Return just the Shariah status string for pipeline use.
    One of: 'COMPLIANT', 'NON_COMPLIANT', 'GRAY_AREA'
    """
    report = screen_stock(symbol, fundamentals, sector, industry)
    return report.overall_status
