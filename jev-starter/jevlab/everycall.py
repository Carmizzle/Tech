"""Experiment: trade on EVERY Jev call, to see what fees do to a bot with no filter.

  uv run python -m jevlab.everycall --coin HYPE --minutes 60

Takes the same flags as `loop`. Any confidence counts, there's no wait between flips,
and the bot simply follows each call: BUY means be long, SELL means be short.
Your own strategy.py is untouched. This is paper trading only.
"""

from __future__ import annotations

import sys

from . import loop

DESCRIPTION = "EXPERIMENT · trade every call, any confidence, no waiting"


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
    sys.argv = [sys.argv[0], "loop", *sys.argv[1:]]
    cli()


if __name__ == "__main__":
    main()
