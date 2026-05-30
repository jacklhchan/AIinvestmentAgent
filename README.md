# AI Investment Agent

本專案是依照 `deep-research-report-2.md` 落地的本機 MVP：Hermes Agent 負責對話與研究外殼，交易控制平面負責資料、proposal、approval、risk check、audit 與紙上交易。預設模式是 `paper`，不會送出實盤訂單。

## 已包含

- FastAPI 本機控制平面：`http://127.0.0.1:8788`
- AI Advisor Brief：首頁一鍵自動整理 portfolio、proposal、research goals、theses、catalysts、earnings reviews、behavior / shadow reports，直接輸出 research-only 建議
- Market Context Lens：獨立追蹤 index、sector、theme、volatility、rates、gold、oil 與 cash-like ETF，只作市場背景與風險提醒，不直接產生 proposal
- Opportunity Radar：回答「今晚市場有無值得留意的新機會？」這類 broad question，輸出 evidence-ranked WATCH / RESEARCH / BLOCKED / AVOID cards，不直接建立 proposal
- Proactive Paper Signal Copilot：用 deterministic feature scoring 主動產生 `BUY_SIGNAL` / `SELL_SIGNAL` / `ADD_SIGNAL` / `REDUCE_SIGNAL` / `WATCH` / `BLOCKED`，只可升級成 paper proposal，不能批准或下實盤單
- Canonical Accounting + IPS foundation：由交易日誌同步成 accounting transactions、FIFO tax lots、accounting snapshot，並把確認後的 Advisor Profile 固化成 Investor Policy Statement
- SQLite 狀態儲存：signals、signal runs、proposal、approval、paper executions、portfolio、quotes、news、fundamentals、research goals、evidence rows、theses、thesis updates、catalysts、catalyst reviews、earnings reviews、research run cards、trade journal、behavior reports、shadow account、audit events
- 風控/審批狀態機：TTL、重複單、notional、confidence、price drift revalidation
- Hermes daily MCP surface：日常 Telegram 只暴露 high-level Advisor/Profile/Committee tools；full study / committee 會先做受控 evidence hydration，再把 frozen data pack 交給 committee
- Futu OpenD read-only refresh：讀取資金、持倉與持倉 quote snapshot，不 unlock trade
- Market/news ingestion：從 watchlist 抓取 GDELT，並在有 `FINNHUB_API_KEY` 時補 Finnhub company news
- SEC/IR primary-source ingestion：SEC EDGAR filings 預設可用；公司 IR RSS 可透過 `.env` 設定
- SEC XBRL companyfacts 基本面快照：解析收入、淨收入、現金流、資產、負債、權益與 diluted EPS，並附上 YoY 變化
- Research Goal / Evidence Ledger：每個自動草擬的 proposal 先建立 research-only goal，寫入 claims、criteria 與 evidence rows，再通過 evidence gate 才能建立待審批 proposal
- Thesis Tracker：保存每個標的的長期 thesis、pillars、invalidating risks、conviction 與 research-goal-backed thesis updates
- Catalyst Calendar：保存 earnings / investor day / macro 等事件，並在 proposal 前套用 high/medium-impact catalyst invariant
- Earnings Review：用本機 SEC companyfacts snapshot 計算財報 YoY 指標、cashflow quality、thesis delta，並可完成 earnings catalyst 的 post-event review
- Research Run Cards：為 earnings review、catalyst review、event replay 產生可 hash、可讀、可追溯的 JSON/Markdown artifact
- Trade Journal / Behavior Report：匯入 Futu/generic CSV、FIFO roundtrip pairing、勝率/盈虧比/回撤，以及處分效應、過度交易、追高、錨定診斷
- Shadow Account / Counterfactual Report：從 behavior report 抽取 deterministic draft rules，人工確認後檢查 early/late exits、thesis mismatch、ignored catalysts；research-only，不產生 proposal
- Event replay：把 portfolio、quotes、news/evidence、fundamental snapshots 匯出成 JSONL，再重播用於信號驗證
- Hermes proposal drafting：根據 watchlist 新聞產生結構化 draft，可選擇送入既有風控與審批狀態機
- Safe autonomy loop：定時刷新 Futu/新聞/SEC/基本面、產生 paper signals，並在 gate / cooldown 允許時建立 paper-only proposal，所有交易仍需人工批准
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

