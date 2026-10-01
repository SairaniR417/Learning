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

4. Open `http://localhost:4200` and select **Preview sample data** to try the history panel without connecting, or **Connect Upstox** to use real market data.

Upstox V3 historical data provides minute/hour candles from January 2022 and daily/weekly/monthly candles from January 2000, subject to interval-specific maximum query ranges. Preview candles are synthetic and are not actual or delayed market data. Upstox access tokens are held in server memory and expire daily, so reconnect after restarting the API or when the token expires. A public deployment needs HTTPS, per-user sessions, and deployment-specific redirect URI configuration; this starter is for a single local user.