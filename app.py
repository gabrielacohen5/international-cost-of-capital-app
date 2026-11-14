"""International cost of capital comparison. Python 3.12 / Streamlit."""
from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import re
import unicodedata

import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup
import streamlit as st

st.set_page_config(page_title="International Cost of Capital", page_icon="🌐", layout="wide")

BETAS_URL = "https://pages.stern.nyu.edu/~adamodar/pc/datasets/betas.xls"
RATINGS_URL = "https://pages.stern.nyu.edu/adamodar/New_Home_Page/datafile/ratings.html"
OECD_URL = "https://www.oecd.org/en/publications/corporate-tax-statistics-2026_73af6222-en/full-report/statutory-corporate-income-tax-rates_ce84abb9.html"
BONDS_URL = "https://tradingeconomics.com/country-list/government-bond-10y"
OECD_STATLINK_XLSX = "https://stat.link/mstq82"  # Figure 2.1 official 2026 OECD data workbook
# OECD SDMX public CSV endpoint; dynamic data availability and dimension names can change.
OECD_API = "https://sdmx.oecd.org/public/rest/v1/data/OECD.CTP.TPS,DSD_TAX_CIT@DF_CIT,2.0/.A..ST..S13..."
COUNTRIES = {
    "United States": ("USD", "United States"), "Australia": ("AUD", "Australia"),
    "Austria": ("EUR", "Austria"), "Belgium": ("EUR", "Belgium"),
    "Brazil": ("BRL", "Brazil"), "Canada": ("CAD", "Canada"),
    "Chile": ("CLP", "Chile"), "China": ("CNY", "China"),
    "Colombia": ("COP", "Colombia"), "Czech Republic": ("CZK", "Czech Republic"),
    "Denmark": ("DKK", "Denmark"), "Finland": ("EUR", "Finland"),
    "France": ("EUR", "France"), "Germany": ("EUR", "Germany"),
    "Greece": ("EUR", "Greece"), "Hungary": ("HUF", "Hungary"),
    "India": ("INR", "India"), "Indonesia": ("IDR", "Indonesia"),
    "Ireland": ("EUR", "Ireland"), "Israel": ("ILS", "Israel"),
    "Italy": ("EUR", "Italy"), "Japan": ("JPY", "Japan"),
    "Malaysia": ("MYR", "Malaysia"), "Mexico": ("MXN", "Mexico"),
    "Netherlands": ("EUR", "Netherlands"), "New Zealand": ("NZD", "New Zealand"),
    "Norway": ("NOK", "Norway"), "Peru": ("PEN", "Peru"),
    "Philippines": ("PHP", "Philippines"), "Poland": ("PLN", "Poland"),
    "Portugal": ("EUR", "Portugal"), "Singapore": ("SGD", "Singapore"),
    "South Africa": ("ZAR", "South Africa"), "South Korea": ("KRW", "South Korea"),
    "Spain": ("EUR", "Spain"), "Sweden": ("SEK", "Sweden"),
    "Switzerland": ("CHF", "Switzerland"), "Thailand": ("THB", "Thailand"),
    "Turkey": ("TRY", "Turkey"), "United Kingdom": ("GBP", "United Kingdom"),
}
# These are editable *fallback illustrations*, NOT asserted current market observations.
FALLBACK_BETAS = {"Software (System & Application)": 0.80, "Healthcare Support Services": 0.90,
                  "Business & Consumer Services": 0.95, "Retail (General)": 0.85,
                  "Machinery": 1.00, "Utilities (General)": 0.65}
DEFAULT_US_TAX = 21.0