## AI Advisor Brief

Dashboard 第一屏的 `AI Advisor Brief` 是日常使用入口。按 `讓 Agent 自動分析` 後，系統會自動讀取目前狀態並整理建議：

- 待審批 proposal 與 warning。
- 48 小時內的高影響 catalyst 與事件後未 review 項目。
- 最近 earnings review 是否削弱 / 推翻 thesis。
- 最新 behavior report 的處分效應、過度交易、追高、錨定診斷。
- 最新 shadow report 的 thesis mismatch、ignored catalyst、early exit。
- 持倉是否缺少 human-confirmed active thesis。
- research goal 是否證據不足。
- broader market context 是否已有 quote/news 覆蓋。

這個 brief 可以自動建立輕量 behavior report，但仍是 research-only：不會建立交易 proposal、不會 approve proposal、不會 unlock Futu，也不會下實盤單。底下的 thesis / catalyst / earnings / journal / shadow 表單保留給人工覆核、修正與審計追溯。

Hermes MCP 也 exposes `get_advisor_brief`，所以你可以直接叫 Hermes「幫我看今天怎樣」，由它讀 brief 後用自然語言回答。

REST API：

```bash
curl http://127.0.0.1:8788/api/advisor/brief
curl -X POST http://127.0.0.1:8788/api/advisor/brief \
  -H "Content-Type: application/json" \
  -d '{"run_light_analysis":true,"max_items":8}'
```

## Hermes Advisor Mode

`Hermes Advisor Mode` 把底層 research goal、thesis、catalyst、committee、run card 與 policy 狀態包成三個高階入口：

- `POST /api/advisor/ask`：回答「而家應唔應該買 / 賣 AAPL？」這類自然語言問題，輸出 concise decision card。
- `ask_advisor` 會把「今晚市場有無值得留意的新機會？」這類 broad opportunity question 轉入內部 Opportunity Radar，輸出 Top WATCH / RESEARCH 與 BLOCKED / AVOID ideas。
- `POST /api/advisor/pulse/hourly`：每小時 urgent detector，只在 `watch` / `urgent` 時建議通知；SGT 00:00-07:00 quiet hours 內只有 urgent 會提示。
- `POST /api/advisor/briefs/pre-market` / `POST /api/advisor/briefs/post-close`：建立開市前 / 收市後 full advisor brief，並按 `ACTION / WATCH / BLOCKED / INFO` 分組 recommendations。

CLI：

```bash
python -m invest_agent.cli ask-advisor "Should I buy AAPL now?" --symbol AAPL
python -m invest_agent.cli opportunity-radar "今晚市場有無值得留意的新機會？"
python -m invest_agent.cli accounting-sync-from-journal
python -m invest_agent.cli accounting-snapshot
python -m invest_agent.cli ips
python -m invest_agent.cli advisor-pulse
python -m invest_agent.cli pre-market-brief
python -m invest_agent.cli post-close-brief
python -m invest_agent.cli advisor-scheduler-once
python -m invest_agent.cli advisor-scheduler-loop
```

Hermes daily MCP 只暴露 high-level Advisor / Profile / Committee tools：`ask_advisor`、`get_advisor_profile`、`suggest_advisor_profile_update`、`confirm_advisor_profile_update`、`run_hourly_advisor_pulse`、`run_pre_market_advisor_brief`、`run_post_close_advisor_brief`、`get_latest_advisor_brief`、`run_committee_review`、`list_committee_reviews`、`get_committee_review`。Advisor Orchestrator 會在本機背後讀取 portfolio、news、market regime、proposal context 與 research artifacts；committee tools 只產生 research-only memo / run card，不可建立 proposal、approve 或 execute trades。Hermes 日常不直接看到底層 tools。

