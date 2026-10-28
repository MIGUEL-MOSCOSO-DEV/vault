import os
from pathlib import Path


def data_dir():
    root = Path(os.environ.get("VAULT_HOME", Path.home() / ".vault"))
    root.mkdir(parents=True, exist_ok=True)
    return root
