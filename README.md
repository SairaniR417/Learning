eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiI4Q0JGN0YiLCJqdGkiOiI2YWMzYmUyODc3YjdjMTI5OTk5MDNkNmUiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6ZmFsc2UsImlzRXh0ZW5kZWQiOnRydWUsImlhdCI6MTc5MTIxMzA5NiwiaXNzIjoidWRhcGktZ2F0ZXdheS1zZXJ2aWNlIiwiZXhwIjoxODIyNzczNjAwfQ.c0zXYeqOABiRA-f7wJzBumLySdnOPxgZndrpoAtdxq4
 
 
 # Market Desk

A personal market dashboard built with Angular and FastAPI. Upstox supplies live LTP quotes and historical NSE candles. API secrets and access tokens stay on the Python server.

## Requirements

- Python 3.10 or newer
- Node.js 20.19 or newer
- An approved Upstox account and developer app with its redirect URI set to `http://localhost:4200/oauth/callback`

## Run locally

1. Copy `.env.example` to `.env` and fill in `UPSTOX_CLIENT_ID` and `UPSTOX_CLIENT_SECRET` from the Upstox developer app. Register `http://localhost:4200/oauth/callback` as the redirect URL in that app.
2. In a terminal, install and run the API:

   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   uvicorn main:app --reload --port 8000
   ```

3. In a second terminal, install and run Angular:

   ```powershell
   cd frontend
   npm install
   npm start
   ```

4. Open `http://localhost:4200` and choose either local NSE example without connecting, or **Connect Upstox** to request other instruments and intervals.

Upstox V3 historical data provides minute/hour candles from January 2022 and daily/weekly/monthly candles from January 2000, subject to interval-specific maximum query ranges. The local Reliance sample is sourced from Yahoo Finance historical chart data and is stored in `reliance_nse_daily.csv`; its daily OHLCV values are used for offline indicator testing. Upstox access tokens are held in server memory and expire daily, so reconnect after restarting the API or when the token expires. A public deployment needs HTTPS, per-user sessions, and deployment-specific redirect URI configuration; this starter is for a single local user.

## Instrument analysis

Choose a cash equity or MCX futures market, search an instrument after connecting Upstox, and its history opens in a focused full-screen chart. The chart starts with EMA 9, 20, 50, and 200 overlays. The status panel checks `close > EMA 9 > EMA 20 > EMA 50 > EMA 200`, marks a newly aligned bullish entry, and reports bearish, mixed, or insufficient-history states. Use at least 200 candles for a complete EMA 200 setup. The local selector includes a Reliance bearish sample and an Adani Ports historical bullish-entry sample for testing the EMA rule without connecting.
