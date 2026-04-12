#!/usr/bin/env python3
"""
Analyze trade returns from ORB_HighVolume backtest JSON files.

The JSON arrays are in reverse chronological order — the first trade executed
is the LAST object in the array. Orders are matched into trades using position
tracking: starting with no position held, each BUY or SELL either opens or
closes a position depending on the current state.
"""

import json
import glob
import os
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Order:
    id: int
    symbol: str
    order_type: str   # 'BUY' or 'SELL'
    quantity: int     # raw (may have wrong sign in some records)
    price: float
    timestamp: str

    @property
    def abs_qty(self) -> int:
        return abs(self.quantity)

    @property
    def notional(self) -> float:
        """Gross dollar value of the order (always positive)."""
        return self.price * self.abs_qty

    @property
    def cash_flow(self) -> float:
        """Signed cash impact: BUY costs money (negative), SELL receives money (positive)."""
        return -self.notional if self.order_type == 'BUY' else +self.notional


@dataclass
class Trade:
    direction: str        # 'LONG' or 'SHORT'
    orders: List[Order]

    @property
    def symbol(self) -> str:
        return self.orders[0].symbol

    @property
    def entry_orders(self) -> List[Order]:
        t = 'BUY' if self.direction == 'LONG' else 'SELL'
        return [o for o in self.orders if o.order_type == t]

    @property
    def exit_orders(self) -> List[Order]:
        t = 'SELL' if self.direction == 'LONG' else 'BUY'
        return [o for o in self.orders if o.order_type == t]

    @property
    def entry_notional(self) -> float:
        return sum(o.notional for o in self.entry_orders)

    @property
    def pnl(self) -> float:
        return sum(o.cash_flow for o in self.orders)

    @property
    def return_pct(self) -> float:
        return (self.pnl / self.entry_notional * 100) if self.entry_notional else 0.0

    def _wavg_price(self, orders: List[Order]) -> float:
        total_qty = sum(o.abs_qty for o in orders)
        return sum(o.price * o.abs_qty for o in orders) / total_qty if total_qty else 0.0

    @property
    def entry_price(self) -> float:
        return self._wavg_price(self.entry_orders)

    @property
    def exit_price(self) -> float:
        return self._wavg_price(self.exit_orders)

    @property
    def entry_time(self) -> str:
        return self.orders[0].timestamp

    @property
    def exit_time(self) -> str:
        return self.orders[-1].timestamp


def load_orders(filepath: str) -> List[Order]:
    """Load and return orders in chronological order (last JSON item → first)."""
    with open(filepath) as f:
        data = json.load(f)

    orders = []
    for item in reversed(data):
        orders.append(Order(
            id=item['id'],
            symbol=item['symbol'],
            order_type=item['order_type'],
            quantity=item['quantity'],
            price=item['price'],
            timestamp=item.get('execution_timestamp') or item.get('timestamp', ''),
        ))
    return orders


def match_trades(orders: List[Order]) -> List[Trade]:
    """
    Group orders into completed trades via position tracking.

    Rules (starting from flat/no position):
      - Flat  + BUY  → open LONG
      - Flat  + SELL → open SHORT
      - Long  + SELL → reduce/close LONG
      - Short + BUY  → reduce/close SHORT
      - Long  + BUY  → add to LONG (pyramiding)
      - Short + SELL → add to SHORT (pyramiding)

    A trade is recorded when the position returns to zero.
    """
    trades: List[Trade] = []
    position: int = 0          # net shares held (>0 long, <0 short)
    current: List[Order] = []
    direction: Optional[str] = None

    for order in orders:
        qty = order.abs_qty

        if position == 0:
            # Opening a new position
            direction = 'LONG' if order.order_type == 'BUY' else 'SHORT'
            position = qty if direction == 'LONG' else -qty
            current = [order]

        elif position > 0:
            # Currently long
            if order.order_type == 'SELL':
                position -= qty
                current.append(order)
                if position <= 0:
                    trades.append(Trade(direction=direction, orders=current))
                    current = []
                    position = 0
                    direction = None
            else:
                # Adding to long
                position += qty
                current.append(order)

        else:
            # Currently short (position < 0)
            if order.order_type == 'BUY':
                position += qty
                current.append(order)
                if position >= 0:
                    trades.append(Trade(direction=direction, orders=current))
                    current = []
                    position = 0
                    direction = None
            else:
                # Adding to short
                position -= qty
                current.append(order)

    if current:
        print(f"  WARNING: {len(current)} unmatched order(s) remain open at end of file.")

    return trades


