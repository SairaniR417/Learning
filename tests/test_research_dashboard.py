"""Research levels must use known prior periods and retain missing-data states."""
from datetime import datetime, timedelta, timezone
from unittest import TestCase
from services.research_dashboard import aggregate, bars, build, build_stock, pivots, trendline

NOW = datetime(2026,11,15,12,tzinfo=timezone.utc)
META = dict(key='NSE_EQ|TEST',symbol='TEST',name='Test',exchange='NSE')

def candle(day, close=100, **extra):
    return dict(timestamp=day,open=close-1,high=close+3,low=close-4,close=close,volume=1000,**extra)

def history():
    start=NOW-timedelta(days=900)
    return [candle((start+timedelta(days=i)).replace(hour=0),100+i*.1) for i in range(899)
            if (start+timedelta(days=i)).weekday()<5]

class ResearchTests(TestCase):
    def test_empty_retains_missing_fields_and_no_institution_claim(self):
        result=build([META],{}, {}, NOW)
        row=result['stocks'][0]
        self.assertIsNone(row['price'])
        self.assertEqual(row['bias'],'UNAVAILABLE')
        self.assertIsNone(row['levels']['daily'])
        self.assertEqual(row['sutradharPosition'],'UNAVAILABLE')
        self.assertEqual(row['institutionalDisclosure'],'Not connected')
        self.assertIsNone(row['futuresOi'])
        self.assertEqual(result['sectors'][0]['name'],'Unclassified')

    def test_formulas_and_sorted_cpr_bounds(self):
        row=candle(NOW,100)
        row.update(high=120,low=80,close=110)
        p=pivots(row,112)
        self.assertAlmostEqual(p['pivot'],310/3)
        self.assertEqual(p['bc'],100)
        self.assertAlmostEqual(p['tc'],320/3)
        self.assertEqual(p['r4'],132)
        self.assertEqual(p['s4'],88)
        self.assertEqual(p['r3'],121)
        self.assertEqual(p['s3'],99)
        self.assertEqual(p['position'],'ABOVE')

    def test_prior_daily_source_does_not_use_observation_candle(self):
        daily=history()
        row=build_stock(META,daily,[],NOW)
        expected=pivots(daily[-2],daily[-1]['close'])
        self.assertEqual(row['levels']['daily'],expected)
        changed=[dict(r) for r in daily]
        changed[-1].update(high=999,low=1)
        self.assertEqual(build_stock(META,changed,[],NOW)['levels']['daily']['pivot'],expected['pivot'])
        for f in ('weekly','monthly'):
            self.assertLess(datetime.fromisoformat(row['levels'][f]['sourceAt']),daily[-1]['timestamp'])

    def test_developing_and_invalid_bars_cannot_contaminate_latest_segment(self):
        rows=history()
        completed=bars(rows,'1d',NOW)
        self.assertEqual(bars(rows+[candle(NOW+timedelta(days=1),999)],'1d',NOW),completed)
        bad=dict(rows[-3],close=0)
        cleaned=bars(rows[:-3]+[bad]+rows[-2:],'1d',NOW)
        self.assertEqual(cleaned,rows[-2:])
        self.assertEqual(bars(rows+[rows[-1]],'1d',NOW),completed)

    def test_aggregates_exclude_developing_month_and_first_partial_period(self):
        rows=history()
        months=aggregate(rows,'monthly',NOW)
        self.assertTrue(all(r['timestamp'].month != 11 or r['timestamp'].year != 2026 for r in months))
        self.assertGreater(months[0]['timestamp'],rows[0]['timestamp'])
        for row in months:
            sources=[r for r in rows if r['timestamp'].year==row['timestamp'].year and r['timestamp'].month==row['timestamp'].month]
            self.assertEqual(row['volume'],sum(r['volume'] for r in sources))
            self.assertEqual(row['sourceAsOf'],sources[-1]['timestamp'])

    def test_new_hourly_session_uses_prior_daily_and_verified_open(self):
        daily=history()
        day=datetime(2026,11,16,3,45,tzinfo=timezone.utc)
        hourly=[candle(day,200,instrument_key=META['key'])]
        row=build_stock(META,daily,hourly,day+timedelta(hours=2))
        self.assertEqual(row['price'],200)
        self.assertEqual(row['levels']['daily']['sourceAt'],daily[-1]['timestamp'].isoformat())
        self.assertIsNotNone(row['sutradhar']['Flow'])
        self.assertEqual(row['sutradhar']['O'],199)
        # An older hourly session must not classify a newer daily close.
        old_hourly=[candle(daily[-3]['timestamp'].replace(hour=3,minute=45),120,instrument_key=META['key'])]
        self.assertEqual(build_stock(META,daily,old_hourly,NOW)['sutradharPosition'],'UNAVAILABLE')

    def test_trendline_requires_confirmed_pivots_and_rejects_broken_lines(self):
        # Low pivots at 2, 6 and 10 create a rising support candidate.
        lows=[13,12,10,12,13,14,12,14,15,16,14,16,17]
        rows=[dict(candle(NOW-timedelta(days=20-i),v+2),low=v,high=v+5) for i,v in enumerate(lows)]
        line=trendline(rows,'support')
        self.assertIsNotNone(line)
        self.assertGreaterEqual(line['touches'],2)
        rows[-1].update(low=1,open=3,close=4,high=5)
        self.assertIsNone(trendline(rows,'support'))
