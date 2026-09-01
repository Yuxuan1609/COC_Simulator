from module_designer.lint import run_lint
import sys

sys.exit(run_lint(sys.argv[1] if len(sys.argv) > 1 else "."))
