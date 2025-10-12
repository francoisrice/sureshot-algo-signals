"""
Vault client for fetching secrets in Kubernetes environments
"""
import os
import logging
from typing import Optional, Dict, Any

try:
    import hvac
    HVAC_AVAILABLE = True
except ImportError:
    HVAC_AVAILABLE = False

logger = logging.getLogger(__name__)


class VaultClient:
    """Client for fetching secrets from HashiCorp Vault"""

    def __init__(
        self,
        vault_addr: Optional[str] = None,
        vault_role: Optional[str] = None,
        use_kubernetes_auth: bool = True
    ):
        """
        Initialize Vault client

        Args:
            vault_addr: Vault server address (default: http://vault.vault.svc.cluster.local:8200)
            vault_role: Kubernetes auth role (default: sureshot-algo)
            use_kubernetes_auth: Whether to use Kubernetes authentication
        """
        if not HVAC_AVAILABLE:
            raise ImportError(
                "hvac library is required for Vault integration. "
                "Install it with: pip install hvac"
            )

        self.vault_addr = vault_addr or os.getenv(
            'VAULT_ADDR',
            'http://vault.vault.svc.cluster.local:8200'
        )
        self.vault_role = vault_role or os.getenv('VAULT_ROLE', 'sureshot-algo')
        self.use_kubernetes_auth = use_kubernetes_auth

        self.client = hvac.Client(url=self.vault_addr)
        self._authenticated = False

        # Auto-authenticate on initialization
        if self.use_kubernetes_auth:
            self._authenticate_kubernetes()

    def _authenticate_kubernetes(self):
        """Authenticate with Vault using Kubernetes service account"""
        try:
            # Read the service account JWT token
            jwt_path = '/var/run/secrets/kubernetes.io/serviceaccount/token'

            if not os.path.exists(jwt_path):
                logger.warning(
                    f"Kubernetes service account token not found at {jwt_path}. "
                    "Running outside Kubernetes?"
                )
                return

            with open(jwt_path, 'r') as f:
                jwt = f.read().strip()

            # Authenticate with Vault
            response = self.client.auth.kubernetes.login(
                role=self.vault_role,
                jwt=jwt
            )

            if response and 'auth' in response:
                self._authenticated = True
                logger.info("Successfully authenticated with Vault using Kubernetes auth")
            else:
                logger.error("Failed to authenticate with Vault")

        except Exception as e:
            logger.error(f"Error authenticating with Vault: {e}")
            raise

    def authenticate_token(self, token: str):
        """
        Authenticate with Vault using a token

        Args:
            token: Vault token
        """
        self.client.token = token
        if self.client.is_authenticated():
            self._authenticated = True
            logger.info("Successfully authenticated with Vault using token")
        else:
            logger.error("Failed to authenticate with Vault using provided token")

    def get_secret(self, path: str, key: Optional[str] = None) -> Optional[Any]:
        """
        Get a secret from Vault

        Args:
            path: Secret path (e.g., 'sureshot-algo/polygon')
            key: Specific key within the secret (e.g., 'api_key')

        Returns:
            Secret value(s) or None if not found
        """
        if not self._authenticated:
            logger.error("Not authenticated with Vault")
            return None

        try:
            # Read secret from KV v2 engine
            secret_response = self.client.secrets.kv.v2.read_secret_version(
                path=path,
                mount_point='secret'
            )

            if not secret_response or 'data' not in secret_response:
                logger.error(f"Secret not found at path: {path}")
                return None

            secret_data = secret_response['data']['data']

            if key:
                return secret_data.get(key)
            else:
                return secret_data

        except Exception as e:
            logger.error(f"Error fetching secret from Vault: {e}")
            return None

    def get_polygon_api_key(self) -> Optional[str]:
        """
        Convenience method to get Polygon API key

        Returns:
            Polygon API key or None
        """
        return self.get_secret('sureshot-algo/polygon', 'api_key')

    def list_secrets(self, path: str) -> Optional[list]:
        """
        List secrets at a given path

        Args:
            path: Path to list (e.g., 'sureshot-algo')

        Returns:
            List of secret names or None
        """
        if not self._authenticated:
            logger.error("Not authenticated with Vault")
            return None

        try:
            response = self.client.secrets.kv.v2.list_secrets(
                path=path,
                mount_point='secret'
            )

            if response and 'data' in response and 'keys' in response['data']:
                return response['data']['keys']

            return []

        except Exception as e:
            logger.error(f"Error listing secrets from Vault: {e}")
            return None

    def is_authenticated(self) -> bool:
        """Check if client is authenticated"""
        return self._authenticated and self.client.is_authenticated()


def get_secret_from_vault(path: str, key: Optional[str] = None) -> Optional[Any]:
    """
    Helper function to quickly get a secret from Vault

    Args:
        path: Secret path
        key: Specific key within secret

    Returns:
        Secret value or None
    """
    try:
        vault_client = VaultClient()
        return vault_client.get_secret(path, key)
    except Exception as e:
        logger.error(f"Error getting secret from Vault: {e}")
        return None


def get_polygon_api_key_from_vault() -> Optional[str]:
    """
    Helper function to get Polygon API key from Vault

    Returns:
        Polygon API key or None
    """
    return get_secret_from_vault('sureshot-algo/polygon', 'api_key')
