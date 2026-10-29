"""
Standalone test runner for CredResolve SmartDialer.
Can be executed with: `python backend/run_tests.py` or `pytest backend/tests`.
"""
import sys
import pytest

if __name__ == "__main__":
    print("Running CredResolve SmartDialer Test Suite...")
    exit_code = pytest.main(["-v", "backend/tests"])
    sys.exit(exit_code)
