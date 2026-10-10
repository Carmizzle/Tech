"""Replay the Jev calls you've already recorded through several strategies and compare them.

  uv run python -m jevlab.backtest              # every coin in results/loop_log.jsonl
  uv run python -m jevlab.backtest --coin HYPE  # just one
  uv run python -m jevlab.backtest --search     # let the data look for a better rule (and check it honestly)

It answers "would strategy X have done better than Y on the same calls?", and it splits the data
in half: a strategy that only wins on one half probably got lucky. It is a rough guide, not a
promise: fills are assumed at the mid price plus half the spread (market) or at the mid (limit),
and real fills are usually a little worse.
"""

from __future__ import annotations

import argparse
import json
import statistics

from . import hl, strategy
from .core import RESULTS

NOTIONAL = 1000.0


# ---------------------------------------------------------------- strategies to compare

def original(call, market, position, since):
    want = 1 if call["side"] == "buy" else -1
    if call["conf"] < 0.85:
        return "hold"
    if want == position:
        return "hold"
    if since < 15:
        return "hold"
    return call["side"]


def original_exit(call, market, position, since):
    want = 1 if call["side"] == "buy" else -1
    if call["conf"] < 0.85:
        if position and want != position and call["conf"] >= 0.60 and since >= 15:
            return "flat"
        return "hold"
    return original(call, market, position, since)


def every_call(call, market, position, since):
    return "hold" if (1 if call["side"] == "buy" else -1) == position else call["side"]


def make_rule(min_conf: float, min_hold: float, trend: str, exit_conf: float | None):
    """A family of strategies for --search: conviction, hold time, a trend filter, an optional exit."""
    def rule(call, market, position, since):
        want = 1 if call["side"] == "buy" else -1
        if call["conf"] < min_conf:
            if exit_conf and position and want != position and call["conf"] >= exit_conf and since >= min_hold:
                return "flat"
            return "hold"
        if want == position or (position and since < min_hold):
            return "hold"
        r30 = market.get("return_30s_bps", 0.0)
        if trend == "with" and r30 * want < 2.0:       # price already moving Jev's way
            return "hold"
        if trend == "against" and r30 * want > -2.0:   # fade: price moved the other way, Jev expects a snap back
            return "hold"
        return call["side"]
    exit_txt = f", exit {exit_conf:.0%}" if exit_conf else ""
    rule.label = f"{min_conf:.0%}, hold {min_hold:g}s, {trend}{exit_txt}"
    return rule


SEARCH = [make_rule(c, h, t, e) for c in (0.7, 0.75, 0.8, 0.85, 0.9) for h in (15, 60, 180, 600)
          for t in ("any trend", "with", "against") for e in (None, 0.6)]


def search(name: str, recs: list[dict], taker: bool) -> None:
    """Pick the best rules on the first half only, then see how they do on the second half they never saw."""
    half = len(recs) // 2
    scored = [(simulate(recs[:half], r, taker), r) for r in SEARCH]
    scored = [(s, r) for s, r in scored if s["trades"] >= 30]  # a rule with a dozen trades proves nothing
    scored.sort(key=lambda x: x[0]["net"], reverse=True)
    print(f"\n  {name}: tried {len(SEARCH)} rules on the 1st half ({half} calls), best 5, then tested on the 2nd half")
    print(f"    {'rule':<34} {'1st half':>9} {'trades':>6}   {'2nd half':>9} {'trades':>6}")
    for s1, r in scored[:5]:
        s2 = simulate(recs[half:], r, taker)
        print(f"    {r.label:<34} {s1['net']:>+9.2f} {s1['trades']:>6}   {s2['net']:>+9.2f} {s2['trades']:>6}")
    held = sum(simulate(recs[half:], r, taker)["net"] > 0 for _, r in scored[:5])
    print(f"    -> {held} of the top 5 stayed profitable on data they hadn't seen")


STRATEGIES = {
    "your strategy.py": strategy.decide,
    "original (85%, 15s)": original,
    "original + 60% exit": original_exit,
    "follow every call": every_call,
}


# ---------------------------------------------------------------- data

