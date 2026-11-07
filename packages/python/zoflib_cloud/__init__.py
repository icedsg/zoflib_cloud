from .errors import CloudError, CancelToken, CODES, CONTRACT_VERSION
from .core import CloudStore, MemoryBackend, CAPABILITIES
from .s3 import S3Backend, S3Config, Credential
from .presets import load_presets, config_from_preset

__all__ = ["CloudError", "CancelToken", "CODES", "CONTRACT_VERSION", "CloudStore", "MemoryBackend", "CAPABILITIES",
           "S3Backend", "S3Config", "Credential", "load_presets", "config_from_preset"]
__version__ = "0.1.0"


def s3_store(config, credentials, cancel=None):
    """CloudStore over generic S3. credentials(credential_ref, session_token_ref) -> Credential."""
    return CloudStore(S3Backend(config, credentials, cancel), config.root)
