# International Cost of Capital App

A Python 3.12 / Streamlit application comparing a project's cost of equity, pretax and after-tax debt cost, and WACC in USD and the currency of a selected country.

## Run locally

```bash
python -m venv .venv
# macOS/Linux: source .venv/bin/activate
# Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
streamlit run app.py
```

## Deploy to Streamlit Community Cloud

1. Create a GitHub repository and upload `app.py`, `requirements.txt`, and `README.md` to its root.
2. In Streamlit Community Cloud, select **Create app**, connect the repository and choose `app.py` as the entry point.
3. Set the Python version to **3.12** in deployment settings if available, then deploy.
4. Check **Data provenance and diagnostics** in the deployed app and enter verified manual values for any source that cannot be retrieved.

## Features

- Select industry and country; initial settings: Software (System & Application), United States, U.S. tax rate, ERP 6.5%, debt share 30%.
- Refresh external data (cached for one hour between refreshes).
- Independently override unlevered beta, U.S. and local statutory corporate tax rates, U.S. BBB credit spread, and both 10-year government yields.
- Optionally override local-currency BBB spread; otherwise derive it with the currency conversion factor.
- Choose whether to apply U.S. or selected-country corporate tax rate to **both** financing scenarios.
- Compare USD and local results side by side, inspect formulas and all-industry results, and download CSV files.

## Source links and data integrity

| Variable | Primary source | Retrieval approach |
|---|---|---|
| U.S. industry unlevered beta | [Damodaran U.S. beta workbook](https://pages.stern.nyu.edu/~adamodar/pc/datasets/betas.xls) | Download XLS, locate Industry Name and Unlevered Beta columns |
| BBB/Baa2 USD spread | [Damodaran ratings table](https://pages.stern.nyu.edu/adamodar/New_Home_Page/datafile/ratings.html) | Extract explicitly labeled BBB spread column; otherwise manual |
| Combined statutory corporate tax | [OECD corporate tax statistics](https://www.oecd.org/en/publications/corporate-tax-statistics-2024_9c27d6e8-en/full-report/statutory-corporate-income-tax-rates_440f9286.html) | Attempt OECD public SDMX CSV and identify combined statutory measure; otherwise manual |
| U.S. and local 10-year yields | [Trading Economics bonds](https://tradingeconomics.com/bonds) | Parse public HTML tables, if available; otherwise manual |

**Important:** The OECD SDMX endpoint and publisher HTML schemas can change. OECD's 2024 report is not necessarily the most recent available observation. The app never silently labels an unverified fallback as the latest value. The source panel shows retrieval errors and retrieval time, but **retrieval time is not observation date**. Confirm the exact source publication/observation dates manually before submitting or relying on the model. The six fallback beta values and default manual yield/spread/tax numbers are **illustrative only**, not sourced current market observations. Country availability is restricted to the countries listed in `COUNTRIES`; extend that mapping for additional countries and their ISO currencies.

## Financial methodology

Let `d = D/(D+E)`, `tau` = selected corporate tax rate, `ERP` = equity risk premium, `s` = USD BBB borrowing spread, and `Rf` = 10-year government yield. Rates in the formulas below are decimals, not percentage points.

1. `D/E = d/(1-d)`
2. `beta_e = beta_u * [1 + (1-tau)*D/E]`
3. `Re_USD = Rf_USD + beta_e*ERP`
4. `Rd_USD = Rf_USD + s_USD`
5. `WACC_USD = (1-d)*Re_USD + d*Rd_USD*(1-tau)`
6. `F = (1+Rf_local)/(1+Rf_USD)`
7. `Re_local = (1+Re_USD)*F - 1`
8. `s_local = s_USD*F` by default (or user-provided local spread)
9. `Rd_local = Rf_local + s_local`
10. `WACC_local = (1-d)*Re_local + d*Rd_local*(1-tau)`

These match the supplied lecture-slide method: debt and interest tax shield have zero beta, the tax shield is usable, debt share is held fixed, the same tax rate applies in both currencies, and the local currency equity return is converted via gross government-yield ratios. No separate country equity premium is added. Government yields are only proxies for risk-free rates; relative PPP/equal real rates is a modeling approximation, not an exact identity for market expected FX changes. The formula for local debt spreads follows the slide's convention; it is not necessarily the only possible way to model credit spreads.

## Validation example (Colombia; illustrative slide inputs)

Inputs: `beta_u=0.80`, `d=30%`, `tau=35%`, `ERP=6.5%`, `Rf_USD=4%`, `Rf_COP=12%`, `s_USD=1.5 percentage points`.

Expected approximately:

| Output | USD | COP |
|---|---:|---:|
| Relevered equity beta | 1.022857 | 1.022857 |
| Cost of equity | 10.6486% | 19.1600% |
| Pretax cost of debt | 5.5000% | 13.6154% |
| After-tax cost of debt | 3.5750% | 8.8500% |
| WACC | 8.5265% | 16.0670% |

Note that the app defaults to the U.S. tax rate, not the slide's 35% example; to reproduce the example, override the tax rate to 35% and provide all example values manually. Results retain full precision internally and round for display.

## Limitations

- Public sites may change markup or block scraping; an API key is not required but reliable automated access is not guaranteed.
- The OECD SDMX API query may require updating to a current dataflow. If the measure cannot be identified safely, the app asks for a manual rate rather than picking an arbitrary OECD value.
- Source observations are not guaranteed to share a common as-of date. Check original publications.
- USD is also the target currency when United States is selected; both columns should match if the same input rates and no local-spread override are used.
- This is an educational capital-budgeting model, not investment advice.
