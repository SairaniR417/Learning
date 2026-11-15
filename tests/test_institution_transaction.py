"""Deterministic tests of the observable pressure proxy, not institutional identity."""
from datetime import datetime, timedelta, timezone
from unittest import TestCase, IsolatedAsyncioTestCase
from unittest.mock import patch, AsyncMock

import polars as pl

from scanner.strategies.institution_transaction import InstitutionTransactionStrategy, pressure_view

NOW = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)
KEY = 'NSE_EQ|TEST'
META = {KEY: dict(symbol='TEST', name='Test company', exchange='NSE')}


def candle(stamp, close, volume=1000, up=True):
    return dict(instrument_key=KEY, timestamp=stamp, open=close-.6 if up else close+.6,
                high=close+.1 if up else close+2, low=close-2 if up else close-.1,
                close=close, volume=volume)


def daily(up=True):
    start = datetime(2026, 10, 15, tzinfo=timezone.utc)
    rows = [candle(start+timedelta(days=i),100+i if up else 200-i,up=up) for i in range(30)]
    rows[-1]['volume'] = 3000
    return rows


def hourly(up=True):
    start = datetime(2026, 10, 30, 3, 45, tzinfo=timezone.utc)
    rows = [candle(start+timedelta(days=day,hours=slot),100+day+slot if up else 200-day-slot,
                   volume=1000 if slot==6 else 10000,up=up) for day in range(15) for slot in range(7)]
    rows[-1]['volume'] = 3000
    return rows


class InstitutionTransactionTests(TestCase):
    def test_daily_buying_and_selling_with_latest_excluded_from_volume_baseline(self):
        for up, state in [(True,'BUYING'),(False,'SELLING')]:
            view = pressure_view(daily(up),'1d',now=NOW)
            self.assertEqual(view['state'],state)
            self.assertEqual(view['relativeVolume'],3)
            self.assertGreater(view['resistance'],view['support'])
            self.assertIsNone(view['vwap'])

    def test_hourly_uses_same_slot_not_all_other_hourly_volumes(self):
        view = pressure_view(hourly(),'1h',now=NOW)
        self.assertEqual(view['relativeVolume'],3)
        self.assertIn('14 prior sessions',view['volumeBasis'])
        self.assertEqual(view['state'],'BUYING')
        self.assertIsNotNone(view['vwap'])

    def test_missing_hourly_open_or_volume_baseline_cannot_confirm_pressure(self):
        rows = hourly()
        day = rows[-1]['timestamp'].date()
        no_open = [r for r in rows if not (r['timestamp'].date()==day and r['timestamp'].hour==3)]
        self.assertEqual(pressure_view(no_open,'1h',now=NOW)['state'],'UNAVAILABLE')
        self.assertEqual(pressure_view(rows[-28:],'1h',now=NOW)['state'],'UNAVAILABLE')

    def test_invalid_zero_volume_short_and_developing_history(self):
        self.assertEqual(pressure_view([],'1d',now=NOW)['state'],'UNAVAILABLE')
        rows=daily();rows[-1]['close']=0
        self.assertEqual(pressure_view(rows,'1d',now=NOW)['state'],'UNAVAILABLE')
        rows=daily()
        for row in rows: row['volume']=0
        self.assertEqual(pressure_view(rows,'1d',now=NOW)['state'],'UNAVAILABLE')
        rows=hourly();before=pressure_view(rows,'1h',now=NOW)
        rows += [candle(NOW,1000,volume=100000)]
        self.assertEqual(pressure_view(rows,'1h',now=NOW),before)

    def test_duplicate_candles_and_old_history(self):
        rows=hourly()
        self.assertEqual(pressure_view(rows,'1h',now=NOW),pressure_view(rows+[rows[-1]],'1h',now=NOW))
        self.assertTrue(pressure_view(rows,'1h',now=NOW+timedelta(days=10))['oldData'])

    def test_last_partial_hour_finishes_at_exchange_close(self):
        rows = hourly()
        closed = datetime(2026,11,13,10,0,6,tzinfo=timezone.utc)
        self.assertEqual(pressure_view(rows,'1h',now=closed)['asOf'],rows[-1]['timestamp'].isoformat())
        before = closed - timedelta(minutes=1)
        self.assertEqual(pressure_view(rows,'1h',now=before)['asOf'],rows[-2]['timestamp'].isoformat())

    def run_strategy(self, daily_rows, hourly_rows, **params):
        with patch('scanner.strategies.institution_transaction.datetime',wraps=datetime) as clock:
            clock.now.return_value=NOW
            return InstitutionTransactionStrategy().run(pl.DataFrame(daily_rows) if daily_rows else pl.DataFrame(),META,
                dict(_timeframe='1d',_hourly_rows={KEY:hourly_rows},**params))

    def test_strategy_combines_views_without_claiming_institutional_identity(self):
        row=self.run_strategy(daily(),hourly())[0]
        self.assertEqual(row['status'],'BUYING PRESSURE')
        self.assertFalse(row['institutionalConfirmed'])
        self.assertEqual(row['disclosureStatus'],'Not checked')
        self.assertEqual(row['signal'],'WATCH')
        self.assertIn('NOT CHECKED',row['pressureExplanation'])
        self.assertIn('next retest',row['pressureExplanation'])
        self.assertAlmostEqual(row['changePct'],(129/128-1)*100)
        self.assertEqual(self.run_strategy(daily(),[])[0]['status'],'BUYING WATCH')
        self.assertEqual(self.run_strategy(daily(),hourly(False))[0]['status'],'MIXED PRESSURE')

    def test_missing_history_visible_and_filterable(self):
        self.assertEqual(self.run_strategy([],[])[0]['status'],'INSUFFICIENT HISTORY')
        self.assertEqual(self.run_strategy([],[],include_waiting=False),[])


class InstitutionRegistryTests(IsolatedAsyncioTestCase):
    async def test_registry_loads_both_timeframes_and_versions_both_sources(self):
        from scanner.strategies.registry import StrategyRegistry
        async def load(frame, **kwargs): return pl.DataFrame(daily() if frame=='1d' else hourly())
        with patch('scanner.strategies.registry.get_all_active_instruments',AsyncMock(return_value=[dict(META[KEY],key=KEY)])), \
             patch('scanner.strategies.registry.get_candle_revision',AsyncMock(side_effect=[11,22])), \
             patch('scanner.strategies.registry.get_cached_strategy_result',AsyncMock(return_value=None)), \
             patch('scanner.strategies.registry.load_recent_candles_polars',AsyncMock(side_effect=load)) as loader, \
             patch('scanner.strategies.registry.save_strategy_result_cache',AsyncMock()) as save:
            response=await StrategyRegistry().execute_scan('institution_transaction',timeframe='1d')
            self.assertEqual({c.args[0] for c in loader.await_args_list},{'1d','1h'})
            self.assertIn('1h-v22',save.await_args.kwargs['cache_key'])
            self.assertEqual(response['total_scanned'],1)
            self.assertEqual(response['results'][0]['disclosureStatus'],'Not checked')

    async def test_registry_rejects_unsupported_interval_before_database_access(self):
        from scanner.strategies.registry import StrategyRegistry
        with self.assertRaisesRegex(ValueError,'Daily and 1-hour'):
            await StrategyRegistry().execute_scan('institution_transaction',timeframe='15m')

