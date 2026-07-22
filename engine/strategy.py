"""
Original VenuxTech Malaysian SNR strategy, ported to plain Python.
This is the ORIGINAL logic (no trend/significance/body filters) — per instruction,
using the version already backtested at ~50% win rate with 1:3 R:R.

Works on a list of candles: each candle = [timestamp, open, high, low, close, volume]
"""

import math
from dataclasses import dataclass, field
from typing import Optional


def atr(candles: list, length: int = 14) -> list:
    """Simple ATR (Wilder-style approximation using rolling mean of true range)."""
    trs = [0.0] * len(candles)
    for i in range(1, len(candles)):
        high = candles[i][2]
        low = candles[i][3]
        prev_close = candles[i - 1][4]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs[i] = tr
    result = [math.nan] * len(candles)
    for i in range(length, len(candles)):
        result[i] = sum(trs[i - length + 1: i + 1]) / length
    return result


@dataclass
class Level:
    price: float
    fresh: bool = True


@dataclass
class Signal:
    index: int
    side: str          # 'buy' or 'sell'
    entry: float
    sl: float
    tp: float
    risk: float


class SNRStrategy:
    """
    Stateful strategy runner — call `.step(candles, i)` per new candle,
    it tracks levels and open-trade state internally, same as the indicator does.
    """

    def __init__(self, swing_lookback: int = 3, atr_len: int = 14,
                 atr_sl_mult: float = 0.3, risk_reward: float = 3.0,
                 touch_tolerance_atr_mult: float = 0.3):
        self.L = swing_lookback
        self.atr_len = atr_len
        self.atr_sl_mult = atr_sl_mult
        self.risk_reward = risk_reward
        self.touch_tolerance_atr_mult = touch_tolerance_atr_mult

        self.a_levels: list[Level] = []   # resistance (peaks) — max 5, oldest dropped
        self.v_levels: list[Level] = []   # support (valleys)

        self.trade_open = False
        self.trade_is_buy = False
        self.trade_sl = 0.0
        self.trade_tp = 0.0
        self.trade_entry = 0.0
        self.trade_risk = 0.0

        self.wins = 0
        self.losses = 0
        self.total = 0

    def _add_level(self, levels: list, price: float):
        levels.append(Level(price))
        if len(levels) > 5:
            levels.pop(0)

    def run(self, candles: list) -> list:
        """Runs the strategy across a full candle history, returns list of Signal."""
        signals: list[Signal] = []
        atrs = atr(candles, self.atr_len)
        L = self.L

        for i in range(2 * L, len(candles)):
            if math.isnan(atrs[i]):
                continue

            # --- detect new swing peak/valley (close price only) ---
            center_close = candles[i - L][4]
            is_peak = all(center_close > candles[i - L - j][4] and center_close > candles[i - L + j][4] for j in range(1, L + 1))
            is_valley = all(center_close < candles[i - L - j][4] and center_close < candles[i - L + j][4] for j in range(1, L + 1))
            if is_peak:
                self._add_level(self.a_levels, center_close)
            if is_valley:
                self._add_level(self.v_levels, center_close)

            close = candles[i][4]
            open_ = candles[i][1]
            high = candles[i][2]
            low = candles[i][3]
            tol = atrs[i] * self.touch_tolerance_atr_mult

            # --- manage open trade first ---
            if self.trade_open:
                if self.trade_is_buy:
                    if low <= self.trade_sl:
                        self.losses += 1
                        self.trade_open = False
                    elif high >= self.trade_tp:
                        self.wins += 1
                        self.trade_open = False
                else:
                    if high >= self.trade_sl:
                        self.losses += 1
                        self.trade_open = False
                    elif low <= self.trade_tp:
                        self.wins += 1
                        self.trade_open = False
                continue  # one trade at a time, same as the indicator

            # --- look for a fresh-level reaction ---
            sell_fired = False
            for lvl in self.a_levels:
                if not lvl.fresh:
                    continue
                if high >= (lvl.price - tol):
                    if close < open_ and close < lvl.price:
                        sl = high + atrs[i] * self.atr_sl_mult
                        sl_dist = sl - close
                        if sl_dist > 0:
                            self.trade_sl = sl
                            self.trade_tp = close - sl_dist * self.risk_reward
                            self.trade_entry = close
                            self.trade_risk = sl_dist
                            self.trade_open = True
                            self.trade_is_buy = False
                            sell_fired = True
                            self.total += 1
                            signals.append(Signal(i, "sell", close, sl, self.trade_tp, sl_dist))
                    lvl.fresh = False
                if sell_fired:
                    break

            if not sell_fired:
                for lvl in self.v_levels:
                    if not lvl.fresh:
                        continue
                    if low <= (lvl.price + tol):
                        if close > open_ and close > lvl.price:
                            sl = low - atrs[i] * self.atr_sl_mult
                            sl_dist = close - sl
                            if sl_dist > 0:
                                self.trade_sl = sl
                                self.trade_tp = close + sl_dist * self.risk_reward
                                self.trade_entry = close
                                self.trade_risk = sl_dist
                                self.trade_open = True
                                self.trade_is_buy = True
                                self.total += 1
                                signals.append(Signal(i, "buy", close, sl, self.trade_tp, sl_dist))
                        lvl.fresh = False
                        break

        return signals

    def latest_signal_from_live_candles(self, candles: list) -> Optional[Signal]:
        """
        For live trading: run the strategy across history, and only act on it
        if the very last candle produced a brand-new signal (so we don't
        re-enter trades that already happened earlier in the history window).
        """
        signals = self.run(candles)
        if signals and signals[-1].index == len(candles) - 1:
            return signals[-1]
        return None
