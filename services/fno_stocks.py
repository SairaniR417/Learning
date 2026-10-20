"""Expose the shared saved F&O stock universe."""
from fastapi import APIRouter
from scanner.universe import get_fno_stocks

router = APIRouter(prefix="/api/market")


@router.get("/fno-stocks")
def fno_stocks():
    stocks = get_fno_stocks()
    return {"stocks": stocks, "total": len(stocks)}
