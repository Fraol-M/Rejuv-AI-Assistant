import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.action_manager.backends import DockerBackend


def main():
    result = DockerBackend().run(
        """
import socket

try:
    print(socket.gethostbyname("example.com"))
except Exception as exc:
    print(type(exc).__name__)
""",
        timeout=15,
    )
    print(result)


if __name__ == "__main__":
    main()
