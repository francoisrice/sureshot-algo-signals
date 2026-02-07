"""
Stock Scanner for ORB Strategy

Scans for stocks meeting criteria:
- High volume (top percentile)
- ATR > 10% of price
- Price > $5
"""

import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import SureshotSDK

logger = logging.getLogger(__name__)


class StockScanner:
    """
    Scans for high-volume, volatile stocks suitable for ORB trading
    """

    def __init__(
        self,
        min_price: float = 5.0,
        min_atr_percent: float = 10.0,
        atr_period: int = 14,
        volume_lookback_days: int = 20
    ):
        """
        Initialize scanner

        Args:
            min_price: Minimum stock price
            min_atr_percent: Minimum ATR as % of price
            atr_period: ATR calculation period
            volume_lookback_days: Days to look back for volume average
        """
        self.min_price = min_price
        self.min_atr_percent = min_atr_percent
        self.atr_period = atr_period
        self.volume_lookback_days = volume_lookback_days
        self.polygon_client = SureshotSDK.PolygonClient()

    def get_sp500_tickers(self) -> List[str]:
        """
        Get list of S&P 500 tickers to scan

        In production, this would fetch from a data source
        For now, return a curated list of liquid stocks
        """
        # High-volume, liquid stocks suitable for day trading
        tickers = [
            "SPY", "QQQ", "IWM",  # ETFs
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META",  # Mega caps
            "AMD", "NFLX", "DIS", "BA", "COIN", "PYPL", "SQ",  # Volatile stocks
            "XLF", "XLE", "XLK", "XLV", "XLI",  # Sector ETFs
        ]
        return tickers

    def calculate_atr_percent(self, symbol: str, currentDate: datetime = None) -> Optional[float]:
        """
        Calculate ATR as percentage of current price

        Args:
            symbol: Stock symbol

        Returns:
            ATR percentage or None if unable to calculate
        """
        try:
            # Get recent data for ATR calculation
            if not currentDate:
                end_date = datetime.now()
            start_date = end_date - timedelta(days=self.atr_period + 10)

            bars = self.polygon_client.get_historical_data(
                symbol=symbol,
                start_date=start_date.strftime("%Y-%m-%d"),
                end_date=end_date.strftime("%Y-%m-%d"),
                timeframe="1d"
            )

            if not bars or len(bars) < self.atr_period:
                return None

            # Calculate ATR
            atr = SureshotSDK.ATR(symbol, self.atr_period)

            for bar in bars:
                atr.update(bar['high'], bar['low'], bar['close'])

            atr_value = atr.get_value()
            current_price = bars[-1]['close']

            if current_price == 0:
                return None

            atr_percent = (atr_value / current_price) * 100

            return atr_percent

        except Exception as e:
            logger.error(f"Error calculating ATR for {symbol}: {e}")
            return None

    def get_average_volume(self, symbol: str) -> Optional[float]:
        """
        Get average volume over lookback period

        Args:
            symbol: Stock symbol

        Returns:
            Average volume or None if unable to calculate
        """
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=self.volume_lookback_days + 10)

            bars = self.polygon_client.get_historical_data(
                symbol=symbol,
                start_date=start_date.strftime("%Y-%m-%d"),
                end_date=end_date.strftime("%Y-%m-%d"),
                timeframe="1d"
            )

            if not bars or len(bars) < self.volume_lookback_days:
                return None

            volumes = [bar['volume'] for bar in bars[-self.volume_lookback_days:]]
            avg_volume = sum(volumes) / len(volumes)

            return avg_volume

        except Exception as e:
            logger.error(f"Error getting volume for {symbol}: {e}")
            return None

    def get_current_price(self, symbol: str) -> Optional[float]:
        """Get current price for symbol"""
        try:
            price = self.polygon_client.get_current_price(symbol)
            return price
        except Exception as e:
            logger.error(f"Error getting price for {symbol}: {e}")
            return None

    def scan(self, max_candidates: int = 5) -> List[Dict]:
        """
        Scan for top candidates

        Args:
            max_candidates: Maximum number of stocks to return

        Returns:
            List of dicts with symbol, price, atr_percent, avg_volume
        """
        logger.info(f"Scanning for stocks with min price ${self.min_price}, min ATR {self.min_atr_percent}%...")

        tickers = self.get_sp500_tickers()
        candidates = []

        for symbol in tickers:
            logger.debug(f"Scanning {symbol}...")

            # Get current price
            price = self.get_current_price(symbol)
            if not price or price < self.min_price:
                logger.debug(f"  {symbol}: Price ${price} below minimum")
                continue

            # Calculate ATR%
            atr_percent = self.calculate_atr_percent(symbol)
            if not atr_percent or atr_percent < self.min_atr_percent:
                logger.debug(f"  {symbol}: ATR% {atr_percent:.2f}% below minimum")
                continue

            # Get average volume
            avg_volume = self.get_average_volume(symbol)
            if not avg_volume:
                logger.debug(f"  {symbol}: Unable to get volume data")
                continue

            candidate = {
                'symbol': symbol,
                'price': price,
                'atr_percent': atr_percent,
                'avg_volume': avg_volume,
                'score': avg_volume * atr_percent  # Simple score: volume * volatility
            }

            candidates.append(candidate)
            logger.info(f"  {symbol}: Price ${price:.2f}, ATR {atr_percent:.2f}%, Vol {avg_volume:,.0f}, Score {candidate['score']:,.0f}")

        # Sort by score (volume * volatility) and take top N
        candidates.sort(key=lambda x: x['score'], reverse=True)
        top_candidates = candidates[:max_candidates]

        logger.info(f"Found {len(top_candidates)} candidates:")
        for i, c in enumerate(top_candidates, 1):
            logger.info(f"  {i}. {c['symbol']}: ${c['price']:.2f}, ATR {c['atr_percent']:.1f}%, Vol {c['avg_volume']:,.0f}")

        return top_candidates

    def get_top_candidate(self) -> Optional[str]:
        """
        Get the single best candidate symbol

        Returns:
            Symbol of top candidate or None
        """
        candidates = self.scan(max_candidates=1)

        if candidates:
            return candidates[0]['symbol']
        else:
            return None
