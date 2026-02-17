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

# Tool name mapping: instance name -> (get, lookup, label, quality_profiles, root_folders, add)
SONARR_TOOL_NAMES = {
    "sonarr": (
        "get_available_series", "lookup_series", "series",
        "get_sonarr_quality_profiles", "get_sonarr_root_folders", "add_series_to_sonarr",
    ),
    "sonarr_anime": (
        "get_available_anime", "lookup_anime", "anime",
        "get_anime_quality_profiles", "get_anime_root_folders", "add_anime_to_sonarr",
    ),
}


def _sonarr_tool_names(instance_name: str) -> tuple:
    """Get tool names for a Sonarr instance. Falls back to generic naming."""
    if instance_name in SONARR_TOOL_NAMES:
        return SONARR_TOOL_NAMES[instance_name]
    safe = instance_name.replace("-", "_")
    return (
        f"get_available_{safe}", f"lookup_{safe}", safe,
        f"get_{safe}_quality_profiles", f"get_{safe}_root_folders", f"add_{safe}",
    )


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
        get_name, lookup_name, label, quality_profiles_name, root_folders_name, add_name = _sonarr_tool_names(instance_name)
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
                        {
                            "id": s.id,
                            "tvdb_id": s.tvdb_id,
                            "title": s.title,
                            "year": s.year,
                            "overview": s.overview,
                        }
                        for s in results
                    ],
                })
            return lookup

        def _make_quality_profiles(svc):
            def get_quality_profiles() -> str:
                """List available quality profiles."""
                profiles = svc.get_quality_profiles()
                return json.dumps({
                    "profiles": [{"id": p["id"], "name": p["name"]} for p in profiles],
                })
            return get_quality_profiles

        def _make_root_folders(svc):
            def get_root_folders() -> str:
                """List available root folders."""
                folders = svc.get_root_folders()
                return json.dumps({
                    "folders": [
                        {"id": f["id"], "path": f["path"], "freeSpace": f.get("freeSpace", 0)}
                        for f in folders
                    ],
                })
            return get_root_folders

        def _make_add_series(svc, lbl):
            def add_series(
                tvdb_id: int,
                quality_profile_id: int,
                root_folder_path: str,
                monitor: str = "all",
                season_folder: bool = True,
                search_for_missing_episodes: bool = False,
                search_for_cutoff_unmet_episodes: bool = False,
                series_type: str = "standard",
            ) -> str:
                f"""Add a {lbl} to Sonarr by TVDB ID."""
                result = svc.add_series(
                    tvdb_id=tvdb_id,
                    quality_profile_id=quality_profile_id,
                    root_folder_path=root_folder_path,
                    monitor=monitor,
                    season_folder=season_folder,
                    search_for_missing_episodes=search_for_missing_episodes,
                    search_for_cutoff_unmet_episodes=search_for_cutoff_unmet_episodes,
                    series_type=series_type,
                )
                return json.dumps(result)
            return add_series

        self.server.tool(name=get_name)(_make_get_available(service, label))
        self.server.tool(name=lookup_name)(_make_lookup(service, label))
        self.server.tool(name=quality_profiles_name)(_make_quality_profiles(service))
        self.server.tool(name=root_folders_name)(_make_root_folders(service))
        self.server.tool(name=add_name)(_make_add_series(service, label))

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

        @self.server.tool()
        def get_radarr_quality_profiles() -> str:
            """List available quality profiles in Radarr."""
            profiles = radarr_service.get_quality_profiles()
            return json.dumps({
                "profiles": [{"id": p["id"], "name": p["name"]} for p in profiles],
            })

        @self.server.tool()
        def get_radarr_root_folders() -> str:
            """List available root folders in Radarr."""
            folders = radarr_service.get_root_folders()
            return json.dumps({
                "folders": [
                    {"id": f["id"], "path": f["path"], "freeSpace": f.get("freeSpace", 0)}
                    for f in folders
                ],
            })

        @self.server.tool()
        def lookup_movie(term: str) -> str:
            """Look up movies by search term in the TMDB catalogue."""
            results = radarr_service.lookup_movie(term)
            return json.dumps({
                "count": len(results),
                "movies": [
                    {
                        "id": m.id,
                        "tmdb_id": m.tmdb_id,
                        "title": m.title,
                        "year": m.year,
                        "overview": m.overview,
                    }
                    for m in results
                ],
            })

        @self.server.tool()
        def add_movie_to_radarr(
            tmdb_id: int,
            quality_profile_id: int,
            root_folder_path: str,
            monitored: bool = True,
            search_for_movie: bool = False,
            minimum_availability: str = "announced",
        ) -> str:
            """Add a movie to Radarr by TMDB ID."""
            result = radarr_service.add_movie(
                tmdb_id=tmdb_id,
                quality_profile_id=quality_profile_id,
                root_folder_path=root_folder_path,
                monitored=monitored,
                search_for_movie=search_for_movie,
                minimum_availability=minimum_availability,
            )
            return json.dumps(result)

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
