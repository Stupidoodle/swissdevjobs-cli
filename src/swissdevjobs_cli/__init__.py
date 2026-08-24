__version__ = "0.2.0"

# Load .env before api/db read the environment at import time.
from . import dotenv as _dotenv

_dotenv.load()
