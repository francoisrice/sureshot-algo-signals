from .Scheduler import Scheduler
from .SMA import SMA
from .Portfolio import Portfolio
from .utils import get_system_time, format_price, is_market_open
from .Polygon import PolygonClient

# Vault client is optional - only import if hvac is available
try:
    from .vault_client import VaultClient, get_secret_from_vault, get_polygon_api_key_from_vault
    __all__ = [
        'Scheduler', 'SMA', 'Portfolio',
        'get_system_time', 'format_price', 'is_market_open',
        'PolygonClient', 'VaultClient',
        'get_secret_from_vault', 'get_polygon_api_key_from_vault'
    ]
except ImportError:
    __all__ = [
        'Scheduler', 'SMA', 'Portfolio',
        'get_system_time', 'format_price', 'is_market_open',
        'PolygonClient'
    ]