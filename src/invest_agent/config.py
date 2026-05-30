from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseModel):
    db_path: Path = Field(default=PROJECT_ROOT / "data" / "invest_agent.db")
    host: str = "127.0.0.1"
    port: int = 8788
    mode: str = "paper"

    max_trade_notional_usd: float = 5000.0
    max_position_pct: float = 35.0
    approval_ttl_minutes: int = 15
    max_price_drift_bps: float = 30.0
    min_confidence: float = 0.35
    allow_live_trading: bool = False
    watchlist_symbols: str = "AAPL,MSFT,NVDA,GOOGL"
    market_context_symbols: str = "SPY,QQQ,IWM,DIA,VIXY,TLT,GLD,USO,XLK,XLF,XLE,XLV,XLY,XLP,XLI,XLU,XLB,XLRE,SMH,SOXX,IGV,XBI,IBB,ITA,KRE,SCHD,SGOV,BIL"
    draft_notional_usd: float = 1000.0
    draft_max_candidates: int = 3
    draft_min_score: int = 7
    signal_buy_threshold: int = 70
    signal_sell_threshold: int = 65
    signal_watch_threshold: int = 45
    signal_max_per_run: int = 8
    signal_expiry_hours: int = 24
    signal_duplicate_cooldown_minutes: int = 240
    paper_advice_committee_freshness_minutes: int = 240
    news_lookback_days: int = 3
    news_max_per_symbol: int = 5
    news_max_symbols: int = 12
    news_timeout_seconds: float = 5.0
    google_news_fallback_enabled: bool = True
    sec_user_agent: str = "AIinvestmentAgent/0.1 local-use contact@example.com"
    sec_forms: str = "10-K,10-Q,8-K,20-F,6-K"
    sec_max_filings_per_symbol: int = 5
    sec_timeout_seconds: float = 8.0
    primary_source_lookback_days: int = 45
    research_gate_required: bool = True
    research_gate_max_verified_age_days: int = 120
    ir_rss_feeds: str = ""
    autonomy_cycle_seconds: int = 900
    autonomy_create_proposals: bool = True
    autonomy_refresh_futu: bool = True
    autonomy_refresh_news: bool = True
    autonomy_refresh_primary_sources: bool = True
    autonomy_refresh_fundamentals: bool = True
    autonomy_primary_every_cycles: int = 4
    autonomy_fundamentals_every_cycles: int = 16
    autonomy_proposal_cooldown_minutes: int = 240

    futu_host: str = "127.0.0.1"
    futu_monitor_port: int = 11111
    futu_trade_port: int = 11112
    futu_trade_password: str = ""
    futu_read_enabled: bool = False
    futu_trd_market: str = "US"
    futu_trd_env: str = "REAL"
    futu_security_firm: str = ""
    futu_sim_acc_type: str = ""
    futu_currency: str = "USD"
    futu_acc_id: int = 0
    futu_acc_index: int = 0
    futu_is_encrypt: bool | None = None
    futu_history_symbol_7d_limit: int = 500
    telegram_bot_token: str = ""
    telegram_allowed_users: str = ""
    finnhub_api_key: str = ""
    finnhub_min_interval_seconds: float = 1.2
    finnhub_max_retries: int = 3
    finnhub_rate_limit_backoff_seconds: float = 2.0
    alpha_vantage_api_key: str = ""
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""
    fmp_api_key: str = ""
    twelvedata_api_key: str = ""
    market_data_provider_priority: str = "local_cache,futu,alpaca,stooq,fmp,twelvedata,alphavantage,yfinance_dev"
    market_data_timeout_seconds: float = 8.0
    market_data_alpha_vantage_daily_limit: int = 25
    market_data_fmp_daily_limit: int = 250
    market_data_twelvedata_daily_limit: int = 800
    market_data_yfinance_dev_enabled: bool = False

    @property
    def is_paper(self) -> bool:
        return self.mode.lower() != "live" or not self.allow_live_trading


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    return default if value in (None, "") else float(value)


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    return default if value in (None, "") else int(value)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    if Path.cwd() != PROJECT_ROOT:
        load_dotenv(Path.cwd() / ".env", override=False)

    db_value = os.getenv("INVEST_AGENT_DB_PATH")
    db_path = Path(db_value) if db_value else PROJECT_ROOT / "data" / "invest_agent.db"
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path

    return Settings(
        db_path=db_path,
        host=os.getenv("INVEST_AGENT_HOST", "127.0.0.1"),
        port=_int_env("INVEST_AGENT_PORT", 8788),
        mode=os.getenv("INVEST_AGENT_MODE", "paper"),
        max_trade_notional_usd=_float_env("INVEST_AGENT_MAX_TRADE_NOTIONAL_USD", 5000.0),
        max_position_pct=_float_env("INVEST_AGENT_MAX_POSITION_PCT", 35.0),
        approval_ttl_minutes=_int_env("INVEST_AGENT_APPROVAL_TTL_MINUTES", 15),
        max_price_drift_bps=_float_env("INVEST_AGENT_MAX_PRICE_DRIFT_BPS", 30.0),
        min_confidence=_float_env("INVEST_AGENT_MIN_CONFIDENCE", 0.35),
        allow_live_trading=_bool_env("INVEST_AGENT_ALLOW_LIVE_TRADING", False),
        watchlist_symbols=os.getenv("INVEST_AGENT_WATCHLIST", "AAPL,MSFT,NVDA,GOOGL"),
        market_context_symbols=os.getenv(
            "INVEST_AGENT_MARKET_CONTEXT_SYMBOLS",
            "SPY,QQQ,IWM,DIA,VIXY,TLT,GLD,USO,XLK,XLF,XLE,XLV,XLY,XLP,XLI,XLU,XLB,XLRE,SMH,SOXX,IGV,XBI,IBB,ITA,KRE,SCHD,SGOV,BIL",
        ),
        draft_notional_usd=_float_env("INVEST_AGENT_DRAFT_NOTIONAL_USD", 1000.0),
        draft_max_candidates=_int_env("INVEST_AGENT_DRAFT_MAX_CANDIDATES", 3),
        draft_min_score=_int_env("INVEST_AGENT_DRAFT_MIN_SCORE", 7),
        signal_buy_threshold=_int_env("INVEST_AGENT_SIGNAL_BUY_THRESHOLD", 70),
        signal_sell_threshold=_int_env("INVEST_AGENT_SIGNAL_SELL_THRESHOLD", 65),
        signal_watch_threshold=_int_env("INVEST_AGENT_SIGNAL_WATCH_THRESHOLD", 45),
        signal_max_per_run=_int_env("INVEST_AGENT_SIGNAL_MAX_PER_RUN", 8),
        signal_expiry_hours=_int_env("INVEST_AGENT_SIGNAL_EXPIRY_HOURS", 24),
        signal_duplicate_cooldown_minutes=_int_env("INVEST_AGENT_SIGNAL_DUPLICATE_COOLDOWN_MINUTES", 240),
        paper_advice_committee_freshness_minutes=_int_env("INVEST_AGENT_PAPER_ADVICE_COMMITTEE_FRESHNESS_MINUTES", 240),
        news_lookback_days=_int_env("INVEST_AGENT_NEWS_LOOKBACK_DAYS", 3),
        news_max_per_symbol=_int_env("INVEST_AGENT_NEWS_MAX_PER_SYMBOL", 5),
        news_max_symbols=_int_env("INVEST_AGENT_NEWS_MAX_SYMBOLS", 12),
        news_timeout_seconds=_float_env("INVEST_AGENT_NEWS_TIMEOUT_SECONDS", 5.0),
        google_news_fallback_enabled=_bool_env("INVEST_AGENT_GOOGLE_NEWS_FALLBACK_ENABLED", True),
        sec_user_agent=os.getenv("INVEST_AGENT_SEC_USER_AGENT", "AIinvestmentAgent/0.1 local-use contact@example.com"),
        sec_forms=os.getenv("INVEST_AGENT_SEC_FORMS", "10-K,10-Q,8-K,20-F,6-K"),
        sec_max_filings_per_symbol=_int_env("INVEST_AGENT_SEC_MAX_FILINGS_PER_SYMBOL", 5),
        sec_timeout_seconds=_float_env("INVEST_AGENT_SEC_TIMEOUT_SECONDS", 8.0),
        primary_source_lookback_days=_int_env("INVEST_AGENT_PRIMARY_SOURCE_LOOKBACK_DAYS", 45),
        research_gate_required=_bool_env("INVEST_AGENT_RESEARCH_GATE_REQUIRED", True),
        research_gate_max_verified_age_days=_int_env("INVEST_AGENT_RESEARCH_GATE_MAX_VERIFIED_AGE_DAYS", 120),
        ir_rss_feeds=os.getenv("INVEST_AGENT_IR_RSS_FEEDS", ""),
        autonomy_cycle_seconds=_int_env("INVEST_AGENT_AUTONOMY_CYCLE_SECONDS", 900),
        autonomy_create_proposals=_bool_env("INVEST_AGENT_AUTONOMY_CREATE_PROPOSALS", True),
        autonomy_refresh_futu=_bool_env("INVEST_AGENT_AUTONOMY_REFRESH_FUTU", True),
        autonomy_refresh_news=_bool_env("INVEST_AGENT_AUTONOMY_REFRESH_NEWS", True),
        autonomy_refresh_primary_sources=_bool_env("INVEST_AGENT_AUTONOMY_REFRESH_PRIMARY_SOURCES", True),
        autonomy_refresh_fundamentals=_bool_env("INVEST_AGENT_AUTONOMY_REFRESH_FUNDAMENTALS", True),
        autonomy_primary_every_cycles=_int_env("INVEST_AGENT_AUTONOMY_PRIMARY_EVERY_CYCLES", 4),
        autonomy_fundamentals_every_cycles=_int_env("INVEST_AGENT_AUTONOMY_FUNDAMENTALS_EVERY_CYCLES", 16),
        autonomy_proposal_cooldown_minutes=_int_env("INVEST_AGENT_AUTONOMY_PROPOSAL_COOLDOWN_MINUTES", 240),
        futu_host=os.getenv("FUTU_HOST", "127.0.0.1"),
        futu_monitor_port=_int_env("FUTU_MONITOR_PORT", 11111),
        futu_trade_port=_int_env("FUTU_TRADE_PORT", 11112),
        futu_trade_password=os.getenv("FUTU_TRADE_PASSWORD", ""),
        futu_read_enabled=_bool_env("FUTU_READ_ENABLED", False),
        futu_trd_market=os.getenv("FUTU_TRD_MARKET", "US").strip().upper(),
        futu_trd_env=os.getenv("FUTU_TRD_ENV", "REAL").strip().upper(),
        futu_security_firm=os.getenv("FUTU_SECURITY_FIRM", "").strip(),
        futu_sim_acc_type=os.getenv("FUTU_SIM_ACC_TYPE", "").strip().upper(),
        futu_currency=os.getenv("FUTU_CURRENCY", "USD").strip().upper(),
        futu_acc_id=_int_env("FUTU_ACC_ID", 0),
        futu_acc_index=_int_env("FUTU_ACC_INDEX", 0),
        futu_is_encrypt=_optional_bool_env("FUTU_IS_ENCRYPT"),
        futu_history_symbol_7d_limit=_int_env("FUTU_HISTORY_SYMBOL_7D_LIMIT", 500),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_allowed_users=os.getenv("TELEGRAM_ALLOWED_USERS", ""),
        finnhub_api_key=os.getenv("FINNHUB_API_KEY", ""),
        finnhub_min_interval_seconds=_float_env("INVEST_AGENT_FINNHUB_MIN_INTERVAL_SECONDS", 1.2),
        finnhub_max_retries=_int_env("INVEST_AGENT_FINNHUB_MAX_RETRIES", 3),
        finnhub_rate_limit_backoff_seconds=_float_env("INVEST_AGENT_FINNHUB_RATE_LIMIT_BACKOFF_SECONDS", 2.0),
        alpha_vantage_api_key=os.getenv("ALPHA_VANTAGE_API_KEY", ""),
        alpaca_api_key=os.getenv("ALPACA_API_KEY", ""),
        alpaca_secret_key=os.getenv("ALPACA_SECRET_KEY", ""),
        fmp_api_key=os.getenv("FMP_API_KEY", ""),
        twelvedata_api_key=os.getenv("TWELVEDATA_API_KEY", ""),
        market_data_provider_priority=os.getenv(
            "INVEST_AGENT_MARKET_DATA_PROVIDER_PRIORITY",
            "local_cache,futu,alpaca,stooq,fmp,twelvedata,alphavantage,yfinance_dev",
        ),
        market_data_timeout_seconds=_float_env("INVEST_AGENT_MARKET_DATA_TIMEOUT_SECONDS", 8.0),
        market_data_alpha_vantage_daily_limit=_int_env("INVEST_AGENT_ALPHA_VANTAGE_DAILY_LIMIT", 25),
        market_data_fmp_daily_limit=_int_env("INVEST_AGENT_FMP_DAILY_LIMIT", 250),
        market_data_twelvedata_daily_limit=_int_env("INVEST_AGENT_TWELVEDATA_DAILY_LIMIT", 800),
        market_data_yfinance_dev_enabled=_bool_env("INVEST_AGENT_YFINANCE_DEV_ENABLED", False),
    )


def _optional_bool_env(name: str) -> bool | None:
    value = os.getenv(name)
    if value in (None, ""):
        return None
    return value.strip().lower() in {"1", "true", "yes", "on"}
