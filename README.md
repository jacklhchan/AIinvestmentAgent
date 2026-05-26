# AI Investment Agent

本專案是依照 `deep-research-report-2.md` 落地的本機 MVP：Hermes Agent 負責對話與研究外殼，交易控制平面負責資料、proposal、approval、risk check、audit 與紙上交易。預設模式是 `paper`，不會送出實盤訂單。

## 已包含

- FastAPI 本機控制平面：`http://127.0.0.1:8788`
- SQLite 狀態儲存：proposal、approval、paper executions、portfolio、quotes、news、fundamentals、research goals、evidence rows、theses、thesis updates、catalysts、catalyst reviews、earnings reviews、audit events
- 風控/審批狀態機：TTL、重複單、notional、confidence、price drift revalidation
- Hermes stdio MCP server：讓 Hermes 讀 portfolio/news/proposals 並建立/批准/拒絕 proposal
- Futu OpenD read-only refresh：讀取資金、持倉與持倉 quote snapshot，不 unlock trade
- Market/news ingestion：從 watchlist 抓取 GDELT，並在有 `FINNHUB_API_KEY` 時補 Finnhub company news
- SEC/IR primary-source ingestion：SEC EDGAR filings 預設可用；公司 IR RSS 可透過 `.env` 設定
- SEC XBRL companyfacts 基本面快照：解析收入、淨收入、現金流、資產、負債、權益與 diluted EPS，並附上 YoY 變化
- Research Goal / Evidence Ledger：每個自動草擬的 proposal 先建立 research-only goal，寫入 claims、criteria 與 evidence rows，再通過 evidence gate 才能建立待審批 proposal
- Thesis Tracker：保存每個標的的長期 thesis、pillars、invalidating risks、conviction 與 research-goal-backed thesis updates
- Catalyst Calendar：保存 earnings / investor day / macro 等事件，並在 proposal 前套用 high/medium-impact catalyst invariant
- Earnings Review：用本機 SEC companyfacts snapshot 計算財報 YoY 指標、cashflow quality、thesis delta，並可完成 earnings catalyst 的 post-event review
- Event replay：把 portfolio、quotes、news/evidence、fundamental snapshots 匯出成 JSONL，再重播用於信號驗證
- Hermes proposal drafting：根據 watchlist 新聞產生結構化 draft，可選擇送入既有風控與審批狀態機
- Safe autonomy loop：定時刷新 Futu/新聞/SEC/基本面並建立 paper-only proposal，所有交易仍需人工批准
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
INVEST_AGENT_RESEARCH_GATE_REQUIRED=true
INVEST_AGENT_RESEARCH_GATE_MAX_VERIFIED_AGE_DAYS=120
INVEST_AGENT_IR_RSS_FEEDS=
FINNHUB_API_KEY=
```

手動刷新與草擬：

```bash
source .venv/bin/activate
python -m invest_agent.cli news-refresh
python -m invest_agent.cli draft-proposals
```

Dashboard 的 `刷新市場新聞` 會把最新新聞寫入本機 store；`草擬並送風控` 會先建立 research goal / evidence ledger，再把 evidence gate 通過的 draft 轉成現有 proposal，然後由風控決定 `PENDING` 或 `RISK_REJECTED`。如果該 symbol 有 active thesis，draft 會附上 `thesis_id`、把 thesis tracker reference 寫入 evidence，並在 triggered risk / broken pillar 時降低信心與加入 counter-evidence。如果只有新聞線索、沒有 SEC/IR primary-source 或 SEC companyfacts 這類 verified evidence，系統會保留研究紀錄但不建立待審批 proposal。即使通過審批，仍然只做 paper execution。

## Research Goals + Evidence Ledger

這一層是吸收 Anthropic financial-services 的 thesis discipline 與 Vibe-Trading 的 Research Goal runtime 概念後，先落地在本機控制平面的安全版本。它只寫研究表，不會批准或執行交易。

- `research_goals`：保存 objective、risk tier、claims、acceptance criteria、status 與 gate summary。
- `research_evidence`：保存來源、URL、資料日期、retrieved time、freshness、verification status、source-verified provenance、confidence、caveat 與反證關聯。
- Proposal draft 會自動建立一個 research-only goal；必須同時具備方向性市場/news evidence 與 source-verified primary-source/fundamentals evidence，才允許 `create_proposals=true` 建立 proposal。
- 所有入口建立 `PENDING` proposal 時，必須有通過 gate 的 `research_goal_id`，或明確 `manual_override_reason`。
- Hermes 只能透過 MCP 建立/讀取研究目標與新增 unverified evidence rows；MCP 文字不能把自己標成 source-verified，也不能寫 execution/order tables。
- 每個 proposal 會保存 `research_goal_id` / `manual_override_reason` 與 `evidence_hash`，方便之後審計。

REST API：

```bash
curl http://127.0.0.1:8788/api/research-goals
curl -X POST http://127.0.0.1:8788/api/research-goals \
  -H "Content-Type: application/json" \
  -d '{"symbol":"AAPL","objective":"Evaluate whether AAPL evidence supports a watchlist proposal."}'
