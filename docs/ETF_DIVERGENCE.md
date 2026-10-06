# ETF_DIVERGENCE.md

## ETF / Basket divergence (spec section 17)

### Definition

The ETF divergence compares a theme's equal-weight basket (of its constituent stocks) against a market-capitalization-weighted ETF proxy.

```text
Divergence = ETF Return - Basket Return   (in percentage points)
```

- **ETF Return**: the ETF's return `(price - prev_close) / prev_close * 100`
- **Basket Return**: the theme's equal-weight average return `(average_return)` — this is NOT the price-weighted index return
- **Divergence**: `ETF Return - Basket Return` in pp

### Key rules (spec 17)

- The ETF is **NEVER** counted as one of the constituent stocks in breadth calculations
- The basket return is the theme's `average_return` (arithmetic mean of `change_vs_previous_close` across valid constituents)
- The ETF ticker is listed in the theme's `etf` field in `config/themes.yaml`
- If the ETF has no intraday data or no previous close, the divergence entry shows `—` for all fields

### Display in the UI

- Shown in the **ETF / BASKET DIVERGENCE** section (sidebar-toggleable)
- Table columns: Theme, ETF, ETF Return, Basket Return, Divergence (pp)
- Each row is color-coded: green if divergence > 0, red if divergence < 0, muted if `—`
- Caption: *"Informational only — NOT a trading recommendation"*

### Example

```text
Semiconductor

ETF: SMH     ETF Return: +1.8%     Basket Return: +1.5%     Divergence: -0.8%

Arithmetic means the theme's constituents average +1.5% while the SMH ETF (semiconductor index) is at +1.8%.
The -0.8 pp divergence indicates the ETF is outperforming the equal-weight basket.
```

### Available ETF mappings (from config/themes.yaml)

| Theme          | ETF Ticker(s) |
|----------------|---------------|
| Semiconductor  | SMH, SOXX     |
| AI / Compute   | SMH           |
| Nuclear        | URA           |
| Uranium        | URA           |
| Solar          | TAN           |
| Clean Energy   | ICLN, QCLN    |
| Oil & Gas      | XLE, XOP      |
| Natural Gas    | XOP           |
| Power / Utilities | XLU         |
| Biotech        | XBI, IBB      |
| Pharmaceuticals| XPH           |
| Defense / Aerospace | ITA       |
| Lithium        | LITH          |
| Copper / Metals| CPER          |

Note: Not all themes have ETF mappings. Those without are simply omitted from the ETF divergence section.