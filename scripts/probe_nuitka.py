import sys, os
from pathlib import Path

print("frozen:", getattr(sys, 'frozen', 'NOT FOUND'))
print("_MEIPASS:", getattr(sys, '_MEIPASS', 'NOT FOUND'))
print("executable:", sys.executable)
print("argv[0]:", sys.argv[0])
print("exe dir:", os.path.dirname(sys.executable))

# Check __compiled__
try:
    import __compiled__
    print("__compiled__:", __compiled__)
except ImportError:
    print("__compiled__: NOT FOUND")

# Check for __nuitka__
print("__nuitka_binary_dir:", getattr(sys, '__nuitka_binary_dir', 'NOT FOUND'))
