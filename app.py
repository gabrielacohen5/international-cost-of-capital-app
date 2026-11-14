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
OECD_URL = "https://www.oecd.org/en/publications/corporate-tax-statistics-2024_9c27d6e8-en/full-report/statutory-corporate-income-tax-rates_440f9286.html"
BONDS_URL = "https://tradingeconomics.com/bonds"
# OECD SDMX public CSV endpoint; dynamic data availability and dimension names can change.
OECD_API = "https://sdmx.oecd.org/public/rest/v1/data/OECD.CTP.TPS,DSD_CIT@DF_CIT,1.1/.A.."
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
    tables = pd.read_html(BytesIO(fetch(RATINGS_URL).content))
    for df in tables:
        for _, row in df.iterrows():
            cells = [str(v) for v in row.tolist()]
            if not any(re.search(r"\b(?:Baa2|BBB)\b", x, re.I) for x in cells):
                continue
            # Damodaran ratings table: spread generally follows rating; find explicitly labeled spread column.
            cols = [normalized(c) for c in df.columns]
            candidates = [i for i, c in enumerate(cols) if "spread" in c]
            for i in candidates:
                value = parse_number(row.iloc[i])
                if value is not None and 0 < value < 20:
                    return value, "Damodaran ratings table: BBB/Baa2 spread (%)"
    raise ValueError("BBB spread not unambiguously located; enter manual spread")


def load_bond_yields() -> tuple[dict[str, float], str]:
    html = fetch(BONDS_URL).text
    tables = pd.read_html(BytesIO(html.encode()))
    result: dict[str, float] = {}
    for table in tables:
        cols = [normalized(c) for c in table.columns]
        country_idx = next((i for i, c in enumerate(cols) if c in ("country", "name")), None)
        yield_idx = next((i for i, c in enumerate(cols) if c in ("yield", "last", "yield10y")), None)
        if country_idx is None or yield_idx is None:
            continue
        for _, row in table.iterrows():
            name = str(row.iloc[country_idx]).strip()
            val = parse_number(row.iloc[yield_idx])
            if val is not None and -10 < val < 100:
                for country in COUNTRIES:
                    if normalized(name) == normalized(country) or normalized(name) == normalized(country + " 10Y"):
                        result[country] = val
    if not result:
        raise ValueError("Bond yield table unavailable or its structure changed")
    return result, "Trading Economics 10-year bond table (retrieval timestamp; quote dates may differ)"


def load_oecd_tax() -> tuple[dict[str, float], str]:
    # Explicitly filter for combined statutory corporate income tax, not effective tax or federal-only rates.
    response = requests.get(OECD_API, params={"format": "csvfilewithlabels", "startPeriod": "2023"}, timeout=25,
                            headers={"Accept": "text/csv"})
    response.raise_for_status()
    df = pd.read_csv(BytesIO(response.content), low_memory=False)
    col = {normalized(c): c for c in df.columns}
    country_col = next((col[k] for k in ("referencearea", "refarea", "country") if k in col), None)
    value_col = next((col[k] for k in ("obsvalue", "value") if k in col), None)
    year_col = next((col[k] for k in ("timeperiod", "year") if k in col), None)
    if not all((country_col, value_col, year_col)):
        raise ValueError("OECD dataset schema changed; manually supply statutory rate")
    # OECD dataset has multiple tax measures. Never silently choose the first series.
    measure_cols = [c for c in df.columns if any(x in normalized(c) for x in ("measure", "taxrate", "taxtype", "indicator"))]
    if not measure_cols:
        raise ValueError("Cannot verify combined statutory rate measure in OECD response")
    mask = pd.Series(False, index=df.index)
    for c in measure_cols:
        mask |= df[c].astype(str).str.contains("combined statutory|combined corporate income tax|combined cit", case=False, regex=True, na=False)
    df = df.loc[mask].copy()
    if df.empty:
        raise ValueError("Combined statutory tax series not found in OECD response")
    df["_year"] = pd.to_numeric(df[year_col], errors="coerce")
    df["_value"] = pd.to_numeric(df[value_col], errors="coerce")
    df = df.dropna(subset=["_year", "_value"]).sort_values("_year")
    result = {}
    for country in COUNTRIES:
        subset = df[df[country_col].astype(str).map(normalized) == normalized(country)]
        if not subset.empty:
            result[country] = float(subset.iloc[-1]["_value"])
    if not result:
        raise ValueError("Country names/codes could not be matched to OECD tax series")
    return result, f"OECD combined statutory CIT (latest matching year: {int(df['_year'].max())})"


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


st.title("🌐 International Cost of Capital")
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
    spread_auto = bundle["spread"][0] if bundle["spread"] else None
    spread_us, spread_mode = numeric_override("USD BBB spread (percentage points)", spread_auto, 1.5, "spread_us")
    manual_fx_spread = st.checkbox("Override selected-currency BBB spread", value=False)
    fx_spread_pct = st.number_input("Selected-currency BBB spread (percentage points)",
                                    min_value=0.0, max_value=30.0, value=1.5, step=0.1,
                                    disabled=not manual_fx_spread)

selected_tax = us_tax if tax_choice == "U.S. tax rate" else foreign_tax
# Clearly flag stale/fallback values instead of treating them as current facts.
missing = [name for name, val in bundle.items() if val is None]
if missing:
    st.warning("Some external sources could not be verified: " + ", ".join(missing) +
               ". Review the manual values and source diagnostics before using the outputs for a decision.")
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

st.subheader(f"Results · {industry} · {country}")
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

st.subheader("Data provenance and diagnostics")
st.caption(f"Most recent fetch attempt: {retrieved_at}. A fetch timestamp is NOT the underlying observation/publication date.")
for label, url, key in (("U.S. industry unlevered betas", BETAS_URL, "betas"),
                        ("BBB spread", RATINGS_URL, "spread"),
                        ("OECD statutory corporate tax rates", OECD_URL, "tax"),
                        ("Trading Economics 10-year government yields", BONDS_URL, "bonds")):
    st.markdown(f"**{label}:** [source]({url}) — {source_status[key]}")
st.info("Data quality: Verify source observation dates and the exact OECD combined statutory tax definition. "
        "Web pages may block automated requests or change their structure. Manual values are explicitly labeled, "
        "and illustrative defaults must not be presented as the latest data. "
        "When an OECD/Trading Economics series cannot be parsed confidently, the app requires a reviewed manual value.")
