import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.action_manager.backends import DockerBackend


def main():
    result = DockerBackend().run(
        """
from pathlib import Path
import os
import socket

print(f"uid={os.getuid()}")
print(f"user_home_writable={os.access('/home/user', os.W_OK)}")
try:
    Path('/root/should_not_write').write_text('nope')
    print("root_write=unexpected_success")
except Exception as exc:
    print(f"root_write={type(exc).__name__}")

try:
    print(f"dns={socket.gethostbyname('example.com')}")
except Exception as exc:
    print(f"dns={type(exc).__name__}")
""",
        timeout=15,
    )
    print(result)


if __name__ == "__main__":
    main()
