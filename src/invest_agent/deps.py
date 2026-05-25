from __future__ import annotations

from functools import lru_cache

from .config import get_settings
from .demo_data import seed_demo_data
from .services import InvestmentService
from .store import Store


@lru_cache(maxsize=1)
def get_store() -> Store:
    store = Store(get_settings().db_path)
    seed_demo_data(store, force=False)
    return store


@lru_cache(maxsize=1)
def get_service() -> InvestmentService:
    return InvestmentService(get_settings(), get_store())