當 Hermes 透過 `ask_advisor` 或 `run_committee_review` 做 full study / committee 時，系統會先對本機 unknown ticker 做受控 read-only hydration：Finnhub quote / company news、GDELT / Google News fallback、SEC EDGAR filings、SEC companyfacts。這些資料會先寫入本機 store，再凍結成 committee data pack；committee 不會自由瀏覽網頁，也不會把網絡文字直接升級成 proposal / approval。CLI 可用 `committee-review --refresh` 觸發同一條受控 hydration path。

Hermes snippets 分開兩種用途：`deploy/hermes/config.daily.snippet.yaml` 只包含上述 daily Advisor/Profile/Committee tools；`deploy/hermes/config.research-admin.snippet.yaml` 給本機研究/admin 工作使用，仍不包含 proposal approval / create / draft tools。舊的 `deploy/hermes/config.snippet.yaml` 保留為 daily-compatible alias。

`ask_advisor` 會保存 symbol resolution audit trail：`original_symbol`、`resolved_symbol` 與 `symbol_resolution_status`。`WHAT` / `IPO` / `AI` / `US` 這類 common uppercase token 不會被當成 ticker；SpaceX IPO / 未上市問題會回 research-only `blocked` decision card，不會進 proposal pipeline。

Advisor Profile update 必須先由 Hermes 建立 pending suggestion，再由你明確 confirm 後才會寫入版本化 profile。已確認 profile 會影響 Advisor 建議，例如不追高、核心 ETF 優先、單股上限、科技曝險上限、現金底線、IPO/options 偏好；pending suggestion 不會影響 advice。

安全邊界不變：Advisor output 只會寫 advisor question / pulse / brief / recommendation / run card，不會建立 `PENDING` proposal、不會 approve、不會 unlock Futu，也不會送 live order。若你仍想買賣，仍要走 `InvestmentService`、evidence gate、thesis/catalyst invariants、policy engine 與人工確認。

Opportunity Radar 是 Advisor Mode 的內部 service。它使用 market regime、sector/theme ETF、symbol-specific quote/news/fundamentals/thesis/catalyst、portfolio fit、risk gate、behavior/shadow evidence 六層資料做 deterministic scoring。輸出可以是 `watch`、`research`、`blocked`、`avoid` 或 `action_candidate`；`action_candidate` 仍只代表「可考慮建立研究 / proposal candidate」，不是買入指令。任何包含單股的 radar card 如果完全缺少 source-backed thesis / SEC / IR / fundamentals evidence，最多只能保留為 watch/research/block，不可升級為 `action_candidate`。

## Proactive Paper Signal Copilot

Signal Engine 是 Advisor / Opportunity Radar 之外的主動訊號層。它會每次 safe autonomy cycle 或手動執行時，針對 watchlist 產生 deterministic paper-trading signals：

- `BUY_SIGNAL` / `ADD_SIGNAL`：分數達到 `INVEST_AGENT_SIGNAL_BUY_THRESHOLD`，且 gate 沒有封鎖時，可由人類升級成 paper proposal。
- `SELL_SIGNAL` / `REDUCE_SIGNAL`：負向分數、thesis invalidation、持倉過重或 stop/risk rule 觸發時產生；仍需人類升級與批准。
- `WATCH` / `HOLD`：有資訊但分數不足，或已有持倉但沒有明確調整理由。
- `BLOCKED`：signal 本身存在，但 quote、verified evidence、research gate、catalyst、market regime 或 duplicate cooldown 阻止升級成 proposal。
- `AVOID`：負向訊號明確但本機沒有對應持倉，不建立賣出 proposal。

Signal score 不是 LLM 決策，而是 deterministic feature breakdown：market regime、sector/theme strength、price momentum、news/catalyst score、fundamentals、thesis alignment、portfolio fit、risk penalty、behavior penalty。每個 signal 會保存 signal-time price、suggested qty/notional、evidence、counter-evidence、gate result、feature breakdown 和 outcome windows，方便之後 replay/backtest。

