"""Experiment: trade on EVERY Jev call, to see what fees do to a bot with no filter.

  uv run python -m jevlab.everycall --coin HYPE --minutes 60

Takes the same flags as `loop`. Any confidence counts and there's no wait between flips: it
follows every on-time call, holding when the call agrees with its position and flipping at
market when it doesn't. Uses market orders so every order fills.
Your own strategy.py is untouched. This is paper trading only.
"""

from __future__ import annotations

import sys

from . import loop

DESCRIPTION = "EXPERIMENT · follow every call (market orders), any confidence, no waiting"


def decide(call: dict, market: dict, position: int, seconds_since_trade: float) -> str:
    want = 1 if call["side"] == "buy" else -1
    if want == position:
        return "hold · already " + ("long" if want > 0 else "short")
    return call["side"]


class _EveryCall:
    DESCRIPTION = DESCRIPTION
    decide = staticmethod(decide)


def main() -> None:
    loop.strategy = _EveryCall  # swap the strategy for this run only
    from .__main__ import main as cli
    args = sys.argv[1:]
    if "--taker" not in args:
        args.append("--taker")  # market orders, so every order fills
    sys.argv = [sys.argv[0], "loop", *args]
    cli()


if __name__ == "__main__":
    main()
