"""
core/psx_signals.py — PSX-specific signal enrichment.
Fetches KIBOR rates, calculates sector rotation, upcoming earnings, and market breadth.
"""

import os
import json
import time
import logging
import requests
from datetime import date, datetime, timedelta
import pandas as pd
import yfinance as yf
from bs4 import BeautifulSoup

from core.data_engine import fetch_ohlcv

logger = logging.getLogger(__name__)

CACHE_FILE = "data/signal_cache.json"

SECTOR_MAP = {
    # Technology & Telecom
    "SYS": "Technology & Telecom", "TRG": "Technology & Telecom", "NETSOL": "Technology & Telecom", 
    "AVN": "Technology & Telecom", "TELE": "Technology & Telecom", "PTC": "Technology & Telecom", 
    "WTL": "Technology & Telecom", "OCTOPUS": "Technology & Telecom", "AIRLINK": "Technology & Telecom",
    # Oil & Gas Exploration
    "OGDC": "Oil & Gas Exploration", "PPL": "Oil & Gas Exploration", "MARI": "Oil & Gas Exploration", "POL": "Oil & Gas Exploration",
    # Oil & Gas Marketing
    "PSO": "Oil & Gas Marketing", "HASCOL": "Oil & Gas Marketing", "APL": "Oil & Gas Marketing", 
    "SNGP": "Oil & Gas Marketing", "SSGC": "Oil & Gas Marketing", "SHEL": "Oil & Gas Marketing",
    # Refineries
    "ATR": "Refineries", "PRL": "Refineries", "NRL": "Refineries", "CNERGY": "Refineries",
    # Cement
    "LUCK": "Cement", "DGKC": "Cement", "MLCF": "Cement", "PIOC": "Cement", "CHCC": "Cement", 
    "FCCL": "Cement", "KOHC": "Cement", "BWCL": "Cement", "SGWL": "Cement", "FLYNG": "Cement", "PAEL": "Cement",
    # Fertilizer
    "ENGRO": "Fertilizer", "EFERT": "Fertilizer", "FATIMA": "Fertilizer", "FFC": "Fertilizer", "FFBL": "Fertilizer",
    # Power Generation & Distribution
    "HUBC": "Power Generation & Distribution", "NCPL": "Power Generation & Distribution", "KAPCO": "Power Generation & Distribution", 
    "PKGP": "Power Generation & Distribution", "LTPH": "Power Generation & Distribution", "NPL": "Power Generation & Distribution", 
    "SPEL": "Power Generation & Distribution", "EPQL": "Power Generation & Distribution", "KEL": "Power Generation & Distribution",
    # Chemicals & Paper
    "ICI": "Chemicals & Paper", "LOTCHEM": "Chemicals & Paper", "SITC": "Chemicals & Paper", 
    "DYNO": "Chemicals & Paper", "EPCL": "Chemicals & Paper", "SPL": "Chemicals & Paper",
    # Textile
    "NML": "Textile", "GATM": "Textile", "KTML": "Textile", "NCL": "Textile", "ANL": "Textile", 
    "DSFL": "Textile", "ILP": "Textile", "MSOT": "Textile", "HAWL": "Textile",
    # Food & Beverages / Personal Care
    "NESTLE": "Food & Beverages / Personal Care", "QUICE": "Food & Beverages / Personal Care", "UNITY": "Food & Beverages / Personal Care", 
    "NATF": "Food & Beverages / Personal Care", "FCEPL": "Food & Beverages / Personal Care", "SHEZ": "Food & Beverages / Personal Care", 
    "MFFL": "Food & Beverages / Personal Care", "UPFL": "Food & Beverages / Personal Care",
    # Pharmaceuticals
    "SEARL": "Pharmaceuticals", "HINOON": "Pharmaceuticals", "GLAXO": "Pharmaceuticals", 
    "ABOT": "Pharmaceuticals", "FEROZ": "Pharmaceuticals", "AGP": "Pharmaceuticals", "IBFL": "Pharmaceuticals",
    # Steel & Engineering
    "ISL": "Steel & Engineering", "ASTL": "Steel & Engineering", "MUGHAL": "Steel & Engineering", 
    "CSAP": "Steel & Engineering", "ASL": "Steel & Engineering", "INIL": "Steel & Engineering", 
    "KSBP": "Steel & Engineering", "ITTEFAQ": "Steel & Engineering",
    # Automobile Assembler / Parts
    "HCAR": "Automobile Assembler / Parts", "INDU": "Automobile Assembler / Parts", "MTL": "Automobile Assembler / Parts", 
    "GHNI": "Automobile Assembler / Parts", "GHNL": "Automobile Assembler / Parts", "GTYR": "Automobile Assembler / Parts", 
    "THALL": "Automobile Assembler / Parts", "LOADS": "Automobile Assembler / Parts",
    # Glass & Ceramics
    "GHGL": "Glass & Ceramics", "TGL": "Glass & Ceramics",
    # Transport / Logistics
    "PIBTL": "Transport / Logistics", "TRIPF": "Transport / Logistics",
    # Miscellaneous / Real Estate
    "MEDIA": "Miscellaneous / Real Estate", "PACE": "Miscellaneous / Real Estate", "TPL": "Miscellaneous / Real Estate", 
    "TPLP": "Miscellaneous / Real Estate", "GTECH": "Miscellaneous / Real Estate"
}

