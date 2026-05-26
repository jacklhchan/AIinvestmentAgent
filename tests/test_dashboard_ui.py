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
    assert "刷新 SEC Fundamentals" in response.text
    assert "SEC 基本面快照" in response.text
    assert "執行自治循環" in response.text
    assert "安全自治狀態" in response.text
    assert "研究目標與證據帳本" in response.text
    assert "投資論點" in response.text
    assert "新增投資論點" in response.text
    assert "催化事件" in response.text
    assert "新增催化事件" in response.text
    assert "財報檢討" in response.text
    assert "執行財報檢討" in response.text
    assert "研究執行紀錄" in response.text
    assert "交易行為" in response.text
    assert "匯入交易日誌" in response.text
    assert "影子帳戶" in response.text
    assert "反事實報告" in response.text
    assert "操作紀錄" in response.text
