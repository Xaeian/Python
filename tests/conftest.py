# tests/conftest.py

"""With `python_functions = ["*"]`, collect only functions defined in the test module."""

import inspect

def pytest_pycollect_makeitem(collector, name, obj):
  if inspect.isfunction(obj) and obj.__module__ != collector.obj.__name__:
    return [] # ignore library functions imported into the test file
