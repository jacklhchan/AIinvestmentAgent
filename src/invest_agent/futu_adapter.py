from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .config import Settings
from .market_news import external_ticker, resolve_market_context_symbols, resolve_watchlist_symbols
from .models import PortfolioSnapshot, Position, Quote, utc_now
from .store import Store


class FutuIntegrationError(RuntimeError):
    pass


class FutuReadDisabled(FutuIntegrationError):
    pass


class FutuSdkMissing(FutuIntegrationError):
    pass


@dataclass(frozen=True)
class FutuAccountInfo:
    acc_id: int | None = None
    trd_env: str = ""
    trdmarket_auth: list[str] = field(default_factory=list)
    sim_acc_type: str = ""
    security_firm: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "acc_id": self.acc_id,
            "trd_env": self.trd_env,
            "trdmarket_auth": self.trdmarket_auth,
            "sim_acc_type": self.sim_acc_type,
            "security_firm": _mask_if_sensitive(self.security_firm),
        }


@dataclass(frozen=True)
class FutuAccountDiscoveryResult:
    accounts: list[FutuAccountInfo]
    selected_account: FutuAccountInfo | None
    candidate_acc_ids: list[int]
    selection_status: str
    message: str
    source: str = "futu-opend"

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "account_count": len(self.accounts),
            "accounts": [account.as_dict() for account in self.accounts],
            "selected_account": self.selected_account.as_dict() if self.selected_account else None,
            "candidate_acc_ids": self.candidate_acc_ids,
            "selection_status": self.selection_status,
            "message": self.message,
        }


@dataclass(frozen=True)
class FutuQuoteRefreshResult:
    quotes: list[Quote]
    symbols: list[str]
    quote_count: int
    source: str = "futu-opend"

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "symbol_count": len(self.symbols),
            "symbols": self.symbols,
            "quote_count": self.quote_count,
            "quotes": [quote.model_dump(mode="json") for quote in self.quotes],
        }


@dataclass(frozen=True)
class FutuAccountSnapshotResult:
    portfolio: PortfolioSnapshot
    selected_account: FutuAccountInfo
    position_count: int
    source: str = "futu-opend"

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "selected_account": self.selected_account.as_dict(),
            "position_count": self.position_count,
            "portfolio": self.portfolio.model_dump(mode="json"),
        }


@dataclass(frozen=True)
class FutuRefreshResult:
    portfolio: PortfolioSnapshot | None
    quotes: list[Quote]
    position_count: int
    quote_count: int
    quote_status: str
    account_status: str
    quote_error: str = ""
    account_error: str = ""
    selected_account: FutuAccountInfo | None = None
    source: str = "futu-opend"

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "ok": self.quote_status != "error" and self.account_status != "error",
            "partial": self.quote_status == "ok" and self.account_status == "error",
            "quote_status": self.quote_status,
            "account_status": self.account_status,
            "quote_error": self.quote_error,
            "account_error": self.account_error,
            "position_count": self.position_count,
            "quote_count": self.quote_count,
            "selected_account": self.selected_account.as_dict() if self.selected_account else None,
            "portfolio": self.portfolio.model_dump(mode="json") if self.portfolio else None,
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
        status["message"] = "Connected to Futu OpenD quote service in read-only mode."
    except Exception as exc:  # pragma: no cover - depends on local OpenD
        status["message"] = f"Futu OpenD quote connection failed: {exc}"
    finally:
        if quote_ctx is not None:
            quote_ctx.close()

    return status


def discover_futu_accounts(settings: Settings) -> FutuAccountDiscoveryResult:
    if not settings.futu_read_enabled:
        raise FutuReadDisabled("FUTU_READ_ENABLED is false; refusing to connect to OpenD.")

    ft = _load_futu()
    trade_ctx = None
    try:
        trade_ctx = _open_trade_context(ft, settings)
        return _discover_accounts_from_context(ft, trade_ctx, settings)
    finally:
        if trade_ctx is not None:
            trade_ctx.close()


