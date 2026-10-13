"""Package CLI: preserve scan flags and add `python -m stock_scanner lookup`."""
from stock_scanner.run_scanner import main

if __name__ == '__main__':
    raise SystemExit(main())