def load(coin: str | None) -> dict[str, list[dict]]:
    path = RESULTS / "loop_log.jsonl"
    if not path.exists():
        raise SystemExit("  no results/loop_log.jsonl yet: run the loop first")
    recs = []
    for line in open(path, encoding="utf-8"):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("status") == "ok" and r.get("side") and r.get("mid"):
            recs.append(r)
    recs.sort(key=lambda r: r["t"])
    groups: dict[str, list[dict]] = {}
    unnamed: list[list[dict]] = []  # older lines have no coin: group them by price level instead
    for r in recs:
        if r.get("coin"):
            groups.setdefault(r["coin"], []).append(r)
            continue
        for g in unnamed:
            if abs(r["mid"] / g[-1]["mid"] - 1) < 0.15:
                g.append(r)
                break
        else:
            unnamed.append([r])
    for g in unnamed:
        mid = statistics.median(x["mid"] for x in g)
        name = f"unlabelled coin @ ~{mid:,.0f}" if mid >= 1000 else f"unlabelled coin @ ~{mid:,.2f}"
        groups[name] = g
    if coin:
        groups = {k: v for k, v in groups.items() if k.upper() == coin.upper()}
    return {k: v for k, v in groups.items() if len(v) >= 20}


def simulate(recs: list[dict], decide, taker: bool) -> dict:
    pos, qty, cash, fees, trades, last_t = 0, 0.0, 0.0, 0.0, 0, 0.0
    fee_rate = hl.TAKER_FEE if taker else hl.MAKER_FEE
    prev_t = None
    for r in recs:
        if prev_t is not None and r["t"] - prev_t > 600:  # a gap between runs: close out, start fresh
            if pos:
                cash += qty * r["mid"]; fees += abs(qty) * r["mid"] * fee_rate; qty, pos = 0.0, 0; trades += 1
        prev_t = r["t"]
        try:
            choice = decide({"side": r["side"], "conf": r["conf"]}, {**r.get("state", {}), "mid": r["mid"]}, pos, r["t"] - last_t)
        except Exception:
            continue
        if choice not in ("buy", "sell", "flat"):
            continue
        target = {"buy": 1, "sell": -1, "flat": 0}[choice]
        if target == pos:
            continue
        half_spread = r["mid"] * r.get("state", {}).get("spread_bps", 0.0) / 2e4
        dq = target * NOTIONAL / r["mid"] - qty
        px = r["mid"] + (half_spread if dq > 0 else -half_spread) if taker else r["mid"]
        cash -= dq * px
        fees += abs(dq) * px * fee_rate
        qty, pos, last_t, trades = qty + dq, target, r["t"], trades + 1
    gross = cash + qty * recs[-1]["mid"]
    return {"trades": trades, "gross": gross, "fees": fees, "net": gross - fees}


def main() -> None:
    ap = argparse.ArgumentParser(prog="jevlab.backtest")
    ap.add_argument("--coin", help="only this coin")
    ap.add_argument("--taker", action="store_true", help="assume market orders (default: limit orders at the mid)")
    ap.add_argument("--search", action="store_true", help="search many rules on the 1st half, test them on the 2nd")
    a = ap.parse_args()
    groups = load(a.coin)
    if not groups:
        raise SystemExit("  not enough recorded calls yet (need 20+ answered calls per coin)")
    print(f"  fills: {'market orders, paying half the spread' if a.taker else 'limit orders at the mid (optimistic)'} "
          f"· ${NOTIONAL:,.0f} position · after fees, in $")
    if a.search:
        for name, recs in groups.items():
            search(name, recs, a.taker)
        print("\n  Benchmark: with a coin-flipping fake Jev, usually 0-2 of the top 5 survive by luck alone.\n"
              "  A rule is only interesting if it survives the 2nd half on SEVERAL coins, with 4-5 of 5 holding up.")
        return
    for name, recs in groups.items():
        half = len(recs) // 2
        hours = (recs[-1]["t"] - recs[0]["t"]) / 3600
        print(f"\n  {name}: {len(recs)} answered calls over {hours:.1f}h")
        print(f"    {'strategy':<22} {'trades':>6} {'before':>8} {'fees':>7} {'after':>8}   1st half  2nd half")
        for label, fn in STRATEGIES.items():
            full = simulate(recs, fn, a.taker)
            h1, h2 = simulate(recs[:half], fn, a.taker), simulate(recs[half:], fn, a.taker)
            print(f"    {label:<22} {full['trades']:>6} {full['gross']:>+8.2f} {full['fees']:>7.2f} {full['net']:>+8.2f}"
                  f"   {h1['net']:>+8.2f}  {h2['net']:>+8.2f}")
    print("\n  Trust a strategy only if it's ahead on BOTH halves, on more than one coin, with plenty of trades.")


if __name__ == "__main__":
    main()
