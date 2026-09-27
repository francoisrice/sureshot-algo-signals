"""
Pytest configuration file for handling imports
"""
import sys
import os

# Add the parent directory (SureshotSDK) to Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Tests mock the HTTP session but still run the throttle; real pacing would add 12.5s per call
os.environ.setdefault('POLYGON_MIN_REQUEST_INTERVAL', '0')
