"""Command-line interface for the Radarr/Sonarr MCP server."""

import argparse
import logging

from .config import Config, NasConfig, RadarrConfig, SonarrConfig, ServerConfig, load_config, save_config
from .server import create_server

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def _ask(prompt: str, default: str = "") -> str:
    """Prompt user for input with a default value."""
    value = input(f"{prompt} [{default}]: ")
    return value or default


def _ask_sonarr_instance(name: str, existing: SonarrConfig = None) -> SonarrConfig:
    """Prompt user for a single Sonarr instance configuration."""
    logging.info(f"  -- {name} --")
    api_key = _ask(f"  {name} API key", existing.api_key if existing else "")
    if not api_key:
        logging.warning(f"  Warning: {name} API key is empty, this instance will be skipped.")
    port = _ask(f"  {name} port", existing.port if existing else "8989")
    base_path = _ask(f"  {name} API base path", existing.base_path if existing else "/api/v3")
    return SonarrConfig(name=name, api_key=api_key, base_path=base_path, port=port)


def configure():
    """Run the configuration wizard."""
    logging.info("==== Radarr/Sonarr MCP Server Configuration Wizard ====")

    config = None
    try:
        config = load_config()
        logging.info("Loaded existing configuration. Press Enter to keep current values.")
    except Exception:
        pass

    # NAS configuration
    nas_ip = _ask("NAS/Server IP address", config.nas_config.ip if config else "10.0.0.23")
    nas_port = _ask("Default port", config.nas_config.port if config else "7878")

    # Radarr configuration
    logging.info("---- Radarr ----")
    radarr_api_key = _ask("Radarr API key", config.radarr_config.api_key if config else "")
    if not radarr_api_key:
        logging.warning("Warning: Radarr API key is required for movie functionality!")
    radarr_port = _ask("Radarr port", config.radarr_config.port if config else "7878")
    radarr_base_path = _ask("Radarr API base path", config.radarr_config.base_path if config else "/api/v3")

    # Sonarr instances
    logging.info("---- Sonarr instances ----")
    sonarr_configs = {}

    existing_sonarr = config.sonarr_configs.get("sonarr") if config else None
    sonarr_main = _ask_sonarr_instance("sonarr", existing_sonarr)
    if sonarr_main.api_key:
        sonarr_configs["sonarr"] = sonarr_main

    add_anime = _ask("Add a Sonarr Anime instance? (y/n)", "y" if (config and "sonarr_anime" in config.sonarr_configs) else "n")
    if add_anime.lower() in ("y", "yes"):
        existing_anime = config.sonarr_configs.get("sonarr_anime") if config else None
        sonarr_anime = _ask_sonarr_instance("sonarr_anime", existing_anime)
        if sonarr_anime.api_key:
            sonarr_configs["sonarr_anime"] = sonarr_anime

    if not sonarr_configs:
        sonarr_configs["sonarr"] = SonarrConfig(name="sonarr")

    # Server configuration
    logging.info("---- MCP Server ----")
    server_port_str = _ask("MCP server port", str(config.server_config.port if config else 3000))
    try:
        server_port = int(server_port_str)
    except ValueError:
        logging.warning("Invalid port number, using default.")
        server_port = config.server_config.port if config else 3000

    new_config = Config(
        nas_config=NasConfig(ip=nas_ip, port=nas_port),
        radarr_config=RadarrConfig(api_key=radarr_api_key, base_path=radarr_base_path, port=radarr_port),
        sonarr_configs=sonarr_configs,
        server_config=ServerConfig(port=server_port),
    )

    save_config(new_config)
    logging.info("Configuration saved successfully!")
    logging.info("To start the server, run: radarr-sonarr-mcp start")

    return new_config


def show_status():
    """Show the current status of the server."""
    try:
        config = load_config()
        logging.info("==== Radarr/Sonarr MCP Server Status ====")
        logging.info(f"NAS IP: {config.nas_config.ip}")
        logging.info(f"Radarr Port: {config.radarr_config.port}")
        for name, sc in config.sonarr_configs.items():
            logging.info(f"Sonarr '{name}' Port: {sc.port}")
        logging.info(f"MCP Server Port: {config.server_config.port}")
        logging.info(f"MCP Endpoint URL: http://localhost:{config.server_config.port}")
        logging.info("Server is configured. Use 'radarr-sonarr-mcp start' to run the server.")
    except Exception as e:
        logging.error(f"Server is not configured: {e}")
        logging.info("Run 'radarr-sonarr-mcp configure' to set up the server.")


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="Radarr/Sonarr MCP Server")
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    subparsers.add_parser("configure", help="Configure the MCP server")

    start_parser = subparsers.add_parser("start", help="Start the MCP server")
    start_parser.add_argument("--config", help="Path to config.json file")
    start_parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        help="Transport mode (overrides config)",
    )
    start_parser.add_argument("--port", type=int, help="Port for HTTP transport (overrides config)")

    subparsers.add_parser("status", help="Show the server status")

    args = parser.parse_args()

    if args.command == "configure":
        configure()
    elif args.command == "start":
        server = create_server(args.config)
        if args.transport:
            server.config.server_config.transport = args.transport
        if args.port:
            server.config.server_config.port = args.port
        server.run()
    elif args.command == "status":
        show_status()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
