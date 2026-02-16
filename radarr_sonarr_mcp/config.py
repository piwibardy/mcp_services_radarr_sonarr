"""Configuration management for the Radarr/Sonarr MCP server."""

import json
import os
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class NasConfig:
    """NAS/Server network configuration."""
    ip: str = "10.0.0.23"
    port: str = "7878"


@dataclass
class RadarrConfig:
    """Radarr service configuration."""
    api_key: str = ""
    base_path: str = "/api/v3"
    port: str = "7878"
    host: str = ""  # If empty, uses NasConfig.ip
    url: str = ""   # Full URL override (e.g. https://radarr.example.com)

    @property
    def base_url(self) -> str:
        """Construct the full base URL for Radarr API."""
        if self.url:
            return f"{self.url.rstrip('/')}{self.base_path}"
        return f"http://{self.host}:{self.port}{self.base_path}"


@dataclass
class SonarrConfig:
    """Sonarr service configuration."""
    name: str = "sonarr"  # Instance name: "sonarr", "sonarr_anime", etc.
    api_key: str = ""
    base_path: str = "/api/v3"
    port: str = "8989"
    host: str = ""  # If empty, uses NasConfig.ip
    url: str = ""   # Full URL override (e.g. https://sonarr.example.com)

    @property
    def base_url(self) -> str:
        """Construct the full base URL for Sonarr API."""
        if self.url:
            return f"{self.url.rstrip('/')}{self.base_path}"
        return f"http://{self.host}:{self.port}{self.base_path}"


@dataclass
class JellyfinConfig:
    """Jellyfin service configuration."""
    base_url: str = ""
    api_key: str = ""
    user_id: str = ""


@dataclass
class PlexConfig:
    """Plex service configuration."""
    base_url: str = ""
    token: str = ""


@dataclass
class ServerConfig:
    """MCP server configuration."""
    port: int = 3000
    transport: str = "stdio"  # "stdio" or "streamable-http"
    host: str = "0.0.0.0"


@dataclass
class Config:
    """Main configuration container."""
    nas_config: NasConfig = field(default_factory=NasConfig)
    radarr_config: RadarrConfig = field(default_factory=RadarrConfig)
    sonarr_configs: Dict[str, SonarrConfig] = field(default_factory=lambda: {"sonarr": SonarrConfig()})
    jellyfin_config: JellyfinConfig = field(default_factory=JellyfinConfig)
    plex_config: PlexConfig = field(default_factory=PlexConfig)
    server_config: ServerConfig = field(default_factory=ServerConfig)

    def __post_init__(self):
        """Set host on Radarr/Sonarr configs from NAS config if not already set."""
        if not self.radarr_config.host:
            self.radarr_config.host = self.nas_config.ip
        for cfg in self.sonarr_configs.values():
            if not cfg.host:
                cfg.host = self.nas_config.ip

    @property
    def sonarr_config(self) -> SonarrConfig:
        """Backward-compatible access to the primary Sonarr instance."""
        return self.sonarr_configs.get("sonarr", next(iter(self.sonarr_configs.values())))


def _config_from_env() -> Config:
    """Load configuration from environment variables."""
    nas_ip = os.environ.get("NAS_IP", "10.0.0.23")
    transport = os.environ.get("MCP_TRANSPORT", "stdio")

    nas = NasConfig(ip=nas_ip, port=os.environ.get("RADARR_PORT", "7878"))

    radarr = RadarrConfig(
        api_key=os.environ.get("RADARR_API_KEY", ""),
        base_path=os.environ.get("RADARR_BASE_PATH", "/api/v3"),
        port=os.environ.get("RADARR_PORT", "7878"),
        host=nas_ip,
        url=os.environ.get("RADARR_URL", ""),
    )

    # Primary Sonarr instance
    sonarr_configs: Dict[str, SonarrConfig] = {}
    sonarr_api_key = os.environ.get("SONARR_API_KEY", "")
    if sonarr_api_key:
        sonarr_configs["sonarr"] = SonarrConfig(
            name="sonarr",
            api_key=sonarr_api_key,
            base_path=os.environ.get("SONARR_BASE_PATH", "/api/v3"),
            port=os.environ.get("SONARR_PORT", "8989"),
            host=nas_ip,
            url=os.environ.get("SONARR_URL", ""),
        )

    # Sonarr Anime instance
    anime_api_key = os.environ.get("SONARR_ANIME_API_KEY", "")
    if anime_api_key:
        sonarr_configs["sonarr_anime"] = SonarrConfig(
            name="sonarr_anime",
            api_key=anime_api_key,
            base_path=os.environ.get("SONARR_ANIME_BASE_PATH", "/api/v3"),
            port=os.environ.get("SONARR_ANIME_PORT", "8990"),
            host=nas_ip,
            url=os.environ.get("SONARR_ANIME_URL", ""),
        )

    # Fallback: at least one empty Sonarr config
    if not sonarr_configs:
        sonarr_configs["sonarr"] = SonarrConfig(name="sonarr", host=nas_ip)

    jellyfin = JellyfinConfig(
        base_url=os.environ.get("JELLYFIN_BASE_URL", ""),
        api_key=os.environ.get("JELLYFIN_API_KEY", ""),
        user_id=os.environ.get("JELLYFIN_USER_ID", ""),
    )

    plex = PlexConfig(
        base_url=os.environ.get("PLEX_BASE_URL", ""),
        token=os.environ.get("PLEX_TOKEN", ""),
    )

    server = ServerConfig(
        port=int(os.environ.get("MCP_SERVER_PORT", "3000")),
        transport=transport,
        host=os.environ.get("MCP_HOST", "0.0.0.0"),
    )

    return Config(
        nas_config=nas,
        radarr_config=radarr,
        sonarr_configs=sonarr_configs,
        jellyfin_config=jellyfin,
        plex_config=plex,
        server_config=server,
    )


