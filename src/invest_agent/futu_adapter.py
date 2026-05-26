from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import Settings
from .market_news import external_ticker, resolve_market_context_symbols
from .models import PortfolioSnapshot, Position, Quote, utc_now
from .store import Store


class FutuIntegrationError(RuntimeError):
    pass


class FutuReadDisabled(FutuIntegrationError):
    pass


class FutuSdkMissing(FutuIntegrationError):
    pass


@dataclass(frozen=True)
class FutuRefreshResult:
    portfolio: PortfolioSnapshot
    quotes: list[Quote]
    position_count: int
    quote_count: int
    source: str = "futu-opend"

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "position_count": self.position_count,
            "quote_count": self.quote_count,
            "portfolio": self.portfolio.model_dump(mode="json"),
            "quotes": [quote.model_dump(mode="json") for quote in self.quotes],
        }


def get_futu_status(settings: Settings) -> dict[str, Any]:
    status = {
        "provider": "futu-opend",
        "read_enabled": settings.futu_read_enabled,
        "host": settings.futu_host,
        "monitor_port": settings.futu_monitor_port,
        "trade_port": settings.futu_trade_port,
        "connected": False,
        "available": False,
        "message": "",
        "checked_at": utc_now().isoformat(),
    }
    if not settings.futu_read_enabled:
        status["message"] = "FUTU_READ_ENABLED is false; read-only refresh is disabled."
        return status

    try:
        ft = _load_futu()
    except FutuSdkMissing as exc:
        status["message"] = str(exc)
        return status

    quote_ctx = None
    try:
        quote_ctx = ft.OpenQuoteContext(
            host=settings.futu_host,
            port=settings.futu_monitor_port,
            is_encrypt=settings.futu_is_encrypt,
        )
        status["connected"] = True
        status["available"] = True
        status["message"] = "Connected to Futu OpenD in read-only mode."
    except Exception as exc:  # pragma: no cover - depends on local OpenD
        status["message"] = f"Futu OpenD connection failed: {exc}"
    finally:
        if quote_ctx is not None:
            quote_ctx.close()

    return status


def refresh_futu_readonly(settings: Settings, store: Store, refresh_cache: bool = False) -> FutuRefreshResult:
    if not settings.futu_read_enabled:
        raise FutuReadDisabled("FUTU_READ_ENABLED is false; refusing to connect to OpenD.")

    ft = _load_futu()
    quote_ctx = None
    trade_ctx = None
    try:
        trd_market = _enum_value(ft.TrdMarket, settings.futu_trd_market, ft.TrdMarket.US)
        currency = _enum_value(ft.Currency, settings.futu_currency, ft.Currency.USD)
        quote_ctx = ft.OpenQuoteContext(
            host=settings.futu_host,
            port=settings.futu_monitor_port,
            is_encrypt=settings.futu_is_encrypt,
        )
        trade_ctx = ft.OpenSecTradeContext(
            filter_trdmarket=trd_market,
            host=settings.futu_host,
            port=settings.futu_monitor_port,
            is_encrypt=settings.futu_is_encrypt,
        )

        ret_funds, funds_df = trade_ctx.accinfo_query(
            trd_env=ft.TrdEnv.REAL,
            acc_id=settings.futu_acc_id,
            acc_index=settings.futu_acc_index,
            refresh_cache=refresh_cache,
            currency=currency,
        )
        if ret_funds != ft.RET_OK:
            raise FutuIntegrationError(f"accinfo_query failed: {funds_df}")

        ret_pos, pos_df = trade_ctx.position_list_query(
            position_market=ft.TrdMarket.NONE,
            trd_env=ft.TrdEnv.REAL,
            acc_id=settings.futu_acc_id,
            acc_index=settings.futu_acc_index,
            refresh_cache=refresh_cache,
            currency=currency,
        )
        if ret_pos != ft.RET_OK:
            raise FutuIntegrationError(f"position_list_query failed: {pos_df}")

        position_records = _records(pos_df)
        fund_records = _records(funds_df)
        positions = _positions_from_records(position_records)
        portfolio = _portfolio_from_records(fund_records, positions)
        quotes = _quotes_for_symbols(ft, quote_ctx, [position.symbol for position in positions if position.symbol])
        market_quote_error = ""
        try:
            market_symbols = [_futu_symbol(symbol) for symbol in resolve_market_context_symbols(settings, store)]
            quotes = _dedupe_quotes([*quotes, *_quotes_for_symbols(ft, quote_ctx, market_symbols)])
        except FutuIntegrationError as exc:
            market_quote_error = str(exc)

        # Prefer fresh snapshot prices when Futu returns them.
        quote_by_symbol = {quote.symbol: quote for quote in quotes}
        positions = [
            position.model_copy(update={"last_price": quote_by_symbol[position.symbol].last_price})
            if position.symbol in quote_by_symbol
            else position
            for position in positions
        ]
        portfolio = portfolio.model_copy(update={"positions": positions})

        store.upsert_portfolio(portfolio)
        for quote in quotes:
            store.upsert_quote(quote)
        store.audit(
            "futu_readonly_refreshed",
            "provider",
            "futu-opend",
            {
                "position_count": len(positions),
                "quote_count": len(quotes),
                "market_context_quote_error": market_quote_error,
                "refresh_cache": refresh_cache,
                "host": settings.futu_host,
                "monitor_port": settings.futu_monitor_port,
            },
        )

        return FutuRefreshResult(
            portfolio=portfolio,
            quotes=quotes,
            position_count=len(positions),
            quote_count=len(quotes),
        )
    finally:
        if trade_ctx is not None:
            trade_ctx.close()
        if quote_ctx is not None:
            quote_ctx.close()


