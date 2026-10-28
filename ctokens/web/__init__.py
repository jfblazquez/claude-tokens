"""Local web server: JSON API and browser UI over the same core functions as the CLI."""
from __future__ import annotations

import errno
import secrets
import sys

from .server import HOST, Config, Server

__all__ = ["Config", "serve"]


def serve(config, port):
    """Run in the foreground until Ctrl+C; returns the process exit status."""
    if config.send_key is None:
        config = config._replace(send_key=secrets.token_urlsafe(18))
    try:
        server = Server(config, port)
    except OSError as error:
        if error.errno == errno.EADDRINUSE:
            print(f"error: port {port} is already in use", file=sys.stderr)
        else:
            print(f"error: cannot listen on port {port}: {error.strerror or error}", file=sys.stderr)
        return 1
    print(f"Serving on http://{HOST}:{port}  (Ctrl+C to stop)\n"
          f"  projects dir: {config.projects_dir}\n"
          f"  from your machine: ssh -tt -L {port}:localhost:{port} <this-host> 'exec sleep infinity' </dev/null\n"
          f"  to send messages to running sessions, open once: http://localhost:{port}/?key={config.send_key}",
          flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
