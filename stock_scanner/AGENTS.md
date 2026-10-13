# Stock Scanner Development Rules

1. Read `README.md` and `docs/` before modifying strategy logic.

2. This is a standalone daily/weekly stock scanner. Do not modify or depend on the intraday trading engine.

3. Technical calculations must be causal. Never use future candles when evaluating a historical signal.

4. Completed weekly candles must be used for historical evaluation. Partial current weeks must not introduce lookahead.

5. Trend Score and Entry Quality are intentionally separate.

6. Do not modify Trend Score merely to force monotonic historical performance.

7. Candidate Score is the ranking mechanism.

8. Gemini is explanation-only and must never modify deterministic scanner results.

9. Do not optimize parameters against historical results without explicit instruction.

10. Run the full test suite after strategy changes.

11. Preserve V1.1 reproducibility when modifying V1.2+.

12. Before changing architecture, read `docs/ARCHITECTURE.md` and `docs/METHODOLOGY.md`.
