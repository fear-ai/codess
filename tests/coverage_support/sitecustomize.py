"""Start coverage in a child process launched by the test suite.

Python imports `sitecustomize` during interpreter start-up if it is importable,
which is early enough to measure the child's own imports. `process_startup()`
is a no-op unless `COVERAGE_PROCESS_START` names a configuration file, so this
module is inert outside a coverage run.

This directory is placed on `PYTHONPATH` by `tests/conftest.py`. It exists
because the alternative -- a `.pth` file -- has to be written into
site-packages, which a checkout must not do to the machine it runs on.
"""

try:
    import coverage
except ImportError:  # coverage is an optional development dependency
    pass
else:
    coverage.process_startup()
