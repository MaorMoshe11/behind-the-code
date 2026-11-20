"""The container's health check: exit 0 when the service is ready, 1 when it is not.

Docker runs it inside the container, every few seconds (HEALTHCHECK in the Dockerfile).
"""

import sys
import urllib.error
import urllib.request

READY_URL = "http://127.0.0.1:8000/ready"


def main() -> None:
    try:
        # A health check that hangs is worse than one that fails: always a timeout.
        with urllib.request.urlopen(READY_URL, timeout=3) as response:
            print(f"ready ({response.status})")
    except urllib.error.HTTPError as error:  # the service answered: 503, not ready
        sys.exit(f"not ready ({error.code})")
    except OSError as error:  # no answer at all: the process is down or stuck
        sys.exit(f"no answer: {error}")


if __name__ == "__main__":
    main()