```bash
INVEST_AGENT_SIGNAL_BUY_THRESHOLD=70
INVEST_AGENT_SIGNAL_SELL_THRESHOLD=65
INVEST_AGENT_SIGNAL_WATCH_THRESHOLD=45
INVEST_AGENT_SIGNAL_MAX_PER_RUN=8
INVEST_AGENT_SIGNAL_EXPIRY_HOURS=24
INVEST_AGENT_SIGNAL_DUPLICATE_COOLDOWN_MINUTES=240
```

CLI / REST：

```bash
python -m invest_agent.cli signals-run
python -m invest_agent.cli signals-latest
python -m invest_agent.cli promote-signal --signal-id sig_...

curl -X POST http://127.0.0.1:8788/api/signals/run -H "Content-Type: application/json" -d '{}'
curl http://127.0.0.1:8788/api/signals/latest
curl -X POST http://127.0.0.1:8788/api/signals/sig_.../promote-to-proposal
```

安全邊界不變：signal 可以主動、明確、有方向，但不是 approval，不會 unlock Futu，也不會送 live order。升級後的 proposal 仍要走 `InvestmentService`、research evidence gate、thesis/catalyst invariants、policy engine 與人工批准。

## Accounting + IPS Foundation

Canonical Accounting 是 portfolio optimizer / tax-aware rebalance 之前的地基。第一版只做本機可審計 ledger：

- `accounting_transactions`：交易、股息、fee、tax withholding、cash deposit/withdrawal、transfer、corporate action placeholder。
- `accounting_tax_lots`：由 accounting transactions 以 FIFO 重建 open/closed tax lots。
- `accounting_snapshots`：保存 cash by currency、open positions、realized PnL、dividend income、fees、withholding tax 與 warnings。
- `investor_policy_statements`：把確認後的 Advisor Profile 固化成正式 IPS，包括 risk profile、投資期限、現金底線、單股/科技/sector 上限、drawdown tolerance、core/satellite target 與 prohibited assets。

這層仍然 research/accounting-only：不建立 proposal、不 approve、不 unlock Futu、不下單。Corporate actions / split 目前只會記錄與 warning，未自動改 lot。

REST API：

```bash
curl -X POST http://127.0.0.1:8788/api/accounting/sync-from-journal
curl http://127.0.0.1:8788/api/accounting/snapshots/latest
curl http://127.0.0.1:8788/api/accounting/transactions
curl http://127.0.0.1:8788/api/accounting/tax-lots
curl -X POST http://127.0.0.1:8788/api/ips/from-advisor-profile
curl http://127.0.0.1:8788/api/ips
```

REST API：

```bash
curl -X POST http://127.0.0.1:8788/api/opportunity-radar/run \
  -H "Content-Type: application/json" \
  -d '{"question":"今晚市場有無值得留意的新機會？"}'
curl http://127.0.0.1:8788/api/opportunity-radar/runs
```

macOS launchd 範例在 `deploy/launchd/com.local.invest-agent-advisor-scheduler.plist`。它會常駐 `advisor-scheduler-loop`，每分鐘檢查是否要跑 hourly pulse、pre-market brief 或 post-close brief；同一個 market session 不會重複建立 full brief。

## Market Context Lens

Market Context Lens 是 broad-market 背景層，和交易 watchlist 分開。它預設追蹤：

```bash
INVEST_AGENT_MARKET_CONTEXT_SYMBOLS=SPY,QQQ,IWM,DIA,VIXY,TLT,GLD,USO,XLK,XLF,XLE,XLV,XLY,XLP,XLI,XLU,XLB,XLRE,SMH,SOXX,IGV,XBI,IBB,ITA,KRE,SCHD,SGOV,BIL
```

這些 symbols 用來理解大盤、sector/theme rotation、科技成長股、小型股、波動率、利率、黃金、油價與 cash-like 環境。它們會進入 Advisor Brief / Opportunity Radar 的背景檢查，但不會自動成為 proposal draft 候選。

