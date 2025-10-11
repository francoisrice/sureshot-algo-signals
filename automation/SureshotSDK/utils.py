from datetime import datetime
import pytz
from typing import Optional

def get_system_time() -> datetime:
    """
    Get the current system time in New York timezone

    Returns:
        Current datetime in NY timezone
    """
    ny_tz = pytz.timezone('America/New_York')
    return datetime.now(ny_tz)

def format_price(price: float, decimals: int = 2) -> str:
    """
    Format a price for display

    Args:
        price: Price to format
        decimals: Number of decimal places

    Returns:
        Formatted price string
    """
    return f"${price:.{decimals}f}"

def is_market_open() -> bool:
    """
    Check if the market is currently open based on NY time
    This checks for weekdays and market hours (9:30 AM - 4:00 PM ET)
    Note: This doesn't account for market holidays

    Returns:
        True if market is likely open, False otherwise
    """
    ny_tz = pytz.timezone('America/New_York')
    now = datetime.now(ny_tz)

    # Check if it's a weekday (Monday = 0, Sunday = 6)
    if now.weekday() >= 5:  # Saturday or Sunday
        return False

    # Check if it's during market hours (9:30 AM - 4:00 PM ET)
    hour = now.hour
    minute = now.minute

    # Market opens at 9:30 AM ET
    market_open = hour > 9 or (hour == 9 and minute >= 30)

    # Market closes at 4:00 PM ET
    market_close = hour < 16

    return market_open and market_close