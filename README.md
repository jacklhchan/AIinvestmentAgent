# AI Investment Agent

本專案是依照 `deep-research-report-2.md` 落地的本機 MVP：Hermes Agent 負責對話與研究外殼，交易控制平面負責資料、proposal、approval、risk check、audit 與紙上交易。預設模式是 `paper`，不會送出實盤訂單。

## 已包含

- FastAPI 本機控制平面：`http://127.0.0.1:8788`
- SQLite 狀態儲存：proposal、approval、paper executions、portfolio、quotes、news、audit events
- 風控/審批狀態機：TTL、重複單、notional、confidence、price drift revalidation
- Hermes stdio MCP server：讓 Hermes 讀 portfolio/news/proposals 並建立/批准/拒絕 proposal
- Futu OpenD read-only refresh：讀取資金、持倉與持倉 quote snapshot，不 unlock trade
- Market/news ingestion：從 watchlist 抓取 GDELT，並在有 `FINNHUB_API_KEY` 時補 Finnhub company news
- SEC/IR primary-source ingestion：SEC EDGAR filings 預設可用；公司 IR RSS 可透過 `.env` 設定
- SEC XBRL companyfacts 基本面快照：解析收入、淨收入、現金流、資產、負債、權益與 diluted EPS，並附上 YoY 變化
- Event replay：把 portfolio、quotes、news/evidence、fundamental snapshots 匯出成 JSONL，再重播用於信號驗證
- Hermes proposal drafting：根據 watchlist 新聞產生結構化 draft，可選擇送入既有風控與審批狀態機
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

## Market News + Proposal Drafting

這一段對齊 design plan 的中迴圈：新聞先入庫，Hermes/Codex 只產生結構化提案草稿，真正 proposal 仍要經過本機 policy engine。預設會先試 GDELT，若來源逾時或無結果，會用 Google News RSS 作為可用性 fallback；有 `FINNHUB_API_KEY` 時會再補 Finnhub company news。

```bash
INVEST_AGENT_WATCHLIST=AAPL,MSFT,NVDA,GOOGL
INVEST_AGENT_DRAFT_NOTIONAL_USD=1000
INVEST_AGENT_DRAFT_MAX_CANDIDATES=3
INVEST_AGENT_NEWS_LOOKBACK_DAYS=3
INVEST_AGENT_NEWS_MAX_PER_SYMBOL=5
INVEST_AGENT_NEWS_MAX_SYMBOLS=6
INVEST_AGENT_NEWS_TIMEOUT_SECONDS=5
INVEST_AGENT_GOOGLE_NEWS_FALLBACK_ENABLED=true
INVEST_AGENT_SEC_USER_AGENT=AIinvestmentAgent/0.1 local-use contact@example.com
INVEST_AGENT_SEC_FORMS=10-K,10-Q,8-K,20-F,6-K
INVEST_AGENT_SEC_MAX_FILINGS_PER_SYMBOL=5
INVEST_AGENT_SEC_TIMEOUT_SECONDS=8
INVEST_AGENT_PRIMARY_SOURCE_LOOKBACK_DAYS=45
INVEST_AGENT_IR_RSS_FEEDS=
FINNHUB_API_KEY=
```

手動刷新與草擬：

```bash
source .venv/bin/activate
python -m invest_agent.cli news-refresh
python -m invest_agent.cli draft-proposals
```

Dashboard 的 `刷新市場新聞` 會把最新新聞寫入本機 store；`草擬並送風控` 會把 draft 轉成現有 proposal，然後由風控決定 `PENDING` 或 `RISK_REJECTED`。即使通過審批，仍然只做 paper execution。

## SEC/IR Primary Sources + Event Replay

SEC EDGAR ingestion 使用官方 `data.sec.gov/submissions/CIK##########.json` filing history，把 `10-K`、`10-Q`、`8-K`、`20-F`、`6-K` 等 filings 寫入本機 evidence store，來源標記為 `SEC EDGAR` / `primary-source`。公司 IR RSS 可用 `INVEST_AGENT_IR_RSS_FEEDS` 加入，例如：

```bash
INVEST_AGENT_IR_RSS_FEEDS=AAPL=https://example.com/aapl-ir.xml;MSFT=https://example.com/msft-ir.xml
```

手動刷新與重播：

```bash
python -m invest_agent.cli primary-refresh
python -m invest_agent.cli fundamentals-refresh
python -m invest_agent.cli event-export --path artifacts/replay/latest-events.jsonl
python -m invest_agent.cli event-replay --path artifacts/replay/latest-events.jsonl
```

Proposal draft 仍只由 directional news 觸發；SEC/IR primary-source evidence 會被附加作為背景證據，不會單靠 filing 自動產生交易方向。

## SEC Company Facts Fundamentals

`fundamentals-refresh` 會使用 SEC 官方 `companyfacts` XBRL JSON，按 CIK 抓取 watchlist 的基本面 snapshot。資料會寫入本機 SQLite `fundamentals` table，並在 proposal draft 裡作為 evidence / counter-evidence 使用：

- `revenue`
- `net_income`
- `operating_income`
- `operating_cash_flow`
- `assets`
- `liabilities`
- `equity`
- `eps_diluted`

如果 revenue、net income 或 operating cash flow 的 YoY 變化與新聞方向相反，draft 會降低信心分數並把反證寫入 `counter_evidence`。這仍然不會自動建立實盤交易，只是讓 Hermes/Codex 在審閱 proposal 時有更硬的 primary-source context。

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
        - get_watchlist_symbols
        - get_news_digest
        - refresh_market_news
        - refresh_primary_source_filings
        - refresh_sec_company_facts
        - get_fundamental_snapshot
        - export_event_replay_file
        - replay_event_file
        - draft_trade_proposals_from_watchlist
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
請刷新 AAPL 的 SEC companyfacts，然後說明收入、淨收入和 operating cash flow 是否支持最新 draft。
```

## 安全邊界

第一版只做紙上交易紀錄。即使透過 Hermes 呼叫 `approve_trade_proposal`，也只會建立本機 `paper_execution`，不會 unlock Futu OpenD 或下實盤單。實盤接通前應先補上：

- macOS Keychain secret loading
- Futu 雙 OpenD 實例
- 下單前持倉/現金/open order/價格 revalidation
- order/deal push 對帳
- 小額 live smoke test