REPRESENTATIVE_TICKERS = {
    "Technology & Telecom": ["SYS", "TRG", "NETSOL"],
    "Oil & Gas Exploration": ["OGDC", "PPL", "MARI"],
    "Oil & Gas Marketing": ["PSO", "APL", "SNGP"],
    "Refineries": ["ATR", "PRL", "NRL"],
    "Cement": ["LUCK", "DGKC", "MLCF"],
    "Fertilizer": ["ENGRO", "EFERT", "FFC"],
    "Power Generation & Distribution": ["HUBC", "KAPCO", "KEL"],
    "Chemicals & Paper": ["ICI", "LOTCHEM", "EPCL"],
    "Textile": ["NML", "GATM", "ILP"],
    "Food & Beverages / Personal Care": ["NESTLE", "UNITY", "NATF"],
    "Pharmaceuticals": ["SEARL", "HINOON", "GLAXO"],
    "Steel & Engineering": ["ISL", "MUGHAL", "ASTL"],
    "Automobile Assembler / Parts": ["HCAR", "INDU", "MTL"],
    "Glass & Ceramics": ["GHGL", "TGL"],
    "Transport / Logistics": ["PIBTL"],
    "Miscellaneous / Real Estate": ["TPL", "TPLP"]
}


def _load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_cache(cache: dict):
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving signal cache: {e}")


def scrape_kibor_from_sbp() -> float:
    """
    Attempts to scrape the current 6-month KIBOR offer rate from the SBP website.

    Tries two pages:
      1. https://www.sbp.org.pk/ecodata/kibor_index.asp  (live dashboard)
      2. https://www.sbp.org.pk/ecodata/kibor.asp         (legacy page)

    Falls back to 12.5% (approximate SBP rate as of mid-2026) on all failures.
    """
    default_rate = 12.5   # Updated: SBP has cut rates significantly from the 22% peak
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    urls_to_try = [
        "https://www.sbp.org.pk/ecodata/kibor_index.asp",
        "https://www.sbp.org.pk/ecodata/kibor.asp",
    ]

    for url in urls_to_try:
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code != 200:
                logger.warning(f"[KIBOR] {url} returned HTTP {resp.status_code}")
                continue

            soup = BeautifulSoup(resp.text, "lxml")

            # Strategy 1: Find table row that mentions "6-month" or "6 m" and extract rate
            for tr in soup.find_all("tr"):
                cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if not cells:
                    continue
                row_text = " ".join(cells).lower()
                if any(kw in row_text for kw in ("6-m", "6 m", "6month", "6-month", "six month")):
                    floats = []
                    for c in cells:
                        try:
                            val = float(c.replace("%", "").replace(",", "").strip())
                            if 3.0 < val < 35.0:
                                floats.append(val)
                        except ValueError:
                            pass
                    if floats:
                        found_rate = max(floats)  # Prefer offer rate (higher value)
                        logger.info(f"[KIBOR] Scraped 6-M offer rate from {url}: {found_rate}%")
                        return found_rate

            # Strategy 2: Collect all rate-like numbers from the page and use positional heuristic.
            # kibor_index.asp shows ~3 tenors x 2 columns (bid/offer) = 6 numeric cells.
            # The 6-month tenor is typically in the middle (indices 2-3).
            all_rates = []
            for td in soup.find_all("td"):
                text = td.get_text(strip=True)
                try:
                    val = float(text.replace("%", "").replace(",", "").strip())
                    if 3.0 < val < 35.0:
                        all_rates.append(val)
                except ValueError:
                    pass

            if len(all_rates) >= 4:
                mid_offer = max(all_rates[2], all_rates[3])
                logger.info(f"[KIBOR] Strategy-2 positional estimate from {url}: {mid_offer}%")
                return mid_offer

        except Exception as e:
            logger.warning(f"[KIBOR] Error scraping {url}: {e}")
            continue

    logger.warning(f"[KIBOR] All scrape attempts failed — using default {default_rate}%")
    return default_rate


