"""One-ticker TradingAgents measurement on free NVIDIA models: does it run end to end, how long, how many tokens/calls,
and what does it decide? Read-only. Run via the tradingagents-test workflow (needs NVIDIA_API_KEY; sandbox has no egress)."""
import sys
import time
import traceback

ticker, date = sys.argv[1], sys.argv[2]
analysts = sys.argv[3].split(",") if len(sys.argv) > 3 else ["market", "news"]

from tradingagents.default_config import DEFAULT_CONFIG  # noqa: E402
from tradingagents.graph.trading_graph import TradingAgentsGraph  # noqa: E402

cfg = DEFAULT_CONFIG.copy()
cfg.update({
    "llm_provider": "nvidia",
    "deep_think_llm": "nvidia/nemotron-3-ultra-550b-a55b",   # slow, big: research manager + portfolio manager
    "quick_think_llm": "nvidia/nemotron-3-super-120b-a12b",  # analysts, researchers, trader
    "max_debate_rounds": 1,
    "max_risk_discuss_rounds": 1,
})

usage = None
try:
    from langchain_core.callbacks import UsageMetadataCallbackHandler
    usage = UsageMetadataCallbackHandler()
except Exception:
    pass

t0 = time.time()
try:
    ta = TradingAgentsGraph(selected_analysts=analysts, debug=False, config=cfg)
    if usage is not None:
        ta.callbacks = getattr(ta, "callbacks", []) + [usage]
    state, decision = ta.propagate(ticker, date)
    print("\n=== DECISION ===\n", decision)
    for k in ("trader_investment_plan", "final_trade_decision"):
        if state.get(k):
            print(f"\n--- {k} (first 800 chars) ---\n{str(state[k])[:800]}")
except Exception:
    print("\nRUN FAILED:\n" + "".join(traceback.format_exc()[-2500:]))
    sys.exit(1)
finally:
    print(f"\nelapsed: {time.time() - t0:.0f}s")
    if usage is not None and getattr(usage, "usage_metadata", None):
        print("token usage by model:", usage.usage_metadata)
    else:
        print("token usage: not captured by the callback (check NVIDIA dashboard credits before/after)")
