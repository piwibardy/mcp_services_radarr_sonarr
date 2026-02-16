#!/usr/bin/env python
"""Main MCP server implementation for Radarr/Sonarr."""

import json
import logging
from typing import Dict, Optional

from fastmcp import FastMCP

from .config import Config, SonarrConfig, load_config
from .services.radarr_service import RadarrService, Movie
from .services.sonarr_service import SonarrService

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Tool name mapping: instance name -> (get_tool_name, lookup_tool_name, content_label)
SONARR_TOOL_NAMES = {
    "sonarr": ("get_available_series", "lookup_series", "series"),
    "sonarr_anime": ("get_available_anime", "lookup_anime", "anime"),
}


def _sonarr_tool_names(instance_name: str) -> tuple:
    """Get tool names for a Sonarr instance. Falls back to generic naming."""
    if instance_name in SONARR_TOOL_NAMES:
        return SONARR_TOOL_NAMES[instance_name]
    # Generic fallback for unknown instance names
    safe = instance_name.replace("-", "_")
    return (f"get_available_{safe}", f"lookup_{safe}", safe)


# -----------------------------------------------------------------------------
# Helper function to check watched status from multiple sources
# -----------------------------------------------------------------------------

def _is_watched_series(series, config: Config, sonarr_service: SonarrService) -> bool:
    """Check if a series is watched using available media services.

    ``series`` can be a Series object or a string title.  Jellyfin/Plex
    checks use the title, while the Sonarr fallback needs the full object.
    """
    title = series.title if hasattr(series, "title") else series
    statuses = []
    if config.jellyfin_config.base_url:
        from .services.jellyfin_service import JellyfinService
        jellyfin = JellyfinService({
            "baseUrl": config.jellyfin_config.base_url,
            "apiKey": config.jellyfin_config.api_key,
            "userId": config.jellyfin_config.user_id,
        })
        try:
            statuses.append(jellyfin.is_series_watched(title))
        except Exception as e:
            logger.error(f"Jellyfin check failed for {title}: {e}")
    if config.plex_config.base_url:
        from .services.plex_service import PlexService
        plex = PlexService({
            "baseUrl": config.plex_config.base_url,
            "token": config.plex_config.token,
        })
        try:
            statuses.append(plex.is_series_watched(title))
        except Exception as e:
            logger.error(f"Plex check failed for {title}: {e}")
    if statuses:
        return any(statuses)
    # Sonarr fallback needs the full Series object
    if hasattr(series, "statistics"):
        return sonarr_service.is_series_watched(series)
    return False


def _is_watched_movie(title: str, config: Config) -> bool:
    """Check if a movie is watched using available media services."""
    statuses = []
    if config.jellyfin_config.base_url:
        from .services.jellyfin_service import JellyfinService
        jellyfin = JellyfinService({
            "baseUrl": config.jellyfin_config.base_url,
            "apiKey": config.jellyfin_config.api_key,
            "userId": config.jellyfin_config.user_id,
        })
        try:
            statuses.append(jellyfin.is_movie_watched(title))
        except Exception as e:
            logger.error(f"Jellyfin movie check failed for {title}: {e}")
    if config.plex_config.base_url:
        from .services.plex_service import PlexService
        plex = PlexService({
            "baseUrl": config.plex_config.base_url,
            "token": config.plex_config.token,
        })
        try:
            statuses.append(plex.is_movie_watched(title))
        except Exception as e:
            logger.error(f"Plex movie check failed for {title}: {e}")
    return any(statuses)


# -----------------------------------------------------------------------------
# MCP Server implementation
# -----------------------------------------------------------------------------

