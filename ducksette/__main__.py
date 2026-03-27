"""CLI entry point for Ducksette."""
import argparse
import logging
import sys

import uvicorn

from ducksette.config import load_config
from ducksette.engine import QueryEngine
from ducksette.errors import ConfigError
from ducksette.server import create_app

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ducksette — DuckDB data browser")
    parser.add_argument("--config", required=True, help="Path to config file (YAML or JSON)")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on (default: 8000)")
    args = parser.parse_args()

    # Load and validate config
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)

    # Initialize query engine
    engine = QueryEngine(config)
    succeeded = engine.initialize()

    if config.sources and not succeeded:
        print("Error: all data sources failed to mount. Exiting.", file=sys.stderr)
        sys.exit(1)

    logger.info("Successfully mounted data sources: %s", succeeded or ["(none)"])

    # Start server
    app = create_app(engine)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
