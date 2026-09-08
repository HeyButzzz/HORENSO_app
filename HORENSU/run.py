import os
import socket

from app import create_app

app = create_app()

# The address the app binds to. Start.bat may override these when the fixed
# lab IP is not present on this machine (docked elsewhere, Wi-Fi off, ...).
DEFAULT_HOST = "10.10.20.19"
DEFAULT_PORT = 8080


def _resolve_host(preferred):
    """Fall back to every interface when the preferred address is not local.

    Binding to an address the machine does not hold fails outright with
    "Cannot assign requested address", which reads as a crash to anyone who
    just double-clicked Start.bat.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((preferred, 0))
        return preferred
    except OSError:
        print(f"  ! {preferred} tidak tersedia di komputer ini — memakai 0.0.0.0 (semua interface).")
        return "0.0.0.0"
    finally:
        probe.close()


if __name__ == "__main__":
    host = os.environ.get("HORENSO_HOST", DEFAULT_HOST)
    port = int(os.environ.get("HORENSO_PORT", DEFAULT_PORT))

    # debug/reloader is off by default: it's a dev convenience but the
    # auto-reloader can be flaky depending on the OS/network setup.
    # Set HORENSO_DEBUG=1 if you want auto-reload while editing code.
    debug = os.environ.get("HORENSO_DEBUG", os.environ.get("HORENSU_DEBUG")) == "1"

    app.run(debug=debug, host=_resolve_host(host), port=port)