def _load_futu():
    try:
        import futu as ft
    except ModuleNotFoundError as exc:
        raise FutuSdkMissing("futu-api is not installed. Run: python -m pip install -e '.[futu]'") from exc
    _disable_futu_console_logging(ft)
    return ft


def _disable_futu_console_logging(ft: Any) -> None:
    """Keep Futu SDK logs away from MCP stdio stdout."""
    logger = None
    common = getattr(ft, "common", None)
    ft_logger = getattr(common, "ft_logger", None) if common is not None else None
    if ft_logger is not None:
        logger = getattr(ft_logger, "logger", None)
    if logger is None:
        return
    try:
        logger.enable_console_log(False)
    except Exception:
        return


def _enum_value(enum_cls: Any, value: str, default: Any) -> Any:
    normalized = value.strip().upper()
    return getattr(enum_cls, normalized, default)


def _records(frame_or_records: Any) -> list[dict[str, Any]]:
    if frame_or_records is None:
        return []
    if isinstance(frame_or_records, list):
        return [dict(row) for row in frame_or_records]
    if hasattr(frame_or_records, "to_dict"):
        return frame_or_records.to_dict(orient="records")
    return []


def _positions_from_records(records: list[dict[str, Any]]) -> list[Position]:
    positions: list[Position] = []
    for row in records:
        symbol = str(row.get("code") or row.get("stock_code") or "").strip().upper()
        if not symbol:
            continue
        positions.append(
            Position(
                symbol=symbol,
                qty=_float(row, "qty", "quantity"),
                market_value=_float(row, "market_val", "market_value"),
                avg_cost=_float(row, "average_cost", "diluted_cost", "cost_price"),
                last_price=_float(row, "nominal_price", "last_price", "cur_price"),
                unrealized_pl=_float(row, "pl_val", "unrealized_pl", "pl_value"),
            )
        )
    return positions


def _portfolio_from_records(records: list[dict[str, Any]], positions: list[Position]) -> PortfolioSnapshot:
    row = records[0] if records else {}
    return PortfolioSnapshot(
        cash_usd=_float(row, "us_cash", "cash", "available_funds"),
        total_value_usd=_float(row, "total_assets", "usd_assets", default=sum(p.market_value for p in positions)),
        positions=positions,
        source="futu-opend",
        updated_at=utc_now(),
    )


def _quotes_for_symbols(ft: Any, quote_ctx: Any, symbols: list[str]) -> list[Quote]:
    symbols = _dedupe_symbols(symbols)
    if not symbols:
        return []

    ret, data = quote_ctx.get_market_snapshot(symbols)
    if ret != ft.RET_OK:
        raise FutuIntegrationError(f"get_market_snapshot failed: {data}")

    return _quotes_from_records(_records(data))


def _futu_symbol(symbol: str) -> str:
    symbol = symbol.strip().upper()
    return symbol if "." in symbol else f"US.{symbol}"


def _dedupe_symbols(symbols: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for symbol in symbols:
        normalized = symbol.strip().upper()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _dedupe_quotes(quotes: list[Quote]) -> list[Quote]:
    by_ticker: dict[str, Quote] = {}
    for quote in quotes:
        by_ticker[external_ticker(quote.symbol)] = quote
    return list(by_ticker.values())


def _quotes_from_records(records: list[dict[str, Any]]) -> list[Quote]:
    quotes: list[Quote] = []
    for row in records:
        symbol = str(row.get("code") or "").strip().upper()
        if not symbol:
            continue
        quotes.append(
            Quote(
                symbol=symbol,
                last_price=_float(row, "last_price", "cur_price", "price", "nominal_price"),
                previous_close=_optional_float(row, "prev_close_price", "pre_close_price", "previous_close"),
                change_pct=_quote_change_pct(row),
                bid=_optional_float(row, "bid_price", "bid"),
                ask=_optional_float(row, "ask_price", "ask"),
                currency=_currency_from_symbol(symbol),
                source="futu-opend",
                updated_at=utc_now(),
            )
        )
    return quotes


def _quote_change_pct(row: dict[str, Any]) -> float | None:
    direct = _optional_float(row, "change_rate", "change_pct", "change_ratio")
    if direct is not None:
        return direct
    last_price = _optional_float(row, "last_price", "cur_price", "price", "nominal_price")
    previous_close = _optional_float(row, "prev_close_price", "pre_close_price", "previous_close")
    if last_price is None or previous_close in (None, 0):
        return None
    return ((last_price - previous_close) / previous_close) * 100


def _currency_from_symbol(symbol: str) -> str:
    prefix = symbol.split(".", 1)[0].upper()
    return {"US": "USD", "HK": "HKD", "CN": "CNY", "JP": "JPY", "SG": "SGD"}.get(prefix, "USD")


def _float(row: dict[str, Any], *keys: str, default: float = 0.0) -> float:
    value = _first(row, *keys)
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_float(row: dict[str, Any], *keys: str) -> float | None:
    value = _first(row, *keys)
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row:
            return row[key]
    return None