```

Dashboard 會顯示 `研究目標與證據帳本`，包含 gate 狀態、證據數、claims 與 criteria。

相關設定：

```bash
INVEST_AGENT_RESEARCH_GATE_REQUIRED=true
INVEST_AGENT_RESEARCH_GATE_MAX_VERIFIED_AGE_DAYS=120
```

## Thesis Tracker

Thesis Tracker 是 proposal 之前的長期記憶層。它不批准交易，也不執行交易；它回答的是「這次 evidence 是支持、削弱、中性，還是推翻原本 thesis」。

- `theses`：保存 symbol、side、thesis statement、status、conviction、target price、stop-loss / invalidation trigger。
- `thesis_pillars`：保存 thesis 的支柱及狀態。
- `thesis_risks`：保存 invalidating risks 與對應失效條件。
- `thesis_updates`：把 research goal、evidence hash、impact、summary 與 action bias 連回 thesis。
- MCP 建立的 thesis 預設 `status=watch`、`human_confirmed=false`，只作 research context；Dashboard/REST 人類建立的 thesis 才能被 proposal draft 自動引用。
- 若 proposal 指向 `thesis_id`，`InvestmentService.create_proposal()` 會拒絕 invalidated / archived thesis、neutral watch thesis、triggered invalidation risk、broken pillar 產生 `PENDING` proposal。

REST API：

```bash
curl http://127.0.0.1:8788/api/theses
curl -X POST http://127.0.0.1:8788/api/theses \
  -H "Content-Type: application/json" \
  -d '{"symbol":"AAPL","thesis_statement":"AAPL thesis requires primary-source evidence before any proposal.","pillars":[{"text":"Revenue and cash flow support the thesis"}],"risks":[{"text":"Growth weakens after filings","invalidation_condition":"SEC/IR evidence contradicts the core thesis"}]}'
```

CLI：

```bash
python -m invest_agent.cli list-theses
```

Dashboard 會顯示 `投資論點`，並提供 `新增投資論點` 表單。

## Catalyst Calendar

Catalyst Calendar 是 proposal 前的事件風險層，不是自動交易訊號。它用來追蹤 earnings、investor day、product、regulatory、conference、macro 等事件，並在 proposal 建立時做額外風控。

- `catalysts`：保存 symbol、event type、event date、time hint、expected impact、source/provenance、status、linked thesis/research goal、actual outcome、thesis delta。
- `catalyst_reviews`：保存 post-event review、research goal、evidence hash、thesis delta、action bias。
- 高影響 catalyst 前 48 小時：沒有 `manual_override_reason` 時，BUY/SELL proposal 不會變成 `PENDING`。
- 中影響 catalyst 前 24 小時：允許 proposal，但加入 warning 與 confidence haircut；若 haircut 後低於最低信心，會被風控拒絕。
- 事件完成但還沒有 post-event review 時，最近 7 天內的 high/medium-impact catalyst 會阻止新 pending proposal，除非人類手動覆寫。
- `symbol=null` 且 `event_type=macro` 的 high/medium-impact event 會視為 portfolio-wide macro catalyst，套用到每個 symbol 的 proposal 前檢查。
- MCP 建立的 catalyst 永遠是 unverified；只有官方來源 ingestor 或 dashboard human confirmation 才能成為 source/human verified。

REST API：

```bash
curl http://127.0.0.1:8788/api/catalysts/upcoming?days=14
curl -X POST http://127.0.0.1:8788/api/catalysts \
  -H "Content-Type: application/json" \
  -d '{"symbol":"AAPL","event_type":"earnings","title":"AAPL earnings","event_date":"2026-06-01T20:00:00Z","expected_impact":"high"}'