def refresh_futu_quotes_only(settings: Settings, store: Store, symbols: Iterable[str] | None = None) -> FutuQuoteRefreshResult:
    if not settings.futu_read_enabled:
        raise FutuReadDisabled("FUTU_READ_ENABLED is false; refusing to connect to OpenD.")

    ft = _load_futu()
    quote_ctx = None
    try:
        quote_ctx = ft.OpenQuoteContext(
            host=settings.futu_host,
            port=settings.futu_monitor_port,
            is_encrypt=settings.futu_is_encrypt,
        )
        futu_symbols = _quote_refresh_symbols(settings, store, symbols)
        quotes = _quotes_for_symbols(ft, quote_ctx, futu_symbols)
        quotes = _dedupe_quotes(quotes)
        for quote in quotes:
            store.upsert_quote(quote)
        store.audit(
            "futu_quotes_refreshed",
            "provider",
            "futu-opend",
            {
                "quote_count": len(quotes),
                "symbol_count": len(futu_symbols),
                "symbols": futu_symbols[:40],
                "host": settings.futu_host,
                "monitor_port": settings.futu_monitor_port,
            },
        )
        return FutuQuoteRefreshResult(quotes=quotes, symbols=futu_symbols, quote_count=len(quotes))
    finally:
        if quote_ctx is not None:
            quote_ctx.close()


def refresh_futu_account_snapshot(settings: Settings, store: Store, refresh_cache: bool = False) -> FutuAccountSnapshotResult:
    if not settings.futu_read_enabled:
        raise FutuReadDisabled("FUTU_READ_ENABLED is false; refusing to connect to OpenD.")

    ft = _load_futu()
    trade_ctx = None
    try:
        trade_ctx = _open_trade_context(ft, settings)
        discovery = _discover_accounts_from_context(ft, trade_ctx, settings)
        if discovery.selected_account is None:
            raise FutuIntegrationError(discovery.message)

        currency = _enum_value(ft.Currency, settings.futu_currency, ft.Currency.USD)
        trd_env = _enum_value(ft.TrdEnv, discovery.selected_account.trd_env or settings.futu_trd_env, ft.TrdEnv.REAL)
        acc_id = discovery.selected_account.acc_id or settings.futu_acc_id

        ret_funds, funds_df = trade_ctx.accinfo_query(
            trd_env=trd_env,
            acc_id=acc_id,
            acc_index=settings.futu_acc_index,
            refresh_cache=refresh_cache,
            currency=currency,
        )
        if ret_funds != ft.RET_OK:
            raise FutuIntegrationError(f"accinfo_query failed: {funds_df}")

        ret_pos, pos_df = trade_ctx.position_list_query(
            position_market=_enum_value(ft.TrdMarket, settings.futu_trd_market, ft.TrdMarket.US),
            trd_env=trd_env,
            acc_id=acc_id,
            acc_index=settings.futu_acc_index,
            refresh_cache=refresh_cache,
            currency=currency,
        )
        if ret_pos != ft.RET_OK:
            raise FutuIntegrationError(f"position_list_query failed: {pos_df}")

        positions = _positions_from_records(_records(pos_df))
        quote_by_symbol = {quote.symbol: quote for quote in store.list_quotes()}
        positions = [
            position.model_copy(update={"last_price": quote_by_symbol[position.symbol].last_price})
            if position.symbol in quote_by_symbol
            else position
            for position in positions
        ]
        portfolio = _portfolio_from_records(_records(funds_df), positions)
        portfolio = portfolio.model_copy(update={"positions": positions})
        store.upsert_portfolio(portfolio)
        store.audit(
            "futu_account_snapshot_refreshed",
            "provider",
            "futu-opend",
            {
                "position_count": len(positions),
                "selected_acc_id": acc_id,
                "trd_env": discovery.selected_account.trd_env,
                "refresh_cache": refresh_cache,
                "host": settings.futu_host,
                "monitor_port": settings.futu_monitor_port,
            },
        )
        return FutuAccountSnapshotResult(
            portfolio=portfolio,
            selected_account=discovery.selected_account,
            position_count=len(positions),
        )
    finally:
        if trade_ctx is not None:
            trade_ctx.close()