Dashboard 的 `市場摘要` 會顯示最近 24 條新聞；`市場全景` 則按 broad-market symbol 顯示 quote/news coverage。Futu read-only refresh 會嘗試為 market-context symbols 抓 quote snapshot；若該 symbol 沒有 quote 權限或 OpenD 無法返回，系統仍保留 news-only context。

REST API：

```bash
curl http://127.0.0.1:8788/api/market-context
curl -X POST http://127.0.0.1:8788/api/market-context/refresh \
  -H "Content-Type: application/json" \
  -d '{}'
```

Market Regime / Risk Budget Lens 會把 market context 轉成 deterministic summary：

- `risk_appetite`: `risk_on | neutral | risk_off`
- `growth_pressure`: `supportive | mixed | pressured`
- `rates_pressure`: `falling_yields | neutral | rising_yields`
- `volatility_regime`: `calm | elevated | stressed`
- `inflation_pressure`: `benign | mixed | oil_gold_pressure`
- `proposal_bias`: `normal | caution | defensive_only`

Regime 使用 quote move、VIXY / TLT / GLD / USO proxy 和 news-only fallback 做規則判斷，並產生 `market_regime_v1` run card。它只影響 Advisor Brief 的審批背景，不會建立 proposal、不會 approve、不會下單。

```bash
curl http://127.0.0.1:8788/api/market-regime
curl -X POST http://127.0.0.1:8788/api/market-regime/refresh
```

Hermes MCP exposes `get_market_context`、`get_market_regime` and `refresh_market_context_news`，所以 conversational agent 可以先看市場全景與 regime，再解釋個別 proposal。

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
INVEST_AGENT_DRAFT_MIN_SCORE=7
INVEST_AGENT_SIGNAL_BUY_THRESHOLD=70
INVEST_AGENT_SIGNAL_SELL_THRESHOLD=65
INVEST_AGENT_SIGNAL_WATCH_THRESHOLD=45
INVEST_AGENT_SIGNAL_MAX_PER_RUN=8
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
- `research_evidence`：保存來源、URL、資料日期、retrieved time、freshness、verification status、source-verified provenance、confidence、caveat、反證關聯與 `run_card_id`。
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

- `earnings_reviews`：保存 symbol、period、catalyst/research/thesis link、YoY 指標、cashflow quality、thesis delta、action bias、evidence hash 與 `run_card_id`。
- `run_earnings_review` 會建立或沿用 research goal，並寫入 source-verified `sec-companyfacts` evidence。
- 如果 review 連到 completed earnings catalyst，會建立 `catalyst_review`，解除「事件完成但未 review」的 proposal block。
- 每次 earnings review 都會產生 `research_run_cards` 記錄，保存 scoring version、thresholds、SEC companyfacts snapshot lineage、input/output hash、warnings 與 artifact path。
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

## Research Run Cards

Research Run Cards 是 Vibe-style Trust Layer 的本機安全版本。它不是交易訊號，也不能由 Hermes 任意建立；它由系統流程在完成重要研究動作時自動寫入，用來固定當時的 inputs、rule version、dataset lineage、metrics、warnings、outputs 與 artifact hashes。

- `research_run_cards`：保存 run type、status、symbol、actor、trigger source、git commit、rule version、input/output/dataset/evidence hash、links、metrics、warnings、assumptions 與 artifact paths。
- `earnings_review` run card 會保存 deterministic scoring metadata，例如 `earnings_review_v1`、YoY thresholds、OCF quality tolerance、SEC snapshot hash、CIK、entity name 與 latest filed date。
- `catalyst_review` run card 會把 post-event review 的 thesis delta、action bias、evidence hash 與 linked research goal 固定下來。
- `event_replay` run card 會保存 JSONL artifact hash、event counts、symbols 與 replay metrics。
- `trade_journal_import` / `behavior_report` run card 會保存 CSV file hash、normalized fills hash、FIFO roundtrip metrics、diagnostics 與 behavior report ID。
- `shadow_strategy_extract` / `shadow_report` run card 會保存 behavior report、抽取規則、roundtrips、rule violations、warnings，以及不計算 fake counterfactual PnL 的限制說明。
- Hermes MCP 只能讀 run cards 和 artifacts，不能建立 arbitrary run card。