def get_kibor_context() -> dict:
    """
    Returns KIBOR context. Caches result for 4 hours to avoid hammering SBP.
    """
    cache = _load_cache()
    now = time.time()
    
    cached_kibor = cache.get("kibor")
    if cached_kibor and (now - cached_kibor.get("timestamp", 0) < 14400):
        return cached_kibor
        
    rate = scrape_kibor_from_sbp()
    # High interest rates are bearish for equities
    sentiment = "bearish" if rate > 15.0 else "bullish" if rate < 12.0 else "neutral"
    
    kibor_data = {
        "rate": rate,
        "sentiment": sentiment,
        "timestamp": now,
        "source": "State Bank of Pakistan",
        "updated_at": datetime.now().isoformat()
    }
    
    cache["kibor"] = kibor_data
    _save_cache(cache)
    return kibor_data


def compute_all_sector_momentum() -> dict:
    """
    Computes 10-day sector return based on representative tickers.
    """
    sector_returns = {}
    for sector, tickers in REPRESENTATIVE_TICKERS.items():
        ticker_returns = []
        for t in tickers:
            try:
                df = fetch_ohlcv(t, period="1mo", interval="1d")
                if df is not None and len(df) >= 11:
                    closes = df["Close"]
                    ret = ((closes.iloc[-1] - closes.iloc[-11]) / closes.iloc[-11]) * 100
                    ticker_returns.append(ret)
            except Exception:
                pass
        if ticker_returns:
            sector_returns[sector] = sum(ticker_returns) / len(ticker_returns)
        else:
            sector_returns[sector] = 0.0
            
    # Rank sectors
    sorted_sectors = sorted(sector_returns.items(), key=lambda x: x[1], reverse=True)
    ranked = {item[0]: {"return": item[1], "rank": idx + 1} for idx, item in enumerate(sorted_sectors)}
    
    n_sectors = len(sorted_sectors)
    for sector, info in ranked.items():
        rank = info["rank"]
        if rank <= max(1, n_sectors // 4):
            status = "LEADER"
        elif rank > n_sectors - max(1, n_sectors // 4):
            status = "LAGGARD"
        else:
            status = "NEUTRAL"
        info["status"] = status
        
    return ranked


def get_sector_rotation(symbol: str) -> dict:
    """
    Returns the target stock's sector momentum status. Caches for 4 hours.
    """
    cache = _load_cache()
    now = time.time()
    
    cached_rot = cache.get("sector_rotation")
    if not cached_rot or (now - cached_rot.get("timestamp", 0) > 14400):
        try:
            ranked = compute_all_sector_momentum()
            cached_rot = {
                "sectors": ranked,
                "timestamp": now,
                "updated_at": datetime.now().isoformat()
            }
            cache["sector_rotation"] = cached_rot
            _save_cache(cache)
        except Exception as e:
            logger.error(f"Error computing sector rotation: {e}")
            
    target_sector = SECTOR_MAP.get(symbol.upper(), "Unknown")
    
    if cached_rot and "sectors" in cached_rot:
        sec_info = cached_rot["sectors"].get(target_sector)
        if sec_info:
            return {
                "sector": target_sector,
                "return": round(sec_info["return"], 2),
                "rank": sec_info["rank"],
                "status": sec_info["status"],
                "total_sectors": len(cached_rot["sectors"])
            }
            
    return {
        "sector": target_sector,
        "return": 0.0,
        "rank": 0,
        "status": "NEUTRAL",
        "total_sectors": 0
    }


def get_earnings_proximity(symbol: str) -> dict:
    """
    Fetches the next earnings date from yfinance and flags risk proximity.
    """
    try:
        ticker = yf.Ticker(f"{symbol.upper()}.KA")
        cal = ticker.calendar
        next_earnings = None
        
        if cal is not None:
            if isinstance(cal, pd.DataFrame) and not cal.empty and "Earnings Date" in cal.index:
                earnings_dates = cal.loc["Earnings Date"].iloc[0]
                if isinstance(earnings_dates, list) and len(earnings_dates) > 0:
                    next_earnings = earnings_dates[0]
                else:
                    next_earnings = earnings_dates
            elif isinstance(cal, dict) and "Earnings Date" in cal:
                earnings_dates = cal["Earnings Date"]
                if isinstance(earnings_dates, list) and len(earnings_dates) > 0:
                    next_earnings = earnings_dates[0]
                else:
                    next_earnings = earnings_dates
                    
        if next_earnings is None:
            try:
                info = ticker.info or {}
                next_earnings = info.get("earningsDate") or info.get("nextEarningsDate")
            except Exception:
                pass
                
        if next_earnings:
            if isinstance(next_earnings, (int, float)):
                dt = datetime.fromtimestamp(next_earnings).date()
            elif isinstance(next_earnings, str):
                dt = datetime.strptime(next_earnings.split("T")[0], "%Y-%m-%d").date()
            else:
                dt = next_earnings
                if hasattr(dt, "date"):
                    dt = dt.date()
                    
            days_to = (dt - date.today()).days
            if days_to < 0:
                return {"status": "CLEAR", "days_to_earnings": None, "date": str(dt)}
                
            if days_to < 5:
                status = "HIGH_RISK"
            elif days_to < 20:
                status = "CAUTION"
            else:
                status = "CLEAR"
                
            return {
                "status": status,
                "days_to_earnings": days_to,
                "date": str(dt)
            }
    except Exception as e:
        logger.warning(f"Could not retrieve earnings proximity for {symbol}: {e}")
        
    return {
        "status": "CLEAR",
        "days_to_earnings": None,
        "date": "Unknown"
    }


def get_psx_breadth() -> dict:
    """
    Calculates KSE-100 market breadth status. Caches for 4 hours.
    """
    cache = _load_cache()
    now = time.time()
    
    cached_breadth = cache.get("breadth")
    if cached_breadth and (now - cached_breadth.get("timestamp", 0) < 14400):
        return cached_breadth
        
    df = None
    try:
        url = "https://dps.psx.com.pk/timeseries/eod/KSE100"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json().get("data", [])
            if data and len(data) >= 20:
                rows = []
                for item in reversed(data):
                    rows.append({
                        "Date": pd.to_datetime(item[0], unit="s", utc=True).tz_convert("Asia/Karachi"),
                        "Close": float(item[1]),
                        "Volume": float(item[2])
                    })
                df = pd.DataFrame(rows)
                if not df.empty:
                    df.set_index("Date", inplace=True)
                    df["Open"] = df["Close"].shift(1)
                    df["High"] = df["Close"]
                    df["Low"] = df["Close"]
                    df = df.dropna()
    except Exception as e:
        logger.warning(f"Could not fetch KSE-100 index from PSX portal: {e}. Falling back to yfinance.")

    if df is None or df.empty or len(df) < 20:
        try:
            df = fetch_ohlcv("^KSE100", period="3mo", interval="1d")
            if df is not None and len(df) < 20:
                df = fetch_ohlcv("KSE100.KA", period="3mo", interval="1d")
        except Exception:
            pass
            
    if df is None or df.empty or len(df) < 20:
        return {
            "status": "CONSOLIDATING",
            "index_price": 0.0,
            "ema_20": 0.0,
            "atr_10": 0.0,
            "up_down_ratio": 1.0,
            "sentiment": "neutral",
            "timestamp": now,
            "updated_at": datetime.now().isoformat()
        }
            
    try:
        closes = df["Close"]
        ema_20 = float(closes.ewm(span=20, adjust=False).mean().iloc[-1])
        latest_close = float(closes.iloc[-1])
        
        # Calculate 10-day ATR
        high = df["High"]
        low = df["Low"]
        close_prev = closes.shift(1)
        tr1 = high - low
        tr2 = (high - close_prev).abs()
        tr3 = (low - close_prev).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr_10 = float(tr.rolling(10).mean().iloc[-1])
        
        # Calculate up/down ratio
        last_10 = df.tail(10)
        up_days = sum(1 for i in range(len(last_10)) if last_10["Close"].iloc[i] > last_10["Open"].iloc[i])
        down_days = len(last_10) - up_days
        up_down_ratio = float(up_days / max(1, down_days))
        
        if latest_close > ema_20 and up_down_ratio > 1.2:
            sentiment = "bullish"
            status = "EXPANDING"
        elif latest_close < ema_20 and up_down_ratio < 0.8:
            sentiment = "bearish"
            status = "CONTRACTING"
        else:
            sentiment = "neutral"
            status = "CONSOLIDATING"
            
        breadth_data = {
            "status": status,
            "index_price": round(latest_close, 2),
            "ema_20": round(ema_20, 2),
            "atr_10": round(atr_10, 2),
            "up_down_ratio": round(up_down_ratio, 2),
            "sentiment": sentiment,
            "timestamp": now,
            "updated_at": datetime.now().isoformat()
        }
        
        cache["breadth"] = breadth_data
        _save_cache(cache)
        return breadth_data
    except Exception as e:
        logger.error(f"Error calculating PSX breadth: {e}")
        return {
            "status": "CONSOLIDATING",
            "index_price": 0.0,
            "ema_20": 0.0,
            "atr_10": 0.0,
            "up_down_ratio": 1.0,
            "sentiment": "neutral",
            "timestamp": now,
            "updated_at": datetime.now().isoformat()
        }


def enrich_analysis(symbol: str, base_analysis: dict) -> dict:
    """
    Enriches the single-stock analysis dictionary with PSX-specific metrics.

    Two-stage system (PSX-calibrated):
      Stage 1 — Hard disqualifiers (override rating)
      Stage 2 — Score adjustments only (DO NOT re-rate)

    The rating from rule_engine + ML blend is authoritative.
    Only hard disqualifiers can override it.
    """
    symbol = symbol.upper()
    kibor = get_kibor_context()
    sector_rot = get_sector_rotation(symbol)
    earnings = get_earnings_proximity(symbol)
    breadth = get_psx_breadth()
    
    psx_signals = {
        "kibor": kibor,
        "sector_rotation": sector_rot,
        "earnings": earnings,
        "market_breadth": breadth
    }
    
    base_analysis["psx_signals"] = psx_signals
    
    advisory = base_analysis.get("advisory")
    if not advisory:
        return base_analysis
        
    score = advisory.get("score", 50.0)
    reasons = advisory.get("rationale", [])
    rating = advisory["rating"]
    
    # Check if stock is Shariah compliant
    shariah = base_analysis.get("shariah", {})
    shariah_ok = shariah.get("overall_status") == "COMPLIANT"
    
    # ── STAGE 1: Hard Disqualifiers ──────────────────────────────────────────
    # These are the ONLY things that can override the rule-engine + ML rating.
    
    # 1a. Non-Shariah stocks can never be BUY
    if not shariah_ok and rating == "BUY":
        rating = "HOLD"
        reasons.append("Non-Shariah compliant — BUY downgraded to HOLD")
    
    # 1b. Earnings within 5 days — force HOLD (don't gamble on earnings)
    if earnings["status"] == "HIGH_RISK" and rating == "BUY":
        rating = "HOLD"
        reasons.append(f"Upcoming earnings in {earnings['days_to_earnings']} days — BUY deferred to HOLD")
    
    # ── STAGE 2: Score Adjustments (informational — no re-rating) ────────────
    # These adjust the composite score shown in the UI but do NOT change the
    # rating. The rating from rule_engine + ML is the final word.
    
    # 2a. Interest Rate Penalty (reduced from -8 to -5)
    if kibor["sentiment"] == "bearish":
        score -= 5
        reasons.append(f"KIBOR rate bearish ({kibor['rate']:.1f}%) — score -5")
        
    # 2b. Sector Laggard Penalty (reduced from -5 to -3)
    if sector_rot["status"] == "LAGGARD":
        score -= 3
        reasons.append(f"Sector laggard ({sector_rot['sector']}) — score -3")
    
    # 2c. Sector Leader Bonus (NEW — reward sector leaders)
    if sector_rot["status"] == "LEADER":
        score += 3
        reasons.append(f"Sector leader ({sector_rot['sector']}) — score +3")
        
    # 2d. Market Breadth Penalty (reduced from -5 to -3)
    if breadth["status"] == "CONTRACTING":
        score -= 3
        reasons.append("KSE-100 breadth contracting — score -3")
        
    # Clamp score
    score = max(0.0, min(100.0, score))
                
    # Update advisory fields (score only — rating stays from Stage 1)
    advisory["score"] = round(score, 1)
    advisory["composite"] = round(score, 1)
    advisory["rating"] = rating
    advisory["rationale"] = reasons
    
    return base_analysis
