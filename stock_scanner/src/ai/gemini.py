"""
Google Gemini AI explanation layer for stock_scanner.
Uses google-genai SDK. Gemini is explanation only and NEVER modifies technical scores or classifications.
"""

import os
import logging
from typing import Optional
from pydantic import BaseModel, Field
try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None

logger = logging.getLogger("stock_scanner.ai")


class GeminiExplanation(BaseModel):
    summary: str = Field(description="Concise summary of the stock's current technical setup.")
    strengths: list[str] = Field(description="Key technical strengths.")
    risks: list[str] = Field(description="Key technical risks or warning signs.")
    what_to_watch: list[str] = Field(description="Key price levels or technical triggers to watch.")
    is_extended: bool = Field(description="Whether the stock is extended from moving averages.")
    intraday_monitoring_worthy: bool = Field(description="Whether the setup deserves further intraday options monitoring.")


class GeminiExplainer:
    """Wrapper for Google GenAI Gemini explanation integration."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self.client = None

        if genai and self.api_key:
            try:
                self.client = genai.Client(api_key=self.api_key)
                logger.info(f"Gemini client initialized with model: {self.model}")
            except Exception as e:
                logger.warning(f"Failed to initialize Gemini client: {e}")

    def explain_symbol(self, symbol: str, category: str, state: str, scores: dict, indicators: dict) -> Optional[GeminiExplanation]:
        """
        Generate explanation for a stock scan result using Gemini structured output.
        Returns None if Gemini is not configured or fails.
        """
        if not self.client:
            return None

        prompt = f"""
You are an expert quantitative stock market analyst.
Analyze the following deterministic technical scanner results for {symbol} (Category: {category}):

State Classification: {state}
Scores:
- Trend Score: {scores.get('trend_score')} / 100
- Bottom Score: {scores.get('bottom_score')} / 100
- Reversal Score: {scores.get('reversal_score')} / 100
- Setup Quality: {scores.get('setup_quality')} / 100

Key Indicators:
- Daily Close: {indicators.get('daily', {}).get('close')}
- Daily EMA20: {indicators.get('daily', {}).get('ema20')} (Distance: {indicators.get('daily', {}).get('distance_ema20')}%)
- Daily RSI: {indicators.get('daily', {}).get('rsi')}
- ATR %: {indicators.get('daily', {}).get('atr_pct')}%
- Volume Ratio: {indicators.get('daily', {}).get('volume_ratio')}
- Relative Strength (20d): {indicators.get('relative_strength', {}).get('rs_20d')}%

Provide a concise, professional technical explanation adhering strictly to the structured schema.
DO NOT modify any scores or classifications.
"""

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=GeminiExplanation,
                    temperature=0.2
                ),
            )
            if response and response.text:
                import json
                data = json.loads(response.text)
                return GeminiExplanation(**data)
        except Exception as e:
            logger.error(f"Gemini explanation failed for {symbol}: {e}")

        return None
