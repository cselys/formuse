# THEME_DEFINITIONS.md

All themes are defined in `config/themes.yaml` and are editable without touching Python code.

Each theme has: a ticker list, an optional ETF mapping, and a description. A stock may belong to multiple themes.

## How to read this file

- `tickers`: list of tickers that belong to this theme
- `etf`: optional ETF tickers for comparison (ETFs are NEVER counted as constituent stocks in breadth calculations)
- The count of constituent stocks is the number of configured tickers that have valid data

## Technology / AI

### Semiconductor
- **Constituent count:** 18
- **Symbols:** NVDA, AMD, AVGO, QCOM, MU, MRVL, TXN, ADI, INTC, AMAT, LRCX, KLAC, ASML, TSM, ON, MPWR, NXPI, ARM
- **ETF:** SMH, SOXX

### AI / Compute
- **Constituent count:** 11
- **Symbols:** NVDA, AMD, AVGO, MRVL, MU, ANET, DELL, SMCI, PLTR, ORCL, APP
- **ETF:** SMH

### Data Center
- **Constituent count:** 11
- **Symbols:** NVDA, AMD, AVGO, MRVL, ANET, VRT, DELL, SMCI, EQIX, DLR, NTNX
- **ETF:** (none)

### Optical / Photonics
- **Constituent count:** 5
- **Symbols:** LITE, COHR, CIEN, FN, AAOI
- **ETF:** (none)

### Networking
- **Constituent count:** 7
- **Symbols:** ANET, CSCO, AVGO, MRVL, CIEN, AST, FN
- **ETF:** (none)

### Memory
- **Constituent count:** 3
- **Symbols:** MU, WDC, STX
- **ETF:** (none)

### Semiconductor Equipment
- **Constituent count:** 9
- **Symbols:** AMAT, LRCX, KLAC, ASML, ACN, ONTO, VECO (ASMI, BESI removed — no pricing data)
- **ETF:** (none)

## Energy / Infrastructure

### Nuclear
- **Constituent count:** 8
- **Symbols:** CEG, VST, OKLO, SMR, LEU, BWXT, CCJ, UEC
- **ETF:** URA

### Uranium
- **Constituent count:** 5
- **Symbols:** CCJ, LEU, UEC, BTU, NK
- **ETF:** URA

### Solar
- **Constituent count:** 6
- **Symbols:** FSLR, ENPH, SEDG, NXT, RUN, ARRY
- **ETF:** TAN

### Clean Energy
- **Constituent count:** 6
- **Symbols:** ENPH, FSLR, SEDG, RUN, BE, EVA
- **ETF:** ICLN, QCLN

### Oil & Gas
- **Constituent count:** 13
- **Symbols:** XOM, CVX, COP, OXY, EOG, FANG, SLB, HAL, MPC, VLO, PSX, DIY, HES
- **ETF:** XLE, XOP

### Natural Gas
- **Constituent count:** 6
- **Symbols:** EQT, MRO, EOG, COP, KNSL, APA
- **ETF:** XOP

### Power / Utilities
- **Constituent count:** 14
- **Symbols:** NRG, VST, CEG, EIX, DUK, SO, XEL, AEP, PEG, D, SRE, NEE, WEC, TLN
- **ETF:** XLU

### Electrical Infrastructure
- **Constituent count:** 7
- **Symbols:** VRT, ETN, PWR, GE, NVT, POWI, HUBB
- **ETF:** (none)

## Healthcare

### Biotech
- **Constituent count:** 8
- **Symbols:** AMGN, GILD, REGN, VRTX, BIIB, MRNA, ALNY, ILMN
- **ETF:** XBI, IBB

### Pharmaceuticals
- **Constituent count:** 8
- **Symbols:** PFE, MRK, JNJ, LLY, ABBV, BMY, ABT, GSK
- **ETF:** XPH

### Medical Devices
- **Constituent count:** 7
- **Symbols:** BDX, ABT, ISRG, SYK, MDT, GEH, HWM
- **ETF:** (none)

## Other useful themes

### Defense / Aerospace
- **Constituent count:** 10
- **Symbols:** LMT, NOC, RTX, GD, LHX, BA, AVAV, TXT, GNRC, TKO
- **ETF:** ITA

### EV
- **Constituent count:** 6
- **Symbols:** TSLA, RIVN, NIO, LI, XPEV, BYDDY
- **ETF:** LITH

### Batteries
- **Constituent count:** 3
- **Symbols:** ALB, TSLA, SQM
- **ETF:** LITH

### Lithium
- **Constituent count:** 2
- **Symbols:** ALB, SQM
- **ETF:** LITH

### Copper / Metals
- **Constituent count:** 5
- **Symbols:** FCX, SCCO, MO, NEM, GOLD
- **ETF:** CPER

### Steel
- **Constituent count:** 3
- **Symbols:** CLF, STLD, CM
- **ETF:** (none)

### Financials
- **Constituent count:** 10
- **Symbols:** JPM, BAC, WFC, C, GS, MS, BLK, SCHW, AXP, V
- **ETF:** XLF

### Regional Banks
- **Constituent count:** 9
- **Symbols:** PNC, HBAN, CINF, KEY, WSBC, ONB, FNB, RF, TIF
- **ETF:** KBE

### Homebuilders
- **Constituent count:** 7
- **Symbols:** DHI, MTH, LEN, PH, NVR, MHO, TOL
- **ETF:** XHB

### Retail
- **Constituent count:** 9
- **Symbols:** WMT, COST, AMZN, TJX, LOW, ORLY, HD, M, NKE
- **ETF:** XRT

### Travel / Airlines
- **Constituent count:** 8
- **Symbols:** DAL, UAL, LUV, AAL, RCL, CCL, WYNN, MGM
- **ETF:** JETS

### Cybersecurity
- **Constituent count:** 9
- **Symbols:** CRWD, ZS, S, PANW, TENB, CHKP, OKTA, FTNT, WCC
- **ETF:** (none)

### Cloud Software
- **Constituent count:** 10
- **Symbols:** CRM, NOW, SNOW, MDB, DDOG, TEAM, WDAY, NET, ORCL, PLTR
- **ETF:** (none)