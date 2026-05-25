from __future__ import annotations

from fastapi.testclient import TestClient

from invest_agent.api import app


def test_dashboard_is_traditional_chinese_with_data_provenance() -> None:
    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert 'lang="zh-Hant"' in response.text
    assert "投資代理控制台" in response.text
    assert "資料來源與刷新狀態" in response.text
    assert "刷新富途 OpenD" in response.text
    assert "刷新 SEC/IR" in response.text
    assert "操作紀錄" in response.text
