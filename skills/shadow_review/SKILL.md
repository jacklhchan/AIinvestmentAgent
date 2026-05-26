name: shadow_review
description: Review shadow-account events, behavior reports, and quote-history-backed diagnostic PnL coverage.
allowed_tools:
  - list_shadow_reports
  - get_shadow_report
  - list_shadow_events
  - get_quote_history_summary
  - list_quote_history

Shadow reports are diagnostic only. Daily close counterfactuals are not executable prices and do not create proposal signals.