REST API：

```bash
curl http://127.0.0.1:8788/api/run-cards
curl http://127.0.0.1:8788/api/run-cards/run_...
curl "http://127.0.0.1:8788/api/run-cards/run_.../artifact?kind=markdown"
```

CLI：

```bash
python -m invest_agent.cli list-run-cards --run-type earnings_review --symbol AAPL
python -m invest_agent.cli show-run-card --run-card-id run_...
python -m invest_agent.cli show-run-card --run-card-id run_... --kind markdown
```

Dashboard 會顯示 `研究執行紀錄`，包含 run type、status、symbol、linked research goal、evidence hash、input/output hash、warnings 與 artifact kind。

## Trade Journal + Behavior Report

Trade Journal / Behavior Report 是 research-only 自我交易行為分析層。它會匯入 broker CSV，把成交標準化成 fills，再用 FIFO 配對 closed roundtrips。它不建立 proposal、不批准 proposal、不改 execution path，只把你的交易行為變成可審計 artifact。

- `trade_imports`：保存來源格式、檔名、CSV file hash、匯入時間、row count、parse warnings 與 `run_card_id`。同一個 `file_hash` 重複匯入會直接回傳既有 import，不重複寫入 fills。
- `trade_fills`：保存 normalized symbol、side、qty、price、fees、currency、market、traded time、broker IDs、raw row hash 與 raw row JSON。
- `trade_roundtrips`：保存 FIFO closed roundtrip、holding days、realized PnL、PnL %、fees 與 pairing method。
- `behavior_reports`：保存 total trades、roundtrips、win rate、profit/loss ratio、average holding days、trade frequency、realized PnL、max drawdown、top symbols、hourly/market distribution、diagnostics 與 `run_card_id`。
- diagnostics v1 是 deterministic rules：`disposition_effect`、`overtrading`、`chasing_momentum`、`anchoring`。
- MCP 只能讀 behavior reports 和 roundtrips；不能匯入任意本機檔案。

Generic CSV 第一版欄位：

```text
datetime,symbol,side,quantity,price,fee,currency,market
```

Futu CSV parser 支援常見中英文欄位 alias，例如 `成交時間`、`代碼`、`買賣方向`、`成交數量`、`成交價格`、`費用`、`幣種`、`訂單號`、`成交號`。

REST API：

```bash
curl -X POST http://127.0.0.1:8788/api/trade-journal/import \
  -H "Content-Type: application/json" \
  -d '{"source":"futu_csv","path":"/Users/apple/Downloads/futu_trades.csv"}'
curl -X POST http://127.0.0.1:8788/api/behavior-reports/run \
  -H "Content-Type: application/json" \
  -d '{"period_start":"2026-01-01T00:00:00Z","period_end":"2026-05-26T23:59:59Z"}'
curl http://127.0.0.1:8788/api/behavior-reports
curl http://127.0.0.1:8788/api/trade-roundtrips?symbol=AAPL
```

CLI：

```bash
python -m invest_agent.cli import-trade-journal --source futu_csv --path ~/Downloads/futu_trades.csv
python -m invest_agent.cli behavior-report --period-start 2026-01-01 --period-end 2026-05-26
python -m invest_agent.cli list-behavior-reports --limit 5
python -m invest_agent.cli show-behavior-report --report-id beh_...
python -m invest_agent.cli list-trade-roundtrips --symbol AAPL
```

Dashboard 會顯示 `交易行為` 和 `匯入交易日誌`，包含 behavior diagnostics badge、PnL profile、recent import、recent roundtrip 與 run card ID。

## Shadow Account + Counterfactual Report

Shadow Account 是 research-only 的自我交易紀律檢查層。它使用已匯入的 fills、FIFO roundtrips 和 behavior report 來抽取 deterministic draft rules；只有人類透過 CLI/REST/dashboard 確認後，才可以跑 shadow report。Hermes MCP 只能讀取策略、報告和事件，不能抽取、確認或執行 shadow report。

