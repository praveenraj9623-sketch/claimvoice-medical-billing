"""Inspect the installed CTranslate2 wheel without importing the failing native module."""
from importlib import metadata
import platform
import shutil
import subprocess
import sys


def main():
    print(f"Python: {sys.executable}\nPlatform: {platform.platform()}\nLibc: {platform.libc_ver()}", flush=True)
    dist = metadata.distribution("ctranslate2")
    print(f"CTranslate2: {dist.version}", flush=True)
    for entry in dist.files or ():
        if entry.name.startswith("libctranslate2") and ".so" in entry.name:
            library = dist.locate_file(entry)
            print(f"{library} exists={library.is_file()}", flush=True)
            if library.is_file() and shutil.which("ldd"):
                subprocess.run(["ldd", str(library)], check=False)


if __name__ == "__main__":
    main()
