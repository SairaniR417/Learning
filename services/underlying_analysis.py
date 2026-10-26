"""Index and listed commodity-futures data for the shared strategy workspace."""
from fastapi import HTTPException
from services import option_analysis, option_market, stock_analysis


async def analyze(request, token, key, timeframe='5m', atr_multiplier=1.5,
                  rsi_settings=None, sutradhar_settings=None, suryavanshi_settings=None,
                  golden_settings=None):
    await option_market.require_key(key)
    items = (await option_market.underlyings(key.startswith('MCX_FO|')))['underlyings']
    metadata = next((item for item in items if item['key'] == key and item['group'] in {'Indices', 'Commodities'}), None)
    if metadata is None:
        raise HTTPException(400, 'Select a listed index or commodity futures contract.')
    intervals = {frame: interval for interval, frame in stock_analysis.FRAMES.items()}
    data_warnings = []

    async def load_frame(frame):
        history = await option_analysis.history(request, token, key, intervals[frame])
        if history.get('invalidCandles'):
            data_warnings.append(f'{frame} history excludes invalid provider candles.')
        completed = [dict(row, developing=False) for row in history['candles']]
        forming = [dict(row, developing=True) for row in history.get('formingCandles', [])]
        rows = sorted(completed + forming, key=lambda row: row['timestamp'])[-1000:]
        return dict(candles=[dict(row, timestamp=row['timestamp'].isoformat()) for row in rows],
                    warning=None, staleData=False)

    result = await stock_analysis._analyze(key, timeframe, atr_multiplier, rsi_settings,
        sutradhar_settings, suryavanshi_settings, golden_settings,
        load_frame=load_frame, metadata=metadata,
        instrument_label='Futures' if metadata['group'] == 'Commodities' else 'Index',
        continuous_futures=metadata['group'] == 'Commodities')
    result['warnings'].extend(data_warnings)
    if metadata['group'] == 'Commodities':
        result['warnings'].append('Prices belong to the selected futures expiry, not a continuous futures series.')
    return result
