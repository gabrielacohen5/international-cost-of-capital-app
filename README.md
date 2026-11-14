# International Cost of Capital

A Streamlit dashboard for comparing a project's USD and local-currency cost of equity, debt and WACC. Designed for Python **3.12** and the class methodology.

## Deploy

1. Upload **app.py**, **requirements.txt** and **README.md** to the root of your GitHub repository, replacing the previous files.
2. In Streamlit Community Cloud, redeploy the app from the repository. Select Python 3.12 if the setting is available.
3. Use **Refresh external data** in the left sidebar. Inspect **Data provenance and diagnostics**.
4. Check that U.S. and local government yields differ when appropriate; validate the tax input and any manually provided values.

For local execution:

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

## Key improvements in v3

- **Trading Economics**: parses the public country-list 10-year yield table by individual HTML rows and validates that at least five countries, including the United States, have been identified; tries the `bonds` page as a secondary route. A blocked or changed website still requires manual input.
- **OECD**: replaces the previous failing SDMX endpoint with the OECD's **2026** published Figure 2.1 source workbook, linked by Statlink, and applies strict column validation to avoid confusing central with combined statutory rates. If the workbook layout changes or the publisher blocks downloads, the app tells users to provide a checked manual value. This is **not** a promise of unrestricted scraping.
- **Currency display**: explicitly warns when the U.S. and selected-country government yields are identical (conversion factor = 1, making results the same). For the United States as target, both scenarios are forced to use identical tax/yield inputs and the local spread override is ignored.
- **Source controls**: sidebar displays whether each input is fetched or manual. Failed sources remain clearly labelled, not silently presented as fresh observations.
- Keeps the v2 interface, side-by-side results, methodology, all-industry benchmark and CSV downloads.

## Sources

| Input | Source | URL |
|---|---|---|
| Industry unlevered beta | Aswath Damodaran, U.S. industries | https://pages.stern.nyu.edu/~adamodar/pc/datasets/betas.xls |
| BBB borrowing spread | Aswath Damodaran, large non-financial firms Baa2/BBB | https://pages.stern.nyu.edu/adamodar/New_Home_Page/datafile/ratings.html |
| Corporate tax rates | OECD Corporate Tax Statistics 2026, combined statutory rate | https://www.oecd.org/en/publications/corporate-tax-statistics-2026_73af6222-en/full-report/statutory-corporate-income-tax-rates_ce84abb9.html |
| Tax chart/source workbook | OECD Statlink Figure 2.1 | https://stat.link/mstq82 |
| Ten-year government yields | Trading Economics country listing | https://tradingeconomics.com/country-list/government-bond-10y |

**Important:** Tax years and bond quote dates are not necessarily aligned. The date a scrape runs is not the observation date. This project does not provide investment-grade pricing data. Data-provider websites may block requests from Streamlit hosting; in that case, verify the values at the original source and enter manual overrides.

## Controls and defaults

- Default industry: Software (System & Application); country: United States; ERP: 6.5%; target debt share: 30%; tax rate: U.S.
- The user can override unlevered beta, U.S. and local corporate tax, both ten-year government yields and USD BBB spread. Local BBB spread can be overridden separately or calculated automatically.
- **Manual defaults are illustrative, not verified latest quotes.** In particular, 21% is a U.S. federal-only tax fallback, **not the OECD combined statutory rate**.
- Selecting another country does **not** automatically switch tax: use the U.S./selected-country tax toggle. The same chosen rate is applied to both columns.

## Financial formulas

All returns, rates and spreads are decimals internally:

```
D/E = d / (1 - d)
beta_e = beta_u * (1 + (1 - tax) * D/E)
Re_USD = Rf_USD + beta_e * ERP
Rd_USD = Rf_USD + spread_USD
WACC_USD = (1-d)*Re_USD + d*Rd_USD*(1-tax)
F = (1 + Rf_local) / (1 + Rf_USD)
Re_local = (1 + Re_USD)*F - 1
spread_local = spread_USD*F          # unless manually overridden
Rd_local = Rf_local + spread_local
WACC_local = (1-d)*Re_local + d*Rd_local*(1-tax)
```

The class model assumes a zero-beta debt and interest tax shield, fully usable interest deductions, identical target financing mix and project tax rate across currencies, and no additional country equity premium. Government yields are imperfect proxies for risk-free rates; expected FX conversion is an approximate PPP/equal real-rate assumption.

## Numerical checks

Using the **illustrative Colombia slide** (beta 0.80; debt share 30%; tax 35%; ERP 6.5%; U.S. 10Y 4%; Colombia 10Y 12%; BBB spread 1.5 percentage points) yields:

| Measure | USD | COP |
|---|---:|---:|
| Cost of equity | 10.6486% | 19.1600% |
| Pretax debt cost | 5.5000% | 13.6154% |
| After-tax debt cost | 3.5750% | 8.8500% |
| WACC | **8.5265%** | **16.0670%** |

Automated local checks cover: code compilation, sample Trading Economics HTML table parsing, sample OECD Excel layout parsing, Colombia WACC, and the identical-currency formula. **Live network fetches and Streamlit Cloud operation were not verified in the build environment**, so inspect diagnostics after deployment.
