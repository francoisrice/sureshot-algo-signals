"""
Pytest configuration file for handling imports
"""
import sys
import os

# Add the parent directory (SureshotSDK) to Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
