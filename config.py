"""
Configuration management for PSAP voice bridge system.

This module provides centralized, validated configuration that:
- Loads environment variables from .env
- Validates required configuration at startup
- Provides typed access to config values
- Makes dependencies explicit throughout the codebase
"""

from dotenv import load_dotenv
import os
from typing import Optional
from dataclasses import dataclass
import logging

# Load .env file at module import time
load_dotenv()

logger = logging.getLogger(__name__)


class ConfigurationError(Exception):
    """Raised when required configuration is missing or invalid."""
    pass


@dataclass
class DiscordConfig:
    """Discord bot configuration."""
    bot_token: str
    guild_id: int
    channel_id: int
    
    @classmethod
    def from_env(cls) -> "DiscordConfig":
        """Load Discord configuration from environment variables."""
        bot_token = os.getenv("DISCORD_BOT_TOKEN")
        if not bot_token:
            raise ConfigurationError("DISCORD_BOT_TOKEN not set in environment")
        
        try:
            guild_id = int(os.getenv("DISCORD_GUILD_ID", "0"))
            channel_id = int(os.getenv("DISCORD_CHANNEL_ID", "0"))
        except (ValueError, TypeError) as e:
            raise ConfigurationError(
                f"DISCORD_GUILD_ID and DISCORD_CHANNEL_ID must be integers: {e}"
            )
        
        if guild_id == 0 or channel_id == 0:
            raise ConfigurationError(
                "DISCORD_GUILD_ID and DISCORD_CHANNEL_ID must be set and non-zero"
            )
        
        return cls(
            bot_token=bot_token,
            guild_id=guild_id,
            channel_id=channel_id
        )


@dataclass
class TwilioConfig:
    """Twilio service configuration."""
    account_sid: str
    auth_token: str
    phone_number: str
    server_port: int
    ws_path: str
    
    @classmethod
    def from_env(cls) -> "TwilioConfig":
        """Load Twilio configuration from environment variables."""
        account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        phone_number = os.getenv("TWILIO_PHONE_NUMBER")
        
        if not account_sid or not auth_token:
            raise ConfigurationError(
                "TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN must be set"
            )
        
        if not phone_number:
            raise ConfigurationError("TWILIO_PHONE_NUMBER must be set")
        
        try:
            server_port = int(os.getenv("TWILIO_SERVER_PORT", "8080"))
        except ValueError:
            raise ConfigurationError("TWILIO_SERVER_PORT must be an integer")
        
        ws_path = os.getenv("TWILIO_WS_PATH", "/ws")
        
        return cls(
            account_sid=account_sid,
            auth_token=auth_token,
            phone_number=phone_number,
            server_port=server_port,
            ws_path=ws_path
        )


@dataclass
class NetworkConfig:
    """Network and connectivity configuration."""
    ngrok_domain: str
    node_ws_port: int
    
    @property
    def public_wss_url(self) -> str:
        """Get the public WebSocket URL for Twilio callbacks."""
        return f"wss://{self.ngrok_domain}/ws"
    
    @property
    def node_ws_url(self) -> str:
        """Get the local Node.js WebSocket URL for bridge communication."""
        return f"ws://localhost:{self.node_ws_port}"
    
    @classmethod
    def from_env(cls) -> "NetworkConfig":
        """Load network configuration from environment variables."""
        ngrok_domain = os.getenv("NGROK_DOMAIN")
        if not ngrok_domain:
            raise ConfigurationError("NGROK_DOMAIN must be set")
        
        try:
            node_ws_port = int(os.getenv("NODE_WS_PORT", "3001"))
        except ValueError:
            raise ConfigurationError("NODE_WS_PORT must be an integer")
        
        return cls(
            ngrok_domain=ngrok_domain,
            node_ws_port=node_ws_port
        )


@dataclass
class Config:
    """
    Complete system configuration.
    
    Usage:
        from config import get_config
        
        config = get_config()
        print(config.discord.bot_token)
        print(config.twilio.phone_number)
        print(config.network.public_wss_url)
    """
    discord: DiscordConfig
    twilio: TwilioConfig
    network: NetworkConfig
    
    def log_config(self) -> None:
        """Log configuration (with secrets redacted) for debugging."""
        logger.info("=== PSAP Configuration ===")
        logger.info(f"Discord Guild: {self.discord.guild_id}")
        logger.info(f"Discord Channel: {self.discord.channel_id}")
        logger.info(f"Discord Token: {'*' * 20}...{self.discord.bot_token[-4:]}")
        logger.info(f"Twilio Phone: {self.twilio.phone_number}")
        logger.info(f"Twilio SID: {self.twilio.account_sid[:8]}...")
        logger.info(f"Twilio Server Port: {self.twilio.server_port}")
        logger.info(f"Twilio WS Path: {self.twilio.ws_path}")
        logger.info(f"Ngrok Domain: {self.network.ngrok_domain}")
        logger.info(f"Public WSS URL: {self.network.public_wss_url}")
        logger.info(f"Node WS Port: {self.network.node_ws_port}")
        logger.info(f"Node WS URL: {self.network.node_ws_url}")
        logger.info("=" * 27)


# Singleton instance
_config: Optional[Config] = None


def get_config() -> Config:
    """
    Get the global configuration instance.
    
    This function lazily loads configuration on first access and
    validates all required values are present.
    
    Returns:
        Config: The validated configuration object
        
    Raises:
        ConfigurationError: If required configuration is missing or invalid
    """
    global _config
    
    if _config is None:
        _config = Config(
            discord=DiscordConfig.from_env(),
            twilio=TwilioConfig.from_env(),
            network=NetworkConfig.from_env()
        )
    
    return _config


def reset_config() -> None:
    """Reset configuration singleton. Useful for testing."""
    global _config
    _config = None


if __name__ == "__main__":
    # Test configuration loading
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(message)s'
    )
    
    try:
        config = get_config()
        config.log_config()
        print("\n✅ Configuration loaded successfully!")
    except ConfigurationError as e:
        print(f"\n❌ Configuration error: {e}")
        exit(1)