class RadarrSonarrMCPServer:
    """MCP Server for Radarr and Sonarr."""

    def __init__(self, config: Config):
        self.config = config
        self.server = FastMCP(
            name="radarr-sonarr-mcp-server",
        )
        self.sonarr_services: Dict[str, SonarrService] = {
            name: SonarrService(cfg)
            for name, cfg in config.sonarr_configs.items()
        }
        self.radarr_service = RadarrService(config.radarr_config)
        self._register_tools()

    # ---- Tools ----

    def _register_tools(self):
        # Register tools for each Sonarr instance
        for instance_name, service in self.sonarr_services.items():
            self._register_sonarr_tools(instance_name, service)

        # Radarr tools (single instance)
        self._register_radarr_tools()

    def _register_sonarr_tools(self, instance_name: str, service: SonarrService):
        get_name, lookup_name, label = _sonarr_tool_names(instance_name)
        config = self.config

        def _make_get_available(svc, lbl):
            def get_available(
                year: Optional[int] = None,
                downloaded: Optional[bool] = None,
                watched: Optional[bool] = None,
                actors: Optional[str] = None,
            ) -> str:
                f"""Get a list of available {lbl} with optional filters."""
                all_series = svc.get_all_series()
                filtered = all_series

                if year is not None:
                    filtered = [s for s in filtered if s.year == year]

                if downloaded is not None:
                    filtered = [
                        s for s in filtered
                        if (s.statistics and s.statistics.episode_file_count > 0) == downloaded
                    ]

                if watched is not None:
                    filtered = [
                        s for s in filtered
                        if _is_watched_series(s, config, svc) == watched
                    ]

                if actors:
                    filtered = [
                        s for s in filtered
                        if s.data.get("credits") and any(
                            actors.lower() in cast.get("name", "").lower()
                            for cast in s.data.get("credits", {}).get("cast", [])
                        )
                    ]

                return json.dumps({
                    "count": len(filtered),
                    lbl: [
                        {
                            "id": s.id,
                            "title": s.title,
                            "year": s.year,
                            "overview": s.overview,
                            "status": s.status,
                            "network": s.network,
                            "genres": s.genres,
                            "watched": _is_watched_series(s, config, svc),
                        }
                        for s in filtered
                    ],
                })
            return get_available

        def _make_lookup(svc, lbl):
            def lookup(term: str) -> str:
                f"""Look up {lbl} by search term."""
                results = svc.lookup_series(term)
                return json.dumps({
                    "count": len(results),
                    lbl: [
                        {"id": s.id, "title": s.title, "year": s.year, "overview": s.overview}
                        for s in results
                    ],
                })
            return lookup

        self.server.tool(name=get_name)(_make_get_available(service, label))
        self.server.tool(name=lookup_name)(_make_lookup(service, label))

    def _register_radarr_tools(self):
        config = self.config
        radarr_service = self.radarr_service

        @self.server.tool()
        def get_available_movies(
            year: Optional[int] = None,
            downloaded: Optional[bool] = None,
            watched: Optional[bool] = None,
            actors: Optional[str] = None,
        ) -> str:
            """Get a list of all available movies with optional filters.

            Watched status is determined using Plex and/or Jellyfin.
            """
            all_movies = radarr_service.get_all_movies()
            filtered = all_movies

            if year is not None:
                filtered = [m for m in filtered if m.year == year]

            if downloaded is not None:
                filtered = [m for m in filtered if m.has_file == downloaded]

            if watched is not None:
                filtered = [
                    m for m in filtered
                    if _is_watched_movie(m.title, config) == watched
                ]

            if actors:
                filtered = [
                    m for m in filtered
                    if m.data.get("credits") and any(
                        actors.lower() in cast.get("name", "").lower()
                        for cast in m.data.get("credits", {}).get("cast", [])
                    )
                ]

            return json.dumps({
                "count": len(filtered),
                "movies": [
                    {
                        "id": m.id,
                        "title": m.title,
                        "year": m.year,
                        "overview": m.overview,
                        "hasFile": m.has_file,
                        "status": m.status,
                        "genres": m.genres or [],
                        "watched": _is_watched_movie(m.title, config),
                    }
                    for m in filtered
                ],
            })

    # ---- Run ----

    def run(self):
        """Start the MCP server with the configured transport."""
        transport = self.config.server_config.transport
        port = self.config.server_config.port
        host = self.config.server_config.host

        instances = ", ".join(self.sonarr_services.keys())
        logger.info(f"Sonarr instances: {instances}")

        if transport == "streamable-http":
            logger.info(f"Starting Radarr-Sonarr MCP Server (HTTP) on {host}:{port}")
            self.server.run(transport="streamable-http", host=host, port=port)
        else:
            logger.info("Starting Radarr-Sonarr MCP Server (stdio)")
            self.server.run()

    def start(self):
        """Alias for run()."""
        self.run()


def create_server(config_path: Optional[str] = None) -> RadarrSonarrMCPServer:
    """Factory function to create a configured server instance."""
    config = load_config(config_path)
    return RadarrSonarrMCPServer(config)


def main():
    """Entry point for running the server."""
    import argparse

    parser = argparse.ArgumentParser(description="Radarr/Sonarr MCP Server")
    parser.add_argument("--config", help="Path to config.json file")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        help="Transport mode (overrides config)",
    )
    parser.add_argument("--port", type=int, help="Port for HTTP transport (overrides config)")
    args = parser.parse_args()

    server = create_server(args.config)

    if args.transport:
        server.config.server_config.transport = args.transport
    if args.port:
        server.config.server_config.port = args.port

    server.run()


if __name__ == "__main__":
    main()
