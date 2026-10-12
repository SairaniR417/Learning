"""Company-size metadata must be dated and never guessed from share price."""
import json
import unittest
from unittest.mock import patch

from services.market_cap import attach_market_caps, parse_market_caps

class MarketCapTests(unittest.TestCase):
    def test_nse_headers_with_padding_and_dated_values(self):
        with patch('services.market_cap.zipfile.ZipFile') as archive:
            z = archive.return_value.__enter__.return_value
            z.namelist.return_value = ['mcap12102026.csv']
            z.read.return_value = b'Trade Date,Symbol,Series,Market Cap(Rs.)    \n12 OCT 2026,BANK,EQ,638399060850\n'
            result = parse_market_caps('PR.zip')
            self.assertEqual(result['asOf'], '2026-10-12')
            self.assertEqual(result['values']['BANK'], 638399060850)

    def test_stale_size_snapshot_is_not_used(self):
        snapshot = {'asOf': '2026-10-12', 'source': 'NSE', 'values': {'BANK': 638399060850}}
        original = {'asOf': '2026-10-13', 'bullish': [{'symbol': 'BANK', 'close': 83}], 'bearish': []}
        with patch('services.market_cap.SNAPSHOT') as path:
            path.exists.return_value = True
            path.read_text.return_value = json.dumps(snapshot)
            result = attach_market_caps(original)
            self.assertIsNone(result['bullish'][0]['marketCap'])
            self.assertIsNone(result['marketCapAsOf'])
            original['asOf'] = '2026-10-12'
            result = attach_market_caps(original)
            self.assertEqual(result['bullish'][0]['marketCap'], 638399060850)
            self.assertNotIn('marketCap', original['bullish'][0])

    def test_unknown_company_stays_unknown(self):
        with patch('services.market_cap.SNAPSHOT') as path:
            path.exists.return_value = False
            result = attach_market_caps({'asOf': '2026-10-12', 'bullish': [{'symbol': 'UNKNOWN', 'close': 20000}], 'bearish': []})
            self.assertIsNone(result['bullish'][0]['marketCap'])

if __name__ == '__main__':
    unittest.main()
