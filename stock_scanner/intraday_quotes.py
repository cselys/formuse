"""Quote-only Yahoo transport. Cookies, crumb and responses live in memory only."""
import http.cookiejar
import json
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener


class YahooQuotes:
    """Batch the same Yahoo quote endpoint used by yfinance, without its caches.

    No chart/history endpoint, bid/ask substitution, or disk-backed session.
    Yahoo's unofficial endpoint can reject authentication or throttle requests.
    """

    def __init__(self, batch_size=50, attempts=3, delay=1.0, timeout=15,
                 sleep=time.sleep):
        if batch_size < 1 or attempts < 1 or delay < 0 or timeout <= 0:
            raise ValueError('Invalid quote transport limits')
        self.batch_size, self.attempts = batch_size, attempts
        self.delay, self.timeout, self.sleep = delay, timeout, sleep
        self.opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.crumb = None
        self.request_stage = 'quote retrieval'

    def _get(self, url):
        request = Request(url, headers={'User-Agent': 'Mozilla/5.0',
                                       # Authentication returns HTML/plain text, not JSON.
                                       'Accept': '*/*'})
        with self.opener.open(request, timeout=self.timeout) as response:
            return response.read().decode('utf-8')

    def _authenticate(self):
        self.request_stage = 'cookie authentication'
        try:
            self._get('https://fc.yahoo.com')
        except HTTPError as exc:
            if exc.code != 404:  # This cookie endpoint commonly returns 404.
                raise
            exc.close()
        self.request_stage = 'crumb authentication'
        crumb = self._get('https://query1.finance.yahoo.com/v1/test/getcrumb').strip()
        if not crumb or '<' in crumb or len(crumb) > 100:
            raise ValueError('Yahoo authentication unavailable')
        self.crumb = crumb

    def _batch(self, symbols):
        if self.crumb is None:
            self._authenticate()
        params = urlencode({'symbols': ','.join(symbols), 'formatted': 'false',
                            'crumb': self.crumb})
        self.request_stage = 'quote retrieval'
        try:
            payload = json.loads(self._get(
                'https://query1.finance.yahoo.com/v7/finance/quote?' + params))
        except HTTPError as exc:
            if exc.code in (401, 403):
                self.crumb = None
            raise
        response = payload['quoteResponse']
        if response.get('error') or not isinstance(response.get('result'), list):
            raise ValueError('Yahoo quote response unavailable')
        return response['result']

    def fetch(self, symbols):
        quotes, failures = {}, {}
        symbols = sorted(set(symbols))
        for offset in range(0, len(symbols), self.batch_size):
            batch = symbols[offset:offset + self.batch_size]
            if offset:
                self.sleep(self.delay)
            for attempt in range(self.attempts):
                try:
                    rows = self._batch(batch)
                    for row in rows:
                        if isinstance(row, dict) and row.get('symbol') in batch:
                            quotes[row['symbol']] = row
                    break
                except Exception as exc:
                    # Do not expose request URLs containing authentication crumbs.
                    detail = f'HTTP {exc.code}' if isinstance(exc, HTTPError) else type(exc).__name__
                    reason = f'Quote request failed during {self.request_stage} ({detail})'
                    if isinstance(exc, HTTPError):
                        exc.close()
                    if attempt + 1 == self.attempts:
                        failures.update(dict.fromkeys(batch, reason))
                    else:
                        self.sleep(self.delay * 2 ** attempt)
            for symbol in batch:
                if symbol not in quotes:
                    failures.setdefault(symbol, 'Provider returned no quote')
        return quotes, failures
