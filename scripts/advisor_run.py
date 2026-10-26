"""Run TradingAgents over plan.json, write results.json. Isolated: needs NVIDIA_API_KEY, never touches the database
(this is third-party code, so it gets no DB credentials). Stops at a time budget so a slow day cannot hang the job."""
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone

plan_path, out_path = sys.argv[1], sys.argv[2]
budget_s = float(os.environ.get("ADVISOR_BUDGET_MIN", "110")) * 60
analysts = os.environ.get("ADVISOR_ANALYSTS", "market,news").split(",")
today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

from tradingagents.default_config import DEFAULT_CONFIG  # noqa: E402
from tradingagents.graph.trading_graph import TradingAgentsGraph  # noqa: E402

cfg = DEFAULT_CONFIG.copy()
cfg.update({"llm_provider": "nvidia",
            "deep_think_llm": os.environ.get("TA_DEEP", "nvidia/nemotron-3-ultra-550b-a55b"),
            "quick_think_llm": os.environ.get("TA_QUICK", "nvidia/nemotron-3.5-lightning-30b-a3b"),
            "max_debate_rounds": 1, "max_risk_discuss_rounds": 1})

plan = json.load(open(plan_path))
results, t0 = [], time.time()
for item in plan:
    if time.time() - t0 > budget_s:
        print(f"time budget reached, skipping {item['ticker']} and the rest")
        break
    t1 = time.time()
    try:
        ta = TradingAgentsGraph(selected_analysts=analysts, debug=False, config=cfg)
        state, decision = ta.propagate(item["ticker"], today)
        results.append({**item, "date": today, "decision": str(decision),
                        "summary": str(state.get("final_trade_decision", ""))[:1500]})
        print(f"{item['ticker']}: {str(decision).strip()[:40]} ({time.time() - t1:.0f}s)")
    except Exception:
        results.append({**item, "date": today, "error": traceback.format_exc()[-400:]})
        print(f"{item['ticker']}: FAILED ({time.time() - t1:.0f}s)\n{traceback.format_exc()[-400:]}")
    json.dump(results, open(out_path, "w"))  # persist after every symbol
json.dump(results, open(out_path, "w"))
print(f"done: {sum(1 for r in results if not r.get('error'))}/{len(plan)} ok in {time.time() - t0:.0f}s")