def _config_from_dict(data: dict) -> Config:
    """Build a Config from a JSON-style dictionary."""
    nas_ip = data.get("nasConfig", {}).get("ip", "10.0.0.23")

    nas = NasConfig(
        ip=nas_ip,
        port=data.get("nasConfig", {}).get("port", "7878"),
    )

    rc = data.get("radarrConfig", {})
    radarr = RadarrConfig(
        api_key=rc.get("apiKey", ""),
        base_path=rc.get("basePath", "/api/v3"),
        port=rc.get("port", "7878"),
        host=nas_ip,
        url=rc.get("url", ""),
    )

    # Multi-instance Sonarr: "sonarrConfigs" dict
    sonarr_configs: Dict[str, SonarrConfig] = {}
    if "sonarrConfigs" in data:
        for name, sc in data["sonarrConfigs"].items():
            sonarr_configs[name] = SonarrConfig(
                name=name,
                api_key=sc.get("apiKey", ""),
                base_path=sc.get("basePath", "/api/v3"),
                port=sc.get("port", "8989"),
                host=nas_ip,
                url=sc.get("url", ""),
            )
    # Backward compat: single "sonarrConfig"
    elif "sonarrConfig" in data:
        sc = data["sonarrConfig"]
        sonarr_configs["sonarr"] = SonarrConfig(
            name="sonarr",
            api_key=sc.get("apiKey", ""),
            base_path=sc.get("basePath", "/api/v3"),
            port=sc.get("port", "8989"),
            host=nas_ip,
        )
    else:
        sonarr_configs["sonarr"] = SonarrConfig(name="sonarr", host=nas_ip)

    jc = data.get("jellyfinConfig", {})
    jellyfin = JellyfinConfig(
        base_url=jc.get("baseUrl", ""),
        api_key=jc.get("apiKey", ""),
        user_id=jc.get("userId", ""),
    )

    pc = data.get("plexConfig", {})
    plex = PlexConfig(
        base_url=pc.get("baseUrl", ""),
        token=pc.get("token", ""),
    )

    srv = data.get("server", {})
    server = ServerConfig(
        port=int(srv.get("port", 3000)),
        transport=srv.get("transport", "stdio"),
        host=srv.get("host", "0.0.0.0"),
    )

    return Config(
        nas_config=nas,
        radarr_config=radarr,
        sonarr_configs=sonarr_configs,
        jellyfin_config=jellyfin,
        plex_config=plex,
        server_config=server,
    )


def load_config(path: Optional[str] = None) -> Config:
    """Load configuration from env vars (priority) or a JSON file.

    If RADARR_API_KEY or SONARR_API_KEY env vars are set, env vars take
    priority.  Otherwise falls back to ``path`` (default ``config.json``).
    """
    if os.environ.get("RADARR_API_KEY") or os.environ.get("SONARR_API_KEY"):
        return _config_from_env()

    config_path = path or "config.json"
    try:
        with open(config_path, "r") as f:
            data = json.load(f)
        return _config_from_dict(data)
    except FileNotFoundError:
        return _config_from_env()


def _config_to_dict(config: Config) -> dict:
    """Serialize a Config to a JSON-compatible dictionary."""
    sonarr_configs_dict = {}
    for name, sc in config.sonarr_configs.items():
        sonarr_configs_dict[name] = {
            "apiKey": sc.api_key,
            "basePath": sc.base_path,
            "port": sc.port,
            "url": sc.url,
        }

    return {
        "nasConfig": {
            "ip": config.nas_config.ip,
            "port": config.nas_config.port,
        },
        "radarrConfig": {
            "apiKey": config.radarr_config.api_key,
            "basePath": config.radarr_config.base_path,
            "port": config.radarr_config.port,
            "url": config.radarr_config.url,
        },
        "sonarrConfigs": sonarr_configs_dict,
        "jellyfinConfig": {
            "baseUrl": config.jellyfin_config.base_url,
            "apiKey": config.jellyfin_config.api_key,
            "userId": config.jellyfin_config.user_id,
        },
        "plexConfig": {
            "baseUrl": config.plex_config.base_url,
            "token": config.plex_config.token,
        },
        "server": {
            "port": config.server_config.port,
            "transport": config.server_config.transport,
            "host": config.server_config.host,
        },
    }


def save_config(config: Config, path: str = "config.json") -> None:
    """Save configuration to a JSON file."""
    with open(path, "w") as f:
        json.dump(_config_to_dict(config), f, indent=2)
