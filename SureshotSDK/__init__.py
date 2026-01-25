from .TradingStrategy import TradingStrategy
from .SMA import SMA
from .Portfolio import Portfolio
from .utils import get_system_time, format_price, is_market_open
from .Polygon import PolygonClient
from .ibkr.automation import IBKRClient
from .BacktestEngine import BacktestEngine, Trade
from .BacktestRunner import BacktestRunner
from .BacktestingPriceCache import BacktestingPriceCache

# Vault client is optional - only import if running in a cluster with Vault for secrets management
try:
    from .vault_client import VaultClient, get_secret_from_vault, get_polygon_api_key_from_vault
    __all__ = [
        'TradingStrategy', 'SMA', 'Portfolio',
        'get_system_time', 'format_price', 'is_market_open',
        'PolygonClient', 'VaultClient',
        'get_secret_from_vault', 'get_polygon_api_key_from_vault', 'IBKRClient',
        'BacktestEngine', 'BacktestRunner', 'BacktestingPriceCache', 'Trade'
    ]
except ImportError:
    __all__ = [
        'TradingStrategy', 'SMA', 'Portfolio',
        'get_system_time', 'format_price', 'is_market_open',
        'PolygonClient', 'IBKRClient',
        'BacktestEngine', 'BacktestRunner', 'BacktestingPriceCache', 'Trade'
    ]