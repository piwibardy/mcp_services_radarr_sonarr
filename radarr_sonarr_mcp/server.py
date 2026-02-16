#!/usr/bin/env python
"""Main MCP server implementation for Radarr/Sonarr."""

import json
import logging
from typing import Optional

from fastmcp import FastMCP

from .config import Config, load_config
from .services.radarr_service import RadarrService, Movie
from .services.sonarr_service import SonarrService

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Helper function to check watched status from multiple sources
# -----------------------------------------------------------------------------

def _is_watched_series(title: str, config: Config, sonarr_service: SonarrService) -> bool:
    """Check if a series is watched using available media services."""
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
    return sonarr_service.is_series_watched(title)


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
            description="MCP Server for Radarr and Sonarr media management",
        )
        self.sonarr_service = SonarrService(config.sonarr_config)
        self.radarr_service = RadarrService(config.radarr_config)
        self._register_tools()
        self._register_resources()

    # ---- Tools ----

    def _register_tools(self):
        @self.server.tool()
        def get_available_series(
            year: Optional[int] = None,
            downloaded: Optional[bool] = None,
            watched: Optional[bool] = None,
            actors: Optional[str] = None,
        ) -> str:
            """Get a list of available TV series with optional filters.

            Watched status is determined using Plex and/or Jellyfin; if either
            reports watched, the series is considered watched.
            """
            all_series = self.sonarr_service.get_all_series()
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
                    if _is_watched_series(s.title, self.config, self.sonarr_service) == watched
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
                "series": [
                    {
                        "id": s.id,
                        "title": s.title,
                        "year": s.year,
                        "overview": s.overview,
                        "status": s.status,
                        "network": s.network,
                        "genres": s.genres,
                        "watched": _is_watched_series(s.title, self.config, self.sonarr_service),
                    }
                    for s in filtered
                ],
            })

        @self.server.tool()
        def lookup_series(term: str) -> str:
            """Look up TV series by search term."""
            results = self.sonarr_service.lookup_series(term)
            return json.dumps({
                "count": len(results),
                "series": [
                    {"id": s.id, "title": s.title, "year": s.year, "overview": s.overview}
                    for s in results
                ],
            })

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
            all_movies = self.radarr_service.get_all_movies()
            filtered = all_movies

            if year is not None:
                filtered = [m for m in filtered if m.year == year]

            if downloaded is not None:
                filtered = [m for m in filtered if m.has_file == downloaded]

            if watched is not None:
                filtered = [
                    m for m in filtered
                    if _is_watched_movie(m.title, self.config) == watched
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
                        "watched": _is_watched_movie(m.title, self.config),
                    }
                    for m in filtered
                ],
            })

    # ---- Resources ----

    def _register_resources(self):
        @self.server.resource("http://example.com/series", description="TV series collection from Sonarr")
        def series() -> dict:
            series_list = self.sonarr_service.get_all_series()
            return {
                "count": len(series_list),
                "series": [
                    {"id": s.id, "title": s.title, "year": s.year}
                    for s in series_list
                ],
            }

        @self.server.resource("http://example.com/movies", description="Movie collection from Radarr")
        def movies() -> dict:
            movies_list = self.radarr_service.get_all_movies()
            return {
                "count": len(movies_list),
                "movies": [
                    {"id": m.id, "title": m.title, "year": m.year}
                    for m in movies_list
                ],
            }

    # ---- Run ----

    def run(self):
        """Start the MCP server with the configured transport."""
        transport = self.config.server_config.transport
        port = self.config.server_config.port
        host = self.config.server_config.host

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