def analyze_file(filepath: str) -> dict:
    orders = load_orders(filepath)
    trades = match_trades(orders)

    pnls = [t.pnl for t in trades]
    returns = [t.return_pct for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    win_pct = [r for r in returns if r > 0]
    loss_pct = [r for r in returns if r <= 0]

    return {
        'filepath': filepath,
        'total_orders': len(orders),
        'trades': trades,
        'total_trades': len(trades),
        'winning_trades': len(wins),
        'losing_trades': len(losses),
        'total_pnl': sum(pnls),
        'avg_pnl': sum(pnls) / len(pnls) if pnls else 0.0,
        'avg_win': sum(win_pct) / len(win_pct) if win_pct else 0.0,
        'avg_loss': sum(loss_pct) / len(loss_pct) if loss_pct else 0.0,
        'win_rate': len(wins) / len(trades) * 100 if trades else 0.0,
        'avg_return_pct': sum(returns) / len(trades) if trades else 0.0,
    }


def print_trade_table(trades: List[Trade]):
    hdr = f"{'#':>4}  {'Dir':>5}  {'Sym':>6}  {'Entry Time':<19}  {'Entry$':>9}  {'Exit$':>9}  {'PnL':>10}  {'Ret%':>8}"
    print(hdr)
    print('─' * len(hdr))
    for i, t in enumerate(trades, 1):
        print(
            f"{i:>4}  {t.direction:>5}  {t.symbol:>6}  "
            f"{t.entry_time[:19]:<19}  "
            f"{t.entry_price:>9.4f}  {t.exit_price:>9.4f}  "
            f"${t.pnl:>+9.2f}  {t.return_pct:>+7.4f}%"
        )


def print_summary(label: str, results: list):
    all_trades = [t for r in results for t in r['trades']]
    pnls = [t.pnl for t in all_trades]
    wins = [p for p in pnls if p > 0]
    n = len(pnls)

    print(f"\n{'═'*60}")
    print(f"  {label}")
    print(f"{'═'*60}")
    print(f"  Files        : {len(results)}")
    print(f"  Total Trades : {n}")
    print(f"  Wins / Losses: {len(wins)} / {n - len(wins)}")
    print(f"  Win Rate     : {len(wins)/n*100:.1f}%" if n else "  Win Rate: N/A")
    print(f"  Total PnL    : ${sum(pnls):+,.2f}")
    print(f"  Avg PnL/Trade: ${sum(pnls)/n:+,.2f}" if n else "  Avg PnL: N/A")
    avg_ret = sum(t.return_pct for t in all_trades) / n if n else 0
    print(f"  Avg Ret/Trade: {avg_ret:+.4f}%")


def main():
    pattern = "temp/other/ORB_*.json"
    files = sorted(glob.glob(pattern))

    if not files:
        print(f"No files found matching: {pattern}")
        return

    print(f"Found {len(files)} file(s):")
    for f in files:
        print(f"  {f}")

    all_results = []

    for filepath in files:
        result = analyze_file(filepath)
        all_results.append(result)

        filename = os.path.basename(filepath)
        print(f"\n{'═'*60}")
        print(f"  {filename}")
        print(f"{'═'*60}")
        print(f"  Orders       : {result['total_orders']}")
        print(f"  Trades       : {result['total_trades']}")
        print(f"  Wins / Losses: {result['winning_trades']} / {result['losing_trades']}")
        print(f"  Win Rate     : {result['win_rate']:.1f}%")
        print(f"  Total PnL    : ${result['total_pnl']:+,.2f}")
        print(f"  Avg Win%: {result['avg_win']:+,.2f}%")
        print(f"  Avg Loss%: {result['avg_loss']:+,.2f}%")
        print(f"  Avg PnL/Trade: ${result['avg_pnl']:+,.2f}")
        print(f"  Avg Ret/Trade: {result['avg_return_pct']:+.4f}%")
        print()
        print_trade_table(result['trades'])

    if len(all_results) > 1:
        print_summary("AGGREGATE ACROSS ALL FILES", all_results)


if __name__ == '__main__':
    main()
