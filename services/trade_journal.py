"""Persistent local trade journal. Money calculations use Decimal, not XLSX caches."""
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from database.connection import async_session_factory
from database.models import JournalTrade

router = APIRouter(prefix='/api/journal')
IST = ZoneInfo('Asia/Kolkata')


class TradeInput(BaseModel):
    account: str = Field(default='Main account', min_length=1, max_length=80)
    symbol: str = Field(min_length=1, max_length=100)
    segment: Literal['Equity', 'Futures', 'Options', 'Commodity', 'Other'] = 'Equity'
    instrumentType: str = Field(default='', max_length=40)
    timeframe: str = Field(default='Daily', max_length=40)
    direction: Literal['LONG', 'SHORT']
    entryAt: datetime
    exitAt: datetime | None = None
    entryPrice: Decimal = Field(gt=0, le=1_000_000_000, allow_inf_nan=False)
    exitPrice: Decimal | None = Field(default=None, gt=0, le=1_000_000_000, allow_inf_nan=False)
    quantity: int = Field(ge=1, le=1_000_000_000)
    lotSize: int = Field(default=1, ge=1, le=10_000_000)
    charges: Decimal = Field(default=0, ge=0, le=1_000_000_000, allow_inf_nan=False)
    capital: Decimal | None = Field(default=None, gt=0, le=1_000_000_000_000, allow_inf_nan=False)
    riskPercent: Decimal | None = Field(default=None, gt=0, le=100, allow_inf_nan=False)
    stopPrice: Decimal | None = Field(default=None, gt=0, le=1_000_000_000, allow_inf_nan=False)
    targetPrice: Decimal | None = Field(default=None, gt=0, le=1_000_000_000, allow_inf_nan=False)
    recordedRisk: Decimal | None = Field(default=None, gt=0, le=1_000_000_000_000, allow_inf_nan=False)
    setup: str = Field(default='', max_length=150)
    marketTrend: str = Field(default='', max_length=200)
    reason: str = Field(default='', max_length=4000)
    evidence: str = Field(default='', max_length=4000)
    fibLevel: str = Field(default='', max_length=100)
    rsi: Decimal | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    divergence: str = Field(default='', max_length=100)
    supportResistance: str = Field(default='', max_length=1000)
    trendline: str = Field(default='', max_length=1000)
    volumeConfirmation: str = Field(default='', max_length=1000)
    emotionBefore: str = Field(default='', max_length=200)
    emotionDuring: str = Field(default='', max_length=200)
    emotionAfter: str = Field(default='', max_length=200)
    confidence: int | None = Field(default=None, ge=1, le=10)
    rating: int | None = Field(default=None, ge=1, le=10)
    entryFollowed: bool | None = None
    stopFollowed: bool | None = None
    exitFollowed: bool | None = None
    wouldTakeAgain: bool | None = None
    mistake: str = Field(default='', max_length=4000)
    didWell: str = Field(default='', max_length=4000)
    learned: str = Field(default='', max_length=4000)
    exitReason: Literal['Target', 'Stop', 'Trailing', 'Manual', 'Other', ''] = ''
    chartLink: str = Field(default='', max_length=2000)
    notes: str = Field(default='', max_length=8000)

    @field_validator('symbol', 'account')
    @classmethod
    def nonblank(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('Symbol and account cannot be blank')
        return value

    @field_validator('entryAt', 'exitAt')
    @classmethod
    def zoned(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError('Trade times must include a timezone')
        return value

    @field_validator('chartLink')
    @classmethod
    def safe_link(cls, value):
        from urllib.parse import urlparse
        if value and (urlparse(value).scheme not in ('https', 'http') or not urlparse(value).hostname):
            raise ValueError('Chart link must be an http or https URL')
        return value

    @model_validator(mode='after')
    def consistent(self):
        if (self.exitAt is None) != (self.exitPrice is None):
            raise ValueError('Enter both exit time and exit price, or leave both empty for an open trade')
        if self.exitAt and self.exitAt < self.entryAt:
            raise ValueError('Exit cannot precede entry')
        if self.stopPrice is not None and ((self.direction == 'LONG' and self.stopPrice >= self.entryPrice) or (self.direction == 'SHORT' and self.stopPrice <= self.entryPrice)):
            raise ValueError('Stop must be below a long entry or above a short entry')
        if self.targetPrice is not None and ((self.direction == 'LONG' and self.targetPrice <= self.entryPrice) or (self.direction == 'SHORT' and self.targetPrice >= self.entryPrice)):
            raise ValueError('Target must be above a long entry or below a short entry')
        return self


def calculated(trade: TradeInput):
    quantity = Decimal(trade.quantity)
    sign = Decimal(1 if trade.direction == 'LONG' else -1)
    risk_unit = abs(trade.entryPrice - trade.stopPrice) if trade.stopPrice is not None else None
    planned = risk_unit * quantity if risk_unit is not None else trade.recordedRisk
    budget = trade.capital * trade.riskPercent / 100 if trade.capital is not None and trade.riskPercent is not None else None
    reward_unit = abs(trade.targetPrice - trade.entryPrice) if trade.targetPrice is not None else None
    points = sign * (trade.exitPrice - trade.entryPrice) if trade.exitPrice is not None else None
    gross = points * quantity if points is not None else None
    net = gross - trade.charges if gross is not None else None
    return {
        'quantity': trade.quantity, 'actualLots': float(quantity / trade.lotSize),
        'positionValue': float(trade.entryPrice * quantity),
        'maxRisk': float(budget) if budget is not None else None,
        'recommendedLots': int((budget / (risk_unit * trade.lotSize)).to_integral_value(rounding=ROUND_FLOOR)) if budget is not None and risk_unit else None,
        'plannedRisk': float(planned) if planned is not None else None,
        'plannedReward': float(reward_unit * quantity) if reward_unit is not None else None,
        'plannedRR': float(reward_unit / risk_unit) if reward_unit is not None and risk_unit else None,
        'points': float(points) if points is not None else None,
        'grossPnl': float(gross) if gross is not None else None,
        'netPnl': float(net) if net is not None else None,
        'rMultiple': float(net / planned) if net is not None and planned else None,
        'durationMinutes': (trade.exitAt - trade.entryAt).total_seconds() / 60 if trade.exitAt else None,
        'result': 'OPEN' if net is None else 'WIN' if net > 0 else 'LOSS' if net < 0 else 'BREAKEVEN',
    }


def serialize(row):
    content = json.loads(row.content_json)
    trade = TradeInput.model_validate(content)
    return {'id': row.id, **content, **calculated(trade), 'imported': bool(row.import_key),
            'updatedAt': row.updated_at.replace(tzinfo=timezone.utc).isoformat() if row.updated_at.tzinfo is None else row.updated_at.isoformat()}


@router.get('/trades')
async def trades():
    async with async_session_factory() as session:
        rows = (await session.scalars(select(JournalTrade).order_by(JournalTrade.id.desc()))).all()
        return {'trades': [serialize(row) for row in rows]}


@router.post('/trades')
async def create_trade(trade: TradeInput):
    async with async_session_factory() as session:
        row = JournalTrade(content_json=trade.model_dump_json())
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return serialize(row)


@router.put('/trades/{trade_id:int}')
async def update_trade(trade_id: int, trade: TradeInput):
    async with async_session_factory() as session:
        row = await session.get(JournalTrade, trade_id)
        if row is None:
            raise HTTPException(404, 'Trade not found')
        row.content_json = trade.model_dump_json()
        row.updated_at = datetime.now(timezone.utc)
        await session.commit()
        return serialize(row)


@router.delete('/trades/{trade_id:int}')
async def delete_trade(trade_id: int):
    async with async_session_factory() as session:
        row = await session.get(JournalTrade, trade_id)
        if row is None:
            raise HTTPException(404, 'Trade not found')
        await session.delete(row)
        await session.commit()
        return {'deleted': True}


@router.get('/provided-workbooks')
async def provided_workbooks():
    return json.loads((Path(__file__).parent.parent / 'data' / 'journal-workbook-reference.json').read_text(encoding='utf-8'))


@router.post('/import-provided')
async def import_provided():
    reference = await provided_workbooks()
    added, duplicates = 0, 0
    async with async_session_factory() as session:
        for item in reference['trades']:
            trade = TradeInput.model_validate(item)
            key = hashlib.sha256(('provided-reflection-v1:' + trade.model_dump_json()).encode()).hexdigest()
            existing = await session.scalar(select(JournalTrade.id).where(JournalTrade.import_key == key))
            if existing is not None:
                duplicates += 1
                continue
            try:
                async with session.begin_nested():
                    session.add(JournalTrade(content_json=trade.model_dump_json(), import_key=key))
                    await session.flush()
                added += 1
            except IntegrityError:
                duplicates += 1
        await session.commit()
    return {'added': added, 'duplicates': duplicates, 'warnings': reference['warnings']}
