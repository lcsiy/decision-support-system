"""
pytest fixtures for DSS tests.
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Ensure dss package is importable
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load real .env FIRST so real credentials win; dummy values only as fallback
# (load_dotenv default override=False — a placeholder set before loading .env
# would permanently shadow the real TUSHARE_TOKEN).
_env_path = project_root / '.env'
if _env_path.exists():
    load_dotenv(dotenv_path=_env_path)
os.environ.setdefault('TUSHARE_TOKEN', 'test_token_placeholder')
os.environ.setdefault('LOG_LEVEL', 'WARNING')
