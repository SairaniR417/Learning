"""Shared browser check includes the Pine RSI scanner, oscillator and settings.

Serve frontend/dist/market-desk/browser on 4309 and isolated Chrome CDP on 9347.
"""
import asyncio
from option_analysis_browser_smoke import main

if __name__ == '__main__':
    asyncio.run(main())
