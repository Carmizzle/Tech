"""YOUR STRATEGY. This is the one file you're meant to edit.

Jev makes a call several times a second ("buy, 91% sure"). Your strategy decides
which of those calls actually become trades. Most should end in "hold": every
trade has a cost, so a bot that trades every call bleeds.

decide() is called every time Jev answers, with:

  call      Jev's answer, e.g. {"side": "buy", "conf": 0.91}
  market    the live numbers Jev was shown, for example:
              return_5s_bps, return_30s_bps     price change over 5s / 30s (1 bps = 0.01%)
              top_of_book_imbalance             -1 (all sellers) .. +1 (all buyers) at the best price
              depth5_imbalance                  the same, over the top 5 price levels
              aggressor_buy_share_5s / _30s     share of recent trade volume that was buyers (0..1)
              trades_last_5s                    how busy the market is right now
              spread_bps, microprice_vs_mid_bps, tick_volatility_60s_bps
              claude_bias                       24/7 bot only: "long", "short" or "flat", Claude's
                                                big-picture call, refreshed every few minutes
  position  1 = you're long, -1 = you're short, 0 = flat
  seconds_since_trade   seconds since your last fill

Return one of:
  "buy"            go (or stay) long
  "sell"           go (or stay) short
  "flat"           close the position
  "hold · reason"  do nothing. The reason shows up in the dashboard feed.

The loop handles everything else: placing the (paper) order, fees, the
dashboard. Want a different strategy? Describe it to Claude in one sentence
and ask it to rewrite decide(), e.g. "only buy when Jev is 90%+ sure AND
buyers have been in control for the last 30 seconds".
"""

# Trend rider: built for a slow Jev (free mode answers 5-20 s late). Instead of guessing the
# next few seconds, only join a move that's already under way and hold it for a while, so each
# trade has room to make more than its fees. Older versions are in git history.
SETTINGS = {
    "min_conf": 0.75,        # Jev must be at least this sure...
    "trend_bps": 3.0,        # ...and price must already be moving its way over 30s (1 bps = 0.01%)...
    "buy_flow": 0.58,        # ...with buyers (or sellers, 1 - this) doing most of the trading over 30s
    "max_spread_bps": 1.5,   # skip when the market is thin: a wide spread costs you on every trade
    "min_hold": 60,          # seconds to keep a position before exiting or flipping (fewer trades, fewer fees)
}

DESCRIPTION = (f"trend rider · join moves ≥{SETTINGS['trend_bps']:g} bps/30s at ≥{SETTINGS['min_conf']:.0%} · "
               f"hold ≥{SETTINGS['min_hold']}s · exit when the trend fades")


def decide(call: dict, market: dict, position: int, seconds_since_trade: float) -> str:
    want = 1 if call["side"] == "buy" else -1
    bias = market.get("claude_bias")  # only set on the 24/7 bot, where Claude is the brain
    if bias == "flat":
        return "flat" if position else "hold · Claude says stay out"
    if (bias == "long" and position < 0) or (bias == "short" and position > 0):
        return "flat"  # Claude changed its mind: get out of the old direction first
    if (bias == "long" and want < 0) or (bias == "short" and want > 0):
        return f"hold · against Claude's {bias} bias"

    r30 = market.get("return_30s_bps", 0.0)
    flow = market.get("aggressor_buy_share_30s", 0.5)
    up = r30 >= SETTINGS["trend_bps"] and flow >= SETTINGS["buy_flow"]
    down = r30 <= -SETTINGS["trend_bps"] and flow <= 1 - SETTINGS["buy_flow"]
    settled = seconds_since_trade >= SETTINGS["min_hold"]

    # Exit when the move we joined has faded: price and order flow both turned against us.
    if position > 0 and r30 < 0 and flow < 0.5:
        return "flat" if settled else "hold · trend fading, min hold"
    if position < 0 and r30 > 0 and flow > 0.5:
        return "flat" if settled else "hold · trend fading, min hold"

    if want == position:
        return "hold · already " + ("long" if want > 0 else "short")
    if market.get("spread_bps", 0.0) > SETTINGS["max_spread_bps"]:
        return "hold · spread too wide"
    if call["conf"] < SETTINGS["min_conf"]:
        return "hold · low conviction"
    if not (up if want > 0 else down):
        return "hold · no trend to ride"
    if position and not settled:
        return "hold · too soon to flip"
    return call["side"]


# ---------------------------------------------------------------------------
# Example: trade with the trend only. Uncomment to use it (and delete the
# decide() above).
#
# def decide(call, market, position, seconds_since_trade):
#     trend_up = market.get("return_30s_bps", 0) > 0 and market.get("aggressor_buy_share_30s", 0.5) > 0.55
#     trend_down = market.get("return_30s_bps", 0) < 0 and market.get("aggressor_buy_share_30s", 0.5) < 0.45
#     if call["conf"] < 0.8:
#         return "hold · low conviction"
#     if call["side"] == "buy" and trend_up and position != 1:
#         return "buy"
#     if call["side"] == "sell" and trend_down and position != -1:
#         return "sell"
#     return "hold · against the trend"
