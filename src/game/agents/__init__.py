"""Multi-agent game loop agents."""
from .author import Author

try:
    from .narrator import Narrator
except ImportError:
    Narrator = None  # created in a later task

try:
    from .keeper import Keeper
except ImportError:
    Keeper = None  # created in a later task
