# Market Desk

A personal market dashboard built with Angular and FastAPI. Kite Connect supplies historical NSE candles; Upstox remains available for live LTP quotes. Broker API secrets and access tokens stay on the Python server.

## Requirements

- Python 3.10 or newer
- Node.js 20.19 or newer
- A Kite Connect developer app with its redirect URI set to `http://localhost:4200/kite/callback`
- Kite Connect's paid Connect subscription for historical candles; the free Personal tier does not include historical market data

## Run locally

1. Copy `.env.example` to `.env` and fill in `KITE_API_KEY` and `KITE_API_SECRET` from the Kite developer app. Register `http://localhost:4200/kite/callback` as the redirect URL in the Kite developer portal. Upstox credentials are only needed when enabling its separate live-quote flow.
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

4. Open `http://localhost:4200` and select **Connect Kite** in the Backdated candles section.

The Kite developer app's callback URL must exactly match `http://localhost:4200/kite/callback`. You can preview the chart and table with the **Preview sample data** button without connecting Kite; that generated data is clearly labeled synthetic and is not market data. For real OHLCV history, search an NSE stock or index, choose dates and a candle interval, then load the data through Kite Connect. Access tokens are kept in server memory and expire daily, so reconnect after restarting the API or when a token expires. A public deployment needs HTTPS, per-user sessions, and deployment-specific redirect URI configuration; this starter is for a single local user.