def refresh_futu_readonly(settings: Settings, store: Store, refresh_cache: bool = False) -> FutuRefreshResult:
    if not settings.futu_read_enabled:
        raise FutuReadDisabled("FUTU_READ_ENABLED is false; refusing to connect to OpenD.")

    quote_result: FutuQuoteRefreshResult | None = None
    account_result: FutuAccountSnapshotResult | None = None
    quote_error = ""
    account_error = ""

    try:
        quote_result = refresh_futu_quotes_only(settings, store)
    except FutuIntegrationError as exc:
        quote_error = str(exc)
        store.audit("futu_quote_refresh_failed", "provider", "futu-opend", {"error": quote_error})

    try:
        account_result = refresh_futu_account_snapshot(settings, store, refresh_cache=refresh_cache)
    except FutuIntegrationError as exc:
        account_error = str(exc)
        store.audit("futu_account_snapshot_failed", "provider", "futu-opend", {"error": account_error})

    if quote_result is None and account_result is None:
        raise FutuIntegrationError("; ".join(item for item in [quote_error, account_error] if item))

    result = FutuRefreshResult(
        portfolio=account_result.portfolio if account_result else None,
        quotes=quote_result.quotes if quote_result else [],
        position_count=account_result.position_count if account_result else 0,
        quote_count=quote_result.quote_count if quote_result else 0,
        quote_status="ok" if quote_result else "error",
        account_status="ok" if account_result else "error",
        quote_error=quote_error,
        account_error=account_error,
        selected_account=account_result.selected_account if account_result else None,
    )
    store.audit(
        "futu_readonly_refreshed",
        "provider",
        "futu-opend",
        {
            "position_count": result.position_count,
            "quote_count": result.quote_count,
            "quote_status": result.quote_status,
            "account_status": result.account_status,
            "quote_error": quote_error,
            "account_error": account_error,
            "refresh_cache": refresh_cache,
            "host": settings.futu_host,
            "monitor_port": settings.futu_monitor_port,
        },
    )
    return result


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


def _open_trade_context(ft: Any, settings: Settings) -> Any:
    return ft.OpenSecTradeContext(
        filter_trdmarket=_enum_value(ft.TrdMarket, settings.futu_trd_market, ft.TrdMarket.US),
        host=settings.futu_host,
        port=settings.futu_monitor_port,
        is_encrypt=settings.futu_is_encrypt,
    )


def _discover_accounts_from_context(ft: Any, trade_ctx: Any, settings: Settings) -> FutuAccountDiscoveryResult:
    if not hasattr(trade_ctx, "get_acc_list"):
        raise FutuIntegrationError("Futu SDK trade context does not expose get_acc_list().")
    ret, data = trade_ctx.get_acc_list()
    if ret != ft.RET_OK:
        raise FutuIntegrationError(f"get_acc_list failed: {data}")
    accounts = _accounts_from_records(_records(data))
    selected, candidates, status, message = _select_account(settings, accounts)
    return FutuAccountDiscoveryResult(
        accounts=accounts,
        selected_account=selected,
        candidate_acc_ids=[account.acc_id for account in candidates if account.acc_id is not None],
        selection_status=status,
        message=message,
    )