```

CLI：

```bash
python -m invest_agent.cli list-catalysts --days 14
python -m invest_agent.cli catalyst-preview --days 7
```

Dashboard 會顯示 `催化事件`，並提供 `新增催化事件` 表單。

## Earnings Review

Earnings Review 是事件後的財報檢討層，不是自動交易訊號。它讀取本機 SEC companyfacts snapshot，計算 revenue、net income、operating income、operating cash flow、diluted EPS 的 YoY 變化，並用 deterministic scoring 產生 `thesis_delta`。

- `earnings_reviews`：保存 symbol、period、catalyst/research/thesis link、YoY 指標、cashflow quality、thesis delta、action bias、evidence hash。
- `run_earnings_review` 會建立或沿用 research goal，並寫入 source-verified `sec-companyfacts` evidence。
- 如果 review 連到 completed earnings catalyst，會建立 `catalyst_review`，解除「事件完成但未 review」的 proposal block。
- MCP 執行 earnings review 只產生 research artifact；`invalidates` / `exit` / `trim` / `block_new_proposal` 這類 severe delta 需要 human confirmation 才能正式套用到 thesis。

REST API：

```bash
curl http://127.0.0.1:8788/api/earnings-reviews
curl -X POST http://127.0.0.1:8788/api/earnings-reviews/run \
  -H "Content-Type: application/json" \
  -d '{"symbol":"AAPL","refresh_fundamentals":false}'
```

CLI：

```bash
python -m invest_agent.cli earnings-review --symbol AAPL
python -m invest_agent.cli list-earnings-reviews --symbol AAPL
```

Dashboard 會顯示 `財報檢討`，並提供 `執行財報檢討` 表單。

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

## Safe Autonomy Loop

自治層會跑一個安全循環：刷新只讀資料、更新新聞與 primary sources、解析 SEC companyfacts、草擬交易提案，並在 evidence gate 與 cooldown 都允許時建立 `PENDING` proposal。它不會批准 proposal、不會 unlock Futu、不會送 live order。

```bash
INVEST_AGENT_AUTONOMY_CYCLE_SECONDS=900
INVEST_AGENT_AUTONOMY_CREATE_PROPOSALS=true
INVEST_AGENT_AUTONOMY_REFRESH_FUTU=true
INVEST_AGENT_AUTONOMY_REFRESH_NEWS=true
INVEST_AGENT_AUTONOMY_REFRESH_PRIMARY_SOURCES=true
INVEST_AGENT_AUTONOMY_REFRESH_FUNDAMENTALS=true
INVEST_AGENT_AUTONOMY_PRIMARY_EVERY_CYCLES=4
INVEST_AGENT_AUTONOMY_FUNDAMENTALS_EVERY_CYCLES=16
INVEST_AGENT_AUTONOMY_PROPOSAL_COOLDOWN_MINUTES=240
```

手動跑一次或查狀態：

```bash
python -m invest_agent.cli autonomy-once
python -m invest_agent.cli autonomy-status
python -m invest_agent.cli autonomy-loop
```

macOS 常駐範例在 `deploy/launchd/com.local.invest-agent-scheduler.plist`。Dashboard 也有 `執行自治循環` 按鈕與 `安全自治狀態` 面板。

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
        - list_research_goals
        - create_research_goal
        - add_research_evidence
        - get_research_goal_snapshot
        - create_thesis
        - list_theses
        - get_thesis_snapshot
        - add_thesis_update_from_research_goal
        - list_catalysts
        - create_catalyst
        - get_catalyst_snapshot
        - complete_catalyst_with_research_goal
        - run_earnings_review
        - list_earnings_reviews
        - get_earnings_review
        - apply_earnings_review_to_thesis
        - get_safe_autonomy_status
        - run_safe_autonomy_cycle
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
請列出 AAPL 的 active thesis，並說明最近 research goal 對 thesis 是 strengthen 還是 weaken。
請列出未來 14 天 high-impact catalysts，並指出哪些 symbol 不應該建立新 proposal。
請用本機 SEC companyfacts 對 AAPL 跑 earnings review，說明 thesis_delta 與 evidence_hash，但不要建立或批准 proposal。
請查看 safe autonomy 狀態，如有需要執行一次自治循環，但不要批准任何 proposal。
```

## 安全邊界

第一版只做紙上交易紀錄。即使透過 Hermes 呼叫 `approve_trade_proposal`，也只會建立本機 `paper_execution`，不會 unlock Futu OpenD 或下實盤單。實盤接通前應先補上：

- macOS Keychain secret loading
- Futu 雙 OpenD 實例
- 下單前持倉/現金/open order/價格 revalidation
- order/deal push 對帳
- 小額 live smoke test
