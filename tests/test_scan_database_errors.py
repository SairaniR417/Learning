"""A failed history read must never be presented as a successful empty scan."""
import unittest
from unittest.mock import patch,AsyncMock
from sqlalchemy.exc import InternalError,OperationalError
from fastapi.testclient import TestClient
import main


class ScanDatabaseErrorsTests(unittest.TestCase):
    def test_damaged_heap_page_has_clear_service_unavailable_response(self):
        error=InternalError('SELECT candle history',{},Exception('invalid page in block 10464 of relation "base/16384/16401"'))
        with patch.object(main.strategy_registry,'execute_scan',AsyncMock(side_effect=error)),self.assertLogs('main',level='ERROR'):
            response=TestClient(main.app).post('/api/strategies/scan',json={'strategy_id':'sutradhar','timeframe':'15m','params':{'use_ema':False}})
        self.assertEqual(response.status_code,503)
        self.assertIn('damaged data page',response.json()['detail'])
        self.assertIn('No scan results',response.json()['detail'])
        self.assertNotIn('base/16384',response.text)

    def test_connection_failure_does_not_claim_corrupt_data(self):
        error=OperationalError('SELECT history',{},Exception('Connection refused'))
        with patch.object(main.strategy_registry,'execute_scan',AsyncMock(side_effect=error)),self.assertLogs('main',level='ERROR'):
            response=TestClient(main.app).post('/api/strategies/scan',json={'strategy_id':'sutradhar','timeframe':'15m'})
        self.assertEqual(response.status_code,503)
        self.assertNotIn('damaged',response.text)
        self.assertIn('database connection',response.json()['detail'])
