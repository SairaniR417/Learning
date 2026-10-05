import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from main import app


class DrishtiApiTests(unittest.TestCase):
    def test_ema_endpoint_uses_upstox_candles(self):
        from datetime import date, timedelta

        candles = []
        start = date(2025, 1, 1)
        for index in range(251):
            close = 100 + index
            candles.append({
                "timestamp": f"{start + timedelta(days=index)}T00:00:00+0530",
                "open": close - 1,
                "high": close + 1,
                "low": close - 2,
                "close": close,
                "volume": 1000 + index,
            })
        with patch("main.historical_candles", new=AsyncMock(return_value={"candles": candles})) as history:
            response = TestClient(app).get(
                "/api/drishti/ema-alignment",
                params={
                    "symbol": "NIFTY 50",
                    "instrument_key": "NSE_INDEX|Nifty 50",
                    "from": "2025-01-01",
                    "to": "2026-01-01",
                },
            )
        self.assertEqual(response.status_code, 200)
        history.assert_awaited_once()
        result = response.json()
        for field in ("symbol", "exchange", "timeframe", "asOf", "ema", "conditions",
                      "bullishAlignment", "status", "alignedSince", "transitionIndex",
                      "transitionTimestamp", "candlesAnalyzed"):
            self.assertIn(field, result)
        self.assertEqual(result["minimumHistory"], 200)
        self.assertEqual(result["recommendedHistory"], 400)
        self.assertIn(result["historyStatus"], {"INSUFFICIENT", "MINIMUM_ONLY", "SUFFICIENT"})
        self.assertEqual(result["candlesAnalyzed"], 251)
    def test_general_chat_forwards_conversation_and_returns_sources(self):
        answer = {"answer": "A useful answer.", "sources": [{"title": "Example", "url": "https://example.com"}]}
        with patch("main.openai_api_key", "test-key"), patch(
            "main.answer_question", new=AsyncMock(return_value=answer)
        ) as ask:
            response = TestClient(app).post("/api/drishti/chat", json={
                "messages": [{"role": "user", "content": "Explain compound interest."}]
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), answer)
        ask.assert_awaited_once_with(
            [{"role": "user", "content": "Explain compound interest."}],
            api_key="test-key",
            model="gpt-6-astra",
        )

    def test_general_chat_reports_missing_server_api_key(self):
        with patch("main.openai_api_key", ""):
            response = TestClient(app).post("/api/drishti/chat", json={
                "messages": [{"role": "user", "content": "Hello"}]
            })
        self.assertEqual(response.status_code, 503)
        self.assertIn("OPENAI_API_KEY", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