def fetch(url: str, timeout: int = 20) -> requests.Response:
    response = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0 (compatible; AcademicResearch/1.0)", "Accept": "text/html,application/vnd.ms-excel,text/csv,*/*"})
    response.raise_for_status()
    return response


def normalized(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode().lower())


def parse_number(value: object) -> float | None:
    if pd.isna(value):
        return None
    txt = str(value).strip().replace(",", "").replace("%", "")
    try:
        return float(txt)
    except (ValueError, TypeError):
        return None


def load_betas() -> tuple[dict[str, float], str]:
    content = fetch(BETAS_URL).content
    sheets = pd.read_excel(BytesIO(content), sheet_name=None, header=None)
    for frame in sheets.values():
        for idx in range(min(18, len(frame))):
            header = [normalized(x) for x in frame.iloc[idx].tolist()]
            industry_cols = [i for i, v in enumerate(header) if v in ("industryname", "industry")]
            beta_cols = [i for i, v in enumerate(header) if "unleveredbeta" in v and "cash" not in v]
            if not industry_cols or not beta_cols:
                continue
            out = {}
            for _, row in frame.iloc[idx + 1:].iterrows():
                name = str(row.iloc[industry_cols[0]]).strip()
                beta = parse_number(row.iloc[beta_cols[0]])
                if name and name.lower() != "nan" and beta is not None and 0 < beta < 10:
                    out[name] = beta
            if len(out) >= 15:
                return out, "Damodaran U.S. industry betas; source workbook (publication date not reliably machine-readable)"
    raise ValueError("Could not identify Industry Name and Unlevered beta columns")


def load_bbb_spread() -> tuple[float, str]:
    """The left-hand rating/spread pair is for large non-financial firms."""
    soup = BeautifulSoup(fetch(RATINGS_URL).text, "html.parser")
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"], recursive=False)]
        rating_positions = [i for i, cell in enumerate(cells)
                            if re.fullmatch(r"Baa2\s*/\s*BBB", cell, re.I)]
        if not rating_positions:
            continue
        # The first BBB rating belongs to the large non-financial company section.
        pos = rating_positions[0]
        if pos + 1 < len(cells):
            raw = cells[pos + 1]
            value = parse_number(raw)
            if value is not None and "%" in raw and 0 < value < 20:
                date_match = re.search(r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+20\d{2}", soup.get_text(" ", strip=True))
                date_label = date_match.group(0) if date_match else "date not detected"
                return value, f"Damodaran large non-financial firms Baa2/BBB; analysis: {date_label}"
    raise ValueError("Cannot identify the large non-financial Baa2/BBB spread in the source table")


def parse_trading_economics_html(html: str) -> tuple[dict[str, float], dict[str, str]]:
    """Parse the public 10-year table by row, without relying on fragile header markup.

    Some deployments receive a site challenge or JavaScript-only shell instead
    of the populated table. Reject those pages, and never fabricate quotes.
    """
    soup = BeautifulSoup(html, "html.parser")
    results: dict[str, float] = {}
    dates: dict[str, str] = {}
    names = {normalized(name): name for name in COUNTRIES}
    for table in soup.select("table"):
        table_headers = " ".join(normalized(x.get_text(" ", strip=True)) for x in table.select("th"))
        # Never interpret other instrument tables as government bond yields.
        if "country" not in table_headers or "last" not in table_headers:
            continue
        for tr in table.select("tr"):
            cells = tr.find_all("td", recursive=False)
            if len(cells) < 2:
                continue
            first = re.sub(r"\s+", " ", cells[0].get_text(" ", strip=True)).strip()
            country = names.get(normalized(first))
            if not country:
                continue
            value = parse_number(cells[1].get_text(" ", strip=True))
            if value is None or not -10 < value < 100:
                continue
            results[country] = value
            if len(cells) > 3:
                dates[country] = cells[3].get_text(" ", strip=True)
        if results:
            break
    # Backstop: HTML parsers may split the headings into markup and/or put the
    # country name into an anchor without a conventional table header.
    if not results:
        for table in soup.select("table"):
            for tr in table.select("tr"):
                cells = tr.find_all("td", recursive=False)
                if len(cells) < 4:
                    continue
                country = names.get(normalized(cells[0].get_text(" ", strip=True)))
                if not country:
                    continue
                rate = parse_number(cells[1].get_text(" ", strip=True))
                reference = cells[3].get_text(" ", strip=True)
                if rate is not None and -10 < rate < 100 and re.search(r"(?:/20?\d\d|/\d\d|20\d\d)", reference):
                    results[country] = rate
                    dates[country] = reference
            if len(results) >= 2:
                break
    return results, dates


def load_bond_yields() -> tuple[dict[str, float], str]:
    """Trading Economics public country 10-year yield page; no API key required."""
    failures = []
    for url in (BONDS_URL, "https://tradingeconomics.com/bonds"):
        try:
            html = fetch(url, timeout=22).text
            rates, dates = parse_trading_economics_html(html)
            if "United States" not in rates or len(rates) < 5:
                raise ValueError(f"only {len(rates)} country quotes extracted (U.S. required)")
            return rates, f"Trading Economics 10Y yields; {len(rates)} countries; reference labels: " + ", ".join(f"{c} {dates.get(c, '?')}" for c in ("United States", "Australia") if c in rates)
        except Exception as exc:
            failures.append(f"{url.rsplit('/', 1)[-1]}: {type(exc).__name__}: {str(exc)[:90]}")
    raise ValueError("Cannot read Trading Economics public 10Y table. " + "; ".join(failures))


def parse_oecd_statlink_xlsx(content: bytes) -> tuple[dict[str, float], str]:
    """Extract 2026 combined statutory CIT rates from OECD Figure 2.1.

    Statlink chart workbooks do not necessarily have conventional headers:
    jurisdictions may be in rows or columns, and rates can be a nearby
    unlabeled series. Evaluate both orientations and validate candidates
    against explicit 2026 rates in the OECD publication before accepting.
    Never substitute a rate from an unrelated sheet or historical series.
    """
    sheets = pd.read_excel(BytesIO(content), sheet_name=None, header=None, engine="openpyxl")
    names = {normalized(name): name for name in COUNTRIES}
    names.update({
        "korea": "South Korea", "republicofkorea": "South Korea",
        "korearepublicof": "South Korea", "turkiye": "Turkey",
        "czechia": "Czech Republic", "unitedstatesofamerica": "United States",
        "uk": "United Kingdom", "usa": "United States", "us": "United States",
    })
    # These reference points are stated in OECD Corporate Tax Statistics 2026:
    # France 36.1%, Colombia 35%, Hungary 9%. They help reject unrelated data.
    anchors = {"France": 36.1, "Colombia": 35.0, "Hungary": 9.0}
    country_keys = set(COUNTRIES)
    candidates = []
    notes = []

    def to_country(x):
        name = names.get(normalized(x))
        return name if name in country_keys else None

    def rate(x):
        val = parse_number(x)
        if val is None or not 0 <= val <= 60:
            return None
        return float(val)

    def evaluate(pairs, sheet, orientation, label, year_label=""):
        """A candidate is accepted only if independently published anchors match."""
        mapping = {}
        for name, value in pairs:
            if name is not None and value is not None:
                if name in mapping and abs(mapping[name] - value) > 0.05:
                    return
                mapping[name] = value
        if len(mapping) < 8:
            return
        verified = sum(abs(mapping[key] - expected) <= 0.20
                       for key, expected in anchors.items() if key in mapping)
        conflicts = sum(abs(mapping[key] - expected) > 0.20
                        for key, expected in anchors.items() if key in mapping)
        if verified < 2 or conflicts:
            return
        # In the publication, the data refer to 2026; prefer this year in labels.
        # Prefer the 2026 observation if the workbook includes several years.
        if re.fullmatch(r"20\d{2}", year_label) and year_label != "2026":
            return
        score = (verified * 100 + len(mapping) + (10 if "2026" in label else 0)
                 + (35 if year_label == "2026" else 0)
                 + (6 if "combined" in normalized(label) else 0))
        candidates.append((score, mapping, sheet, orientation))

    for sheet_name, frame in sheets.items():
        frame = frame.dropna(axis=0, how="all").dropna(axis=1, how="all").reset_index(drop=True)
        if frame.empty:
            continue
        label_text = " ".join(str(x) for x in frame.iloc[:min(12,len(frame))].values.flatten() if pd.notna(x))
        notes.append(f"{sheet_name}: {frame.shape[0]}x{frame.shape[1]}")
        # Find country positions in every column, without assuming a header row.
        for country_col in range(frame.shape[1]):
            found = [(i, to_country(frame.iat[i, country_col])) for i in range(len(frame))]
            found = [(i, name) for i, name in found if name]
            if len({name for _, name in found}) < 8:
                continue
            for value_col in range(frame.shape[1]):
                if value_col == country_col:
                    continue
                pairs = [(name, rate(frame.iat[i, value_col])) for i, name in found]
                header = " ".join(str(frame.iat[i, value_col]) for i in range(min(15, len(frame)))
                                  if pd.notna(frame.iat[i, value_col]))
                years = re.findall(r"(?<!\d)20\d{2}(?!\d)", header)
                year_label = years[-1] if years else ""
                evaluate(pairs, sheet_name, "countries in rows", label_text, year_label)

        # Some chart source sheets put countries across a single row.
        for country_row in range(len(frame)):
            found = [(j, to_country(frame.iat[country_row, j])) for j in range(frame.shape[1])]
            found = [(j, name) for j, name in found if name]
            if len({name for _, name in found}) < 8:
                continue
            for value_row in range(len(frame)):
                if value_row == country_row:
                    continue
                pairs = [(name, rate(frame.iat[value_row, j])) for j, name in found]
                header = " ".join(str(frame.iat[value_row, j]) for j in range(min(8, frame.shape[1]))
                                  if pd.notna(frame.iat[value_row, j]))
                years = re.findall(r"(?<!\d)20\d{2}(?!\d)", header)
                year_label = years[-1] if years else ""
                evaluate(pairs, sheet_name, "countries in columns", label_text, year_label)

    if not candidates:
        raise ValueError(
            "OECD workbook received, but no 2026 country/rate table passed "
            "independent country-rate validation. Sheet shapes: " + "; ".join(notes[:8])
        )
    candidates.sort(key=lambda x: x[0], reverse=True)
    _, rates, sheet_name, orientation = candidates[0]
    # Reject conflicting equally plausible datasets instead of quietly choosing.
    for score, other, other_sheet, _ in candidates[1:]:
        if score < candidates[0][0] - 15:
            break
        common = set(rates) & set(other)
        if len(common) >= 8 and any(abs(rates[k] - other[k]) > 0.20 for k in common):
            raise ValueError(f"Conflicting OECD 2026 candidates: {sheet_name} vs {other_sheet}")
    return rates, (f"OECD Corporate Tax Statistics 2026, Figure 2.1; "
                   f"{len(rates)} countries; '{sheet_name}' ({orientation}); "
                   "checked against published France/Colombia/Hungary rates")


def load_oecd_tax() -> tuple[dict[str, float], str]:
    """Read the downloadable OECD 2026 published source data rather than 403 SDMX."""
    response = fetch(OECD_STATLINK_XLSX, timeout=35)
    if not response.content.startswith(b"PK"):
        raise ValueError("OECD statlink returned an HTML page or non-XLSX payload")
    return parse_oecd_statlink_xlsx(response.content)


@st.cache_data(ttl=3600, show_spinner=False)
def source_bundle():
    data, status = {}, {}
    for name, loader in (("betas", load_betas), ("spread", load_bbb_spread),
                         ("bonds", load_bond_yields), ("tax", load_oecd_tax)):
        try:
            data[name], status[name] = loader()
        except Exception as exc:
            data[name] = None
            status[name] = f"Unavailable: {type(exc).__name__}: {str(exc)[:160]}"
    return data, status, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def calculate(beta_u: float, tax: float, debt_share: float, erp: float,
              rf_us: float, rf_foreign: float, spread_us: float,
              spread_foreign_override: float | None = None) -> dict[str, float]:
    """All rates are decimals; uses exact gross-return currency conversion."""
    if not (0 <= tax < 1 and 0 <= debt_share < 1):
        raise ValueError("Tax must be in [0, 1), and debt share in [0, 1)")
    beta_e = beta_u * (1 + (1 - tax) * debt_share / (1 - debt_share))
    re_us = rf_us + beta_e * erp
    rd_us = rf_us + spread_us
    wacc_us = (1 - debt_share) * re_us + debt_share * rd_us * (1 - tax)
    factor = (1 + rf_foreign) / (1 + rf_us)
    re_fx = (1 + re_us) * factor - 1
    spread_fx = spread_us * factor if spread_foreign_override is None else spread_foreign_override
    rd_fx = rf_foreign + spread_fx
    wacc_fx = (1 - debt_share) * re_fx + debt_share * rd_fx * (1 - tax)
    return dict(beta_e=beta_e, factor=factor, re_us=re_us, re_fx=re_fx,
                rd_us=rd_us, rd_fx=rd_fx, spread_fx=spread_fx,
                debt_after_tax_us=rd_us * (1 - tax), debt_after_tax_fx=rd_fx * (1 - tax),
                wacc_us=wacc_us, wacc_fx=wacc_fx)


def percent(x):
    return f"{x * 100:.4f}%"


st.markdown("""<style>
.block-container {max-width: 1380px; padding-top: 1.6rem; padding-bottom: 3rem}
[data-testid="stSidebar"] {background: #f5f7fb}
[data-testid="stMetric"] {background: white; border: 1px solid #e3e9f2; border-radius: 14px; padding: 16px 20px; box-shadow: 0 2px 8px rgba(18,42,76,.035)}
[data-testid="stMetricLabel"] {color: #53657d}
[data-testid="stMetricValue"] {color: #123b70; font-weight: 750}
h1,h2,h3 {letter-spacing: -.025em}
h1 {color: #132d50}
[data-testid="stDownloadButton"] button {border-radius: 10px}
.hero {background: linear-gradient(115deg,#102d52,#225c91); border-radius: 18px; color: white; padding: 25px 30px; margin-bottom: 22px}
.hero h1 {color: white; margin: 0; font-size: 2.1rem}
.hero p {color: #dceaf8; margin: 8px 0 0}
.section-kicker {color: #53708f; font-size: .8rem; font-weight: 700; text-transform: uppercase; letter-spacing: .12em}
</style>""", unsafe_allow_html=True)
st.markdown('<div class="hero"><div class="section-kicker" style="color:#9fd0ff">FINANCIAL ANALYTICS · INTERNATIONAL PROJECTS</div><h1>International Cost of Capital</h1><p>Compare the cost of equity, borrowing and WACC across currencies with transparent assumptions.</p></div>', unsafe_allow_html=True)
st.caption("Compare a project's cost of equity, borrowing costs, and WACC in USD and a selected country's currency")
with st.sidebar:
    st.header("Data & sources")
    if st.button("🔄 Refresh external data", use_container_width=True):
        source_bundle.clear()
        st.rerun()

with st.spinner("Checking source availability…"):
    bundle, source_status, retrieved_at = source_bundle()

betas = bundle["betas"] or FALLBACK_BETAS
beta_source = "Live Damodaran" if bundle["betas"] else "Illustrative fallback — verify before submission"
industries = sorted(betas)
default_industry = next((x for x in industries if normalized(x) == normalized("Software (System & Application)")), None)
if default_industry is None:
    default_industry = next((x for x in industries if "software" in x.lower() and "system" in x.lower()), industries[0])

with st.sidebar:
    st.header("Project settings")
    industry = st.selectbox("Industry", industries, index=industries.index(default_industry))
    country = st.selectbox("Target country", list(COUNTRIES), index=list(COUNTRIES).index("United States"))
    currency = COUNTRIES[country][0]
    erp_pct = st.number_input("Equity risk premium (%)", min_value=0.0, max_value=50.0, value=6.5, step=0.25)
    debt_pct = st.slider("Target debt share (%)", 0.0, 95.0, 30.0, 1.0)
    tax_choice = st.radio("Corporate tax rate used in BOTH currencies", ["U.S. tax rate", "Selected-country tax rate"], horizontal=False)
    st.divider()
    st.subheader("Source values / manual overrides")
    st.caption("If a source fails, enter a verified value manually. Fallback figures are not live observations.")

    def numeric_override(label, auto, default, key, help_text=""):
        use_manual = st.checkbox(f"Override {label}", value=auto is None, key=f"override_{key}")
        value = st.number_input(label, value=float(default if auto is None else auto),
                                min_value=0.0, max_value=100.0, step=0.1,
                                format="%.4f", key=f"number_{key}", disabled=not use_manual,
                                help=help_text)
        return (value if use_manual else auto), ("Manual" if use_manual else "Fetched")

    beta, beta_mode = numeric_override("Unlevered beta", betas[industry] if bundle["betas"] else None, betas[industry], "beta")
    us_tax_auto = (bundle["tax"] or {}).get("United States")
    foreign_tax_auto = (bundle["tax"] or {}).get(country)
    us_tax, us_tax_mode = numeric_override("U.S. corporate tax (%)", us_tax_auto, DEFAULT_US_TAX, "tax_us")
    foreign_tax, foreign_tax_mode = numeric_override(f"{country} corporate tax (%)", foreign_tax_auto,
                                                       DEFAULT_US_TAX if country == "United States" else 25.0, "tax_fx")
    us_yield_auto = (bundle["bonds"] or {}).get("United States")
    foreign_yield_auto = (bundle["bonds"] or {}).get(country)
    us_yield, us_yield_mode = numeric_override("U.S. 10-year yield (%)", us_yield_auto, 4.0, "rf_us")
    foreign_yield, foreign_yield_mode = numeric_override(f"{country} 10-year yield (%)", foreign_yield_auto,
                                                          4.0 if country == "United States" else 12.0, "rf_fx")
    # source_bundle stores each loader's returned value in data[name] and its
    # provenance text in status[name]. The spread is therefore a float, not a tuple.
    spread_data = bundle.get("spread")
    if isinstance(spread_data, (int, float, np.integer, np.floating)) and np.isfinite(spread_data):
        spread_auto = float(spread_data)
    elif isinstance(spread_data, (tuple, list)) and spread_data:
        # Backward-compatible with older cached/source structures.
        candidate = spread_data[0]
        spread_auto = float(candidate) if isinstance(candidate, (int, float)) and np.isfinite(candidate) else None
    else:
        spread_auto = None
    spread_us, spread_mode = numeric_override("USD BBB spread (percentage points)", spread_auto, 1.5, "spread_us")
    manual_fx_spread = st.checkbox("Override selected-currency BBB spread", value=False)
    fx_spread_pct = st.number_input("Selected-currency BBB spread (percentage points)",
                                    min_value=0.0, max_value=30.0, value=1.5, step=0.1,
                                    disabled=not manual_fx_spread)

if country == "United States":
    foreign_yield = us_yield
    foreign_tax = us_tax
    foreign_yield_mode = us_yield_mode
    foreign_tax_mode = us_tax_mode
    manual_fx_spread = False
selected_tax = us_tax if tax_choice == "U.S. tax rate" else foreign_tax
with st.sidebar:
    st.caption("Data status · β: " + beta_mode + " · U.S. tax: " + us_tax_mode + " · Local tax: " + foreign_tax_mode + " · U.S. yield: " + us_yield_mode + " · Local yield: " + foreign_yield_mode + " · BBB spread: " + spread_mode)
# Clearly flag stale/fallback values instead of treating them as current facts.
missing = [name for name, val in bundle.items() if val is None]
if missing:
    st.warning("Some external sources could not be verified: " + ", ".join(missing) +
               ". Review the manual values and source diagnostics before using the outputs for a decision.")
if country != "United States" and abs(us_yield - foreign_yield) < 0.00001:
    st.info("The U.S. and selected-country government yields are identical. Currency conversion is therefore 1.0000, so USD and local costs may coincide. Check your yields, especially if manual inputs are active.")
if missing:
    st.caption("Inputs from unavailable sources are MANUAL / ILLUSTRATIVE, not verified live market data. See sidebar overrides and diagnostics.")
if country != "United States" and currency == "USD":
    st.info("This country's project currency is USD; the two columns will use the same currency.")

inputs = [beta, us_tax, foreign_tax, us_yield, foreign_yield, spread_us]
if any(v is None for v in inputs):
    st.error("Provide all required inputs to calculate results.")
    st.stop()
if selected_tax >= 100:
    st.error("Corporate tax rate must be below 100%.")
    st.stop()

results = calculate(beta, selected_tax / 100, debt_pct / 100, erp_pct / 100,
                    us_yield / 100, foreign_yield / 100, spread_us / 100,
                    fx_spread_pct / 100 if manual_fx_spread else None)

st.markdown('<div class="section-kicker">01 / Capital cost comparison</div>', unsafe_allow_html=True)
st.subheader(f"{industry}  ·  {country}")
a, b = st.columns(2, gap="large")
with a:
    st.markdown("### 🇺🇸 USD financing")
    st.metric("Cost of equity", percent(results["re_us"]))
    st.metric("Pretax borrowing cost", percent(results["rd_us"]))
    st.metric("After-tax borrowing cost", percent(results["debt_after_tax_us"]))
    st.metric("WACC", percent(results["wacc_us"]))
with b:
    st.markdown(f"### {currency} financing · {country}")
    st.metric("Cost of equity", percent(results["re_fx"]))
    st.metric("Pretax borrowing cost", percent(results["rd_fx"]))
    st.metric("After-tax borrowing cost", percent(results["debt_after_tax_fx"]))
    st.metric("WACC", percent(results["wacc_fx"]))

st.markdown("#### WACC comparison")
import plotly.graph_objects as go
fig = go.Figure(go.Bar(x=["USD", currency + " · " + country], y=[results["wacc_us"] * 100, results["wacc_fx"] * 100],
                       text=[percent(results["wacc_us"]), percent(results["wacc_fx"])], textposition="outside",
                       marker_color=["#164c7e", "#18a3a0"]))
fig.update_layout(height=290, margin=dict(l=10,r=10,t=20,b=10), yaxis_title="Annual WACC (%)",
                  paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", showlegend=False)
st.plotly_chart(fig, use_container_width=True)
st.caption(f"Relevered equity beta: {results['beta_e']:.4f} | Selected tax rate: {selected_tax:.2f}% ({tax_choice}) | Debt: {debt_pct:.0f}% | ERP: {erp_pct:.2f}%")

with st.expander("📐 Methodology and assumptions", expanded=True):
    st.latex(r"\beta_E = \beta_U\left[1+(1-\tau)\frac{D}{E}\right],\quad \frac{D}{E}=\frac{d}{1-d}")
    st.latex(r"R_{E,USD}=R_{f,USD}+\beta_E ERP,\quad R_{D,USD}=R_{f,USD}+s_{USD}")
    st.latex(r"F=\frac{1+R_{f,FX}}{1+R_{f,USD}},\quad 1+R_{E,FX}=F(1+R_{E,USD})")
    st.latex(r"s_{FX}=F s_{USD}\quad\mathrm{(unless\ overridden)},\quad R_{D,FX}=R_{f,FX}+s_{FX}")
    st.latex(r"WACC=(1-d)R_E+dR_D(1-\tau)")
    st.write(f"Gross-return conversion factor: **{results['factor']:.6f}**. "
             "The project uses the same tax rate, debt share, and equity risk premium in both financing currencies. "
             "The debt and interest tax shield are assumed to have zero beta; interest deductions are fully usable. "
             "Government 10-year yields proxy risk-free rates, although they include sovereign, liquidity and term risk. "
             "No separate country equity risk premium is added. Currency conversion assumes equal real rates / relative PPP as a simplifying approximation. "
             "A local-currency borrowing-spread override breaks exact USD-to-local conversion consistency by design.")

st.markdown('<div class="section-kicker">02 / Industry benchmark</div>', unsafe_allow_html=True)
st.subheader("All-industry comparison")
rows = []
for name, b_u in sorted(betas.items()):
    r = calculate(float(b_u), selected_tax / 100, debt_pct / 100, erp_pct / 100,
                  us_yield / 100, foreign_yield / 100, spread_us / 100,
                  fx_spread_pct / 100 if manual_fx_spread else None)
    rows.append({"Industry": name, "Unlevered beta": round(float(b_u), 5),
                 "Relevered beta": round(r["beta_e"], 5),
                 "Cost of equity USD (%)": round(r["re_us"] * 100, 5),
                 f"Cost of equity {currency} (%)": round(r["re_fx"] * 100, 5),
                 "WACC USD (%)": round(r["wacc_us"] * 100, 5),
                 f"WACC {currency} (%)": round(r["wacc_fx"] * 100, 5)})
comparison = pd.DataFrame(rows)
st.dataframe(comparison, hide_index=True, use_container_width=True, height=340)
st.download_button("⬇ Download all-industry comparison (CSV)", comparison.to_csv(index=False).encode("utf-8-sig"),
                   "industry_cost_of_capital.csv", "text/csv")

summary = pd.DataFrame([{
    "Industry": industry, "Country": country, "Currency": currency,
    "ERP (%)": erp_pct, "Debt share (%)": debt_pct, "Tax rate (%)": selected_tax,
    "Tax selection": tax_choice, "Unlevered beta": beta, "Relevered beta": results["beta_e"],
    "USD government yield (%)": us_yield, "Local government yield (%)": foreign_yield,
    "USD BBB spread (pp)": spread_us, "Local BBB spread (pp)": results["spread_fx"] * 100,
    "USD cost of equity (%)": results["re_us"] * 100, f"{currency} cost of equity (%)": results["re_fx"] * 100,
    "USD pretax debt cost (%)": results["rd_us"] * 100, f"{currency} pretax debt cost (%)": results["rd_fx"] * 100,
    "USD after-tax debt cost (%)": results["debt_after_tax_us"] * 100,
    f"{currency} after-tax debt cost (%)": results["debt_after_tax_fx"] * 100,
    "USD WACC (%)": results["wacc_us"] * 100, f"{currency} WACC (%)": results["wacc_fx"] * 100,
    "Data retrieved UTC": retrieved_at,
}])
st.download_button("⬇ Download selected-project results (CSV)", summary.to_csv(index=False).encode("utf-8-sig"),
                   "project_cost_of_capital.csv", "text/csv")

st.markdown('<div class="section-kicker">03 / Data transparency</div>', unsafe_allow_html=True)
with st.expander("Data provenance and diagnostics", expanded=False):
    st.caption(f"Most recent fetch attempt: {retrieved_at}. A fetch timestamp is NOT the underlying observation/publication date.")
    for label, url, key in (("U.S. industry unlevered betas", BETAS_URL, "betas"),
                            ("BBB spread", RATINGS_URL, "spread"),
                            ("OECD statutory corporate tax rates (2026)", OECD_URL, "tax"),
                            ("Trading Economics 10-year government yields", BONDS_URL, "bonds")):
        st.markdown(f"**{label}:** [source]({url}) — {source_status[key]}")
    st.info("Data quality: Verify source observation dates and the exact OECD combined statutory tax definition. "
            "Web pages may block automated requests or change their structure. Manual values are explicitly labeled, "
            "and illustrative defaults must not be presented as the latest data. "
            "When an OECD/Trading Economics series cannot be parsed confidently, the app requires a reviewed manual value.")