def _select_account(
    settings: Settings,
    accounts: list[FutuAccountInfo],
) -> tuple[FutuAccountInfo | None, list[FutuAccountInfo], str, str]:
    candidates = [account for account in accounts if _account_matches_settings(account, settings)]
    candidate_ids = [str(account.acc_id) for account in candidates if account.acc_id is not None]
    if settings.futu_acc_id:
        explicit = next((account for account in candidates if account.acc_id == settings.futu_acc_id), None)
        if explicit:
            return explicit, candidates, "ok", f"Selected configured FUTU_ACC_ID {settings.futu_acc_id}."
        return (
            None,
            candidates,
            "error",
            f"Configured FUTU_ACC_ID {settings.futu_acc_id} is not available for {settings.futu_trd_env}/{settings.futu_trd_market}. "
            f"Available candidate acc_id values: {', '.join(candidate_ids) or 'none'}.",
        )
    if len(candidates) == 1:
        selected = candidates[0]
        return selected, candidates, "ok", f"Auto-selected single matching Futu account {selected.acc_id}."
    if not candidates:
        return (
            None,
            candidates,
            "warn",
            f"No Futu accounts match {settings.futu_trd_env}/{settings.futu_trd_market}; set FUTU_ACC_ID explicitly after running futu-accounts.",
        )
    return (
        None,
        candidates,
        "warn",
        f"Multiple Futu accounts match {settings.futu_trd_env}/{settings.futu_trd_market}; set FUTU_ACC_ID explicitly. "
        f"Available candidate acc_id values: {', '.join(candidate_ids)}.",
    )


def _account_matches_settings(account: FutuAccountInfo, settings: Settings) -> bool:
    if settings.futu_trd_env and account.trd_env and _norm(account.trd_env) != _norm(settings.futu_trd_env):
        return False
    if settings.futu_trd_market and account.trdmarket_auth:
        auth = {_norm(item) for item in account.trdmarket_auth}
        market = _norm(settings.futu_trd_market)
        if market not in auth and "ALL" not in auth and "NONE" not in auth:
            return False
    if settings.futu_security_firm and account.security_firm and _norm(settings.futu_security_firm) != _norm(account.security_firm):
        return False
    if settings.futu_sim_acc_type and account.sim_acc_type and _norm(settings.futu_sim_acc_type) != _norm(account.sim_acc_type):
        return False
    return True


def _accounts_from_records(records: list[dict[str, Any]]) -> list[FutuAccountInfo]:
    result: list[FutuAccountInfo] = []
    for row in records:
        acc_id = _optional_int(row, "acc_id", "accID", "id")
        result.append(
            FutuAccountInfo(
                acc_id=acc_id,
                trd_env=_string(row, "trd_env", "env"),
                trdmarket_auth=_market_auth(row.get("trdmarket_auth") or row.get("trd_market_auth") or row.get("market_auth")),
                sim_acc_type=_string(row, "sim_acc_type", "simulation_account_type"),
                security_firm=_string(row, "security_firm", "broker", "broker_name"),
            )
        )
    return result


def _quote_refresh_symbols(settings: Settings, store: Store, symbols: Iterable[str] | None = None) -> list[str]:
    requested = list(symbols or [])
    portfolio_symbols = [position.symbol for position in store.get_portfolio().positions if position.symbol]
    watchlist_symbols = resolve_watchlist_symbols(settings, store)
    market_symbols = resolve_market_context_symbols(settings, store)
    return _dedupe_symbols([_futu_symbol(symbol) for symbol in [*requested, *portfolio_symbols, *watchlist_symbols, *market_symbols]])


def _enum_value(enum_cls: Any, value: str, default: Any) -> Any:
    normalized = str(value or "").strip().upper()
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


def _market_auth(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple, set)):
        return [_norm(item) for item in value if str(item).strip()]
    raw = str(value).replace("[", " ").replace("]", " ").replace("'", " ").replace('"', " ")
    parts = [item.strip() for chunk in raw.split(",") for item in chunk.split("|")]
    return [_norm(item) for item in parts if item]


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


def _optional_int(row: dict[str, Any], *keys: str) -> int | None:
    value = _first(row, *keys)
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _string(row: dict[str, Any], *keys: str) -> str:
    value = _first(row, *keys)
    if value in (None, ""):
        return ""
    return _norm(value)


def _first(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row:
            return row[key]
    return None


def _norm(value: Any) -> str:
    raw = getattr(value, "value", value)
    text = str(raw or "").strip().upper()
    return text.rsplit(".", 1)[-1]


def _mask_if_sensitive(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    sensitive = {"password", "token", "secret", "key"}
    if any(item in text.lower() for item in sensitive):
        return "***"
    return text
