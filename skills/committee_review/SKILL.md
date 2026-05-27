name: committee_review
description: Create and inspect committee-style research memos with bull case, bear case, risk memo, and missing evidence.
allowed_tools:
  - run_committee_review
  - list_committee_reviews
  - get_committee_review
  - list_hypotheses
  - list_research_goals

Committee memos cannot approve proposals. Missing evidence should send the workflow back to research.

When the user asks for "committee", "investment committee", "agent swarm", "bull/bear debate", "多角度", "反方", "牛熊", or "投資委員會", call `run_committee_review` first and summarize the persisted committee memo. Do not substitute general Hermes subagents/delegation for the audited committee layer. General subagents can only be optional commentary after the control-plane committee review exists, and must be labeled as non-audited.
