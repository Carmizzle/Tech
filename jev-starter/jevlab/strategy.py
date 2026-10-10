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
              mid                               the current price (loop only)
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

# Big plays: few trades, aiming for larger moves. Enter only when Jev is very sure AND the market is
# already moving hard that way, then let it run to a take-profit or a stop-loss (or a time limit).
# Opposite calls are ignored while in a trade, so small wiggles don't shake you out.
# The guide's original rules (85% sure, 15s between flips) are in git history.
SETTINGS = {
    "min_conf": 0.85,        # Jev must be at least this sure...
    "trend_bps": 5.0,        # ...and price already moving that way over 30s (5 bps = 0.05%)...
    "buy_flow": 0.60,        # ...with buyers (or sellers, 1 - this) doing most of the trading
    "take_profit_pct": 1.0,  # close when the trade is up this much
    "stop_loss_pct": 0.5,    # close when it's down this much (keep it smaller than the take-profit)
    "max_hold_min": 60,      # close after this long, win or lose
    "cooldown_s": 120,       # wait this long after closing before the next trade
}

DESCRIPTION = (f"big plays · enter at ≥{SETTINGS['min_conf']:.0%} with a strong move · "
               f"take profit +{SETTINGS['take_profit_pct']:g}% · stop -{SETTINGS['stop_loss_pct']:g}% · "
               f"max {SETTINGS['max_hold_min']:g} min")

_trade: dict = {}  # the open trade: side and entry price, so we know when to take profit or stop out


def decide(call: dict, market: dict, position: int, seconds_since_trade: float) -> str:
    want = 1 if call["side"] == "buy" else -1
    bias = market.get("claude_bias")  # only set on the 24/7 bot, where Claude is the brain
    if bias == "flat":
        return "flat" if position else "hold · Claude says stay out"
    if (bias == "long" and position < 0) or (bias == "short" and position > 0):
        return "flat"  # Claude changed its mind: get out of the old direction first
    if (bias == "long" and want < 0) or (bias == "short" and want > 0):
        return f"hold · against Claude's {bias} bias"

    mid = market.get("mid")
    if position == 0:
        _trade.clear()
    elif mid and _trade.get("side") != position:  # a new position just filled: remember where we got in
        _trade.update(side=position, entry=mid)

    # In a trade: only the take-profit, the stop-loss or the time limit can close it.
    if position:
        if mid and _trade.get("entry"):
            move_pct = 100 * (mid / _trade["entry"] - 1) * position
            if move_pct >= SETTINGS["take_profit_pct"]:
                return "flat"
            if move_pct <= -SETTINGS["stop_loss_pct"]:
                return "flat"
            if seconds_since_trade >= SETTINGS["max_hold_min"] * 60:
                return "flat"
            return f"hold · riding {move_pct:+.2f}%"
        return "hold · in a trade"

    # Flat: wait for a strong, confirmed setup.
    if seconds_since_trade < SETTINGS["cooldown_s"]:
        return "hold · cooling down"
    if call["conf"] < SETTINGS["min_conf"]:
        return "hold · low conviction"
    r30 = market.get("return_30s_bps", 0.0)
    flow = market.get("aggressor_buy_share_30s", 0.5)
    strong = (r30 >= SETTINGS["trend_bps"] and flow >= SETTINGS["buy_flow"]) if want > 0 else \
             (r30 <= -SETTINGS["trend_bps"] and flow <= 1 - SETTINGS["buy_flow"])
    if not strong:
        return "hold · no strong move to join"
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
