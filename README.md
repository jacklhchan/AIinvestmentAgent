# AI Investment Agent

本專案是依照 `deep-research-report-2.md` 落地的本機 MVP：Hermes Agent 負責對話與研究外殼，交易控制平面負責資料、proposal、approval、risk check、audit 與紙上交易。預設模式是 `paper`，不會送出實盤訂單。

## 已包含

- FastAPI 本機控制平面：`http://127.0.0.1:8788`
- SQLite 狀態儲存：proposal、approval、paper executions、portfolio、quotes、news、audit events
- 風控/審批狀態機：TTL、重複單、notional、confidence、price drift revalidation
- Hermes stdio MCP server：讓 Hermes 讀 portfolio/news/proposals 並建立/批准/拒絕 proposal
- Futu OpenD read-only refresh：讀取資金、持倉與持倉 quote snapshot，不 unlock trade
- 繁體中文本機 dashboard：可看持倉、新聞、pending proposal、資料來源、刷新時間、audit trail，並在瀏覽器批准/拒絕
- launchd 與 Hermes config 範例

## 快速啟動

```bash
cd /Users/apple/Documents/AIinvestmentAgent
/opt/homebrew/bin/python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev,futu]"
cp .env.example .env
python -m invest_agent.cli seed
python -m invest_agent.api
```

開啟 `http://127.0.0.1:8788`。介面預設為繁體中文，並會用來源 badge 區分 `Demo` 與 `富途 OpenD` 資料。

## Futu OpenD Read-Only

從你目前的 OpenD 畫面來看，API port 是 `11111`，已 connected，交易仍 locked。這個 MVP 只使用 read-only API：

```bash
FUTU_READ_ENABLED=true
FUTU_HOST=127.0.0.1
FUTU_MONITOR_PORT=11111
FUTU_TRD_MARKET=US
FUTU_CURRENCY=USD
```

刷新本機資料：

```bash
source .venv/bin/activate
python -m invest_agent.cli futu-refresh
```

或者開 dashboard 後按 `Refresh Futu`。這只會呼叫 `accinfo_query`、`position_list_query`、`get_market_snapshot`，不會呼叫 `unlock_trade` 或任何下單 API。

## Hermes + Codex LLM 設定

Hermes 官方文件目前支援 `OpenAI Codex` provider，可用 `hermes model` 進行 ChatGPT OAuth。這個專案預設讓 Hermes 使用 Codex model，再透過 stdio MCP server 連到本機投資控制平面。

安裝 Hermes 後，把以下片段合併到 `~/.hermes/config.yaml`：

```yaml
model:
  provider: "openai-codex"
  default: "gpt-5.2-codex"

agent:
  reasoning_effort: "high"
  tool_use_enforcement: "auto"

mcp_servers:
  invest_agent:
    command: "/Users/apple/Documents/AIinvestmentAgent/.venv/bin/python"
    args: ["-m", "invest_agent.mcp_server"]
    timeout: 30
    supports_parallel_tool_calls: false
    tools:
      include:
        - get_portfolio_snapshot
        - get_watchlist_quotes
        - get_news_digest
        - get_futu_connection_status
        - refresh_futu_readonly_snapshot
        - list_pending_proposals
        - create_trade_proposal
        - approve_trade_proposal
        - reject_trade_proposal
      resources: false
      prompts: false
```

如果 `hermes model` 顯示你的帳戶有更新的 Codex model，可用互動選單覆蓋 `model.default`，MCP 設定不用改。

在 Hermes 裡可以問：

```text
請用 invest_agent 工具列出 pending proposals，並解釋每個提案的風險檢查。
```

## 安全邊界

第一版只做紙上交易紀錄。即使透過 Hermes 呼叫 `approve_trade_proposal`，也只會建立本機 `paper_execution`，不會 unlock Futu OpenD 或下實盤單。實盤接通前應先補上：

- macOS Keychain secret loading
- Futu 雙 OpenD 實例
- 下單前持倉/現金/open order/價格 revalidation
- order/deal push 對帳
- 小額 live smoke test