- `shadow_strategies`：保存從 behavior report 抽出的 draft / active strategy、source behavior report、extraction method、human confirmation 狀態與 `run_card_id`。
- `shadow_rules`：保存 deterministic rules，例如 median holding days、take-profit / stop-loss reference、median entry notional、same-symbol cooldown、thesis required、high-impact catalyst window。
- `shadow_reports`：保存 rule violation count、early/late exit count、actual PnL、counterfactual PnL（v1 若無 quote history 則為 `null`）、diagnostics 與 `run_card_id`。
- `shadow_events`：保存 `early_exit`、`late_exit`、`oversized_trade`、`ignored_catalyst`、`thesis_mismatch`、`post_event_review_missing`、`contradicted_earnings_review` 等事件。
- v1 是 journal-internal counterfactual：不使用 OHLCV，不做 full backtest，不把自己的歷史行為當成 alpha signal。

REST API：

```bash
curl -X POST http://127.0.0.1:8788/api/shadow-strategies/extract \
  -H "Content-Type: application/json" \
  -d '{"behavior_report_id":"beh_..."}'
curl -X POST http://127.0.0.1:8788/api/shadow-strategies/shadow_.../confirm \
  -H "Content-Type: application/json" \
  -d '{"human_confirmed":true,"confirmed_by":"local-user"}'
curl -X POST http://127.0.0.1:8788/api/shadow-reports/run \
  -H "Content-Type: application/json" \
  -d '{"strategy_id":"shadow_..."}'
curl http://127.0.0.1:8788/api/shadow-events?report_id=shrep_...
```

CLI：

```bash
python -m invest_agent.cli extract-shadow-strategy --behavior-report-id beh_...
python -m invest_agent.cli confirm-shadow-strategy --strategy-id shadow_...
python -m invest_agent.cli run-shadow-report --strategy-id shadow_...
python -m invest_agent.cli list-shadow-reports --limit 5
python -m invest_agent.cli show-shadow-report --report-id shrep_...
```

Dashboard 會顯示 `影子帳戶` 和 `反事實報告`，包含 draft / active strategy、extracted rules、rule violation events、actual PnL、counterfactual PnL availability 和 run card linkage。

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

`event-export` 會同時產生 `event_replay` run card，讓 JSONL export 的 hash 和 replay context 可以回到 run card audit trail。Proposal draft 仍只由 directional news 觸發；SEC/IR primary-source evidence 會被附加作為背景證據，不會單靠 filing 自動產生交易方向。

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

自治層會跑一個安全循環：刷新只讀資料、更新新聞與 primary sources、解析 SEC companyfacts、產生主動 paper signals、草擬交易提案，並在 evidence gate 與 cooldown 都允許時建立 `PENDING` proposal。它不會批准 proposal、不會 unlock Futu、不會送 live order。
同一時間只允許一個 safe autonomy cycle 執行；launchd、Dashboard、CLI、MCP 若重疊觸發，後到的請求會回傳 structured skipped result，不會重複刷新或建立 proposal。

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
python -m invest_agent.cli doctor
python -m invest_agent.cli autonomy-loop
```

macOS 常駐範例在 `deploy/launchd/com.local.invest-agent-scheduler.plist`。Dashboard 也有 `執行自治循環` 按鈕與 `安全自治狀態` / `主動買賣訊號` 面板。Runtime doctor 會檢查 DB、Futu、autonomy/advisor freshness、draft threshold metrics、latest signal run、proposal status mismatch；若日後加入 repair/migration 指令，必須先建立 timestamped SQLite backup 並記錄 backup path。
同一份 doctor 實作也由 `GET /api/runtime/doctor` 提供；CLI 版本直接讀本機設定與 SQLite，不依賴 API server 已啟動。

## Next Phase Research Cockpit

The roadmap from `nextphaseplan.docx` is implemented as research-only control-plane layers. These artifacts can add context, warnings, run cards, and research goals, but they cannot directly create `PENDING` proposals, approve proposals, unlock Futu, or send live broker orders.

- Hypothesis Registry: `research_hypotheses` and `hypothesis_links`, with MCP drafts defaulting unconfirmed.
- Portfolio Studio: portfolio risk x-ray, target drift, concentration warnings, and rebalance candidates that can only promote to research goals.
- Earnings Preview: pre-event key metrics, bull/base/bear scenario notes, what-to-watch checklist, and optional options implied move.
- Quote History: daily price bars for diagnostic shadow-account counterfactual PnL; missing prices keep PnL fields null.
- External Backtest Imports: JSON/Markdown run-card artifact import only; no external code execution and no proposal-gate pass.
- Data Bridge: safe CSV imports under `artifacts/imports` for local schemas such as symbol classification; MCP remains read-only.
- Daily Briefs: morning/close/weekly research delivery artifacts based on Advisor Brief and Market Regime.
- Sector / Peer / Correlation Lens, Options Implied Move Lens, Dividend Lens, Idea Inbox, Committee Review, Skill Validator, and Data Quality reports.
- Stabilization guardrails: `docs/permissions.md` records the MCP permission matrix, and `schema-check` verifies the SQLite schema without clearing proposal, execution, research-goal, or run-card rows.

Useful CLI examples:

```bash
python -m invest_agent.cli market-regime --refresh
python -m invest_agent.cli create-hypothesis --title "AI capex" --statement "AI capex beneficiaries need verified revenue evidence" --symbols AAPL,NVDA
python -m invest_agent.cli portfolio-risk
python -m invest_agent.cli rebalance-review
python -m invest_agent.cli earnings-preview --symbol AAPL
python -m invest_agent.cli quote-history-refresh --symbol AAPL --path ./bars.csv
python -m invest_agent.cli run-shadow-report --strategy-id shadow_... --use-quote-history
python -m invest_agent.cli import-backtest-run-card --path ./run_card.json
python -m invest_agent.cli data-import --schema symbol_classification --path ./classifications.csv
python -m invest_agent.cli morning-brief
python -m invest_agent.cli correlation-run --symbols AAPL,MSFT,NVDA
python -m invest_agent.cli import-options-snapshot --symbol AAPL --expiry 2026-02-20 --implied-move-pct 7.5
python -m invest_agent.cli dividend-review --symbol T --dividend-yield 0.06 --payout-ratio 1.1
python -m invest_agent.cli idea-screen
python -m invest_agent.cli committee-review --topic "AAPL post-earnings thesis"
python -m invest_agent.cli validate-skills
python -m invest_agent.cli data-quality-run --target-type all
python -m invest_agent.cli schema-check
```

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
        - ask_advisor
        - get_advisor_profile
        - suggest_advisor_profile_update
        - confirm_advisor_profile_update
        - run_hourly_advisor_pulse
        - run_pre_market_advisor_brief
        - run_post_close_advisor_brief
        - get_latest_advisor_brief
        - run_committee_review
        - list_committee_reviews
        - get_committee_review
      resources: false
      prompts: false
```

如果 `hermes model` 顯示你的帳戶有更新的 Codex model，可用互動選單覆蓋 `model.default`，MCP 設定不用改。

在 Hermes 裡可以問：

```text
Hermes，我而家應唔應該買 AAPL？
Hermes，今晚 portfolio strategy 應該保守啲嗎？
Hermes，跑一次 hourly pulse，有 urgent 先提醒我。
Hermes，幫我出 pre-market advisor brief。
Hermes，SpaceX IPO 應唔應該投資？
Hermes，如果我一直話唔想追高，你可以問我是否保存成 Advisor Profile。
```

## 安全邊界

第一版只做紙上交易紀錄。Daily Hermes mode 不暴露 proposal approval / execution tools；即使本機控制平面有 paper approval path，也不會 unlock Futu OpenD 或下實盤單。實盤接通前應先補上：

- macOS Keychain secret loading
- Futu 雙 OpenD 實例
- 下單前持倉/現金/open order/價格 revalidation
- order/deal push 對帳
- 小額 live smoke test
