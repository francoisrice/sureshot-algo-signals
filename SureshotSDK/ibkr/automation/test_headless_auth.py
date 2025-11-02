import pytest
import os
import sys
from unittest.mock import patch

# TODO: Make better tests
#   The tests should match SPECIFIC exceptions. Not any exception.

def test_username_none():
    """Test that an error is raised when username is None"""
    with patch.dict(os.environ, {'IBKR_PASSWORD': 'test', 'IBKR_SECRET': 'test'}, clear=True):
        # Clear the module cache to force reimport
        if 'headless_auth' in sys.modules:
            del sys.modules['headless_auth']

        with pytest.raises(Exception):
            import headless_auth

def test_username_empty_string():
    """Test that an error is raised when username is an empty string"""
    with patch.dict(os.environ, {'IBKR_USERNAME': '', 'IBKR_PASSWORD': 'test', 'IBKR_SECRET': 'test'}, clear=True):
        # Clear the module cache to force reimport
        if 'headless_auth' in sys.modules:
            del sys.modules['headless_auth']

        with pytest.raises(Exception):
            import headless_auth

def test_password_none():
    """Test that an error is raised when password is None"""
    with patch.dict(os.environ, {'IBKR_USERNAME': 'test', 'IBKR_SECRET': 'test'}, clear=True):
        # Clear the module cache to force reimport
        if 'headless_auth' in sys.modules:
            del sys.modules['headless_auth']

        with pytest.raises(Exception):
            import headless_auth

def test_password_empty_string():
    """Test that an error is raised when password is an empty string"""
    with patch.dict(os.environ, {'IBKR_USERNAME': 'test', 'IBKR_PASSWORD': '', 'IBKR_SECRET': 'test'}, clear=True):
        # Clear the module cache to force reimport
        if 'headless_auth' in sys.modules:
            del sys.modules['headless_auth']

        with pytest.raises(Exception):
            import headless_auth

def test_secret_none():
    """Test that an error is raised when secret is None"""
    with patch.dict(os.environ, {'IBKR_USERNAME': 'test', 'IBKR_PASSWORD': 'test'}, clear=True):
        # Clear the module cache to force reimport
        if 'headless_auth' in sys.modules:
            del sys.modules['headless_auth']

        with pytest.raises(Exception):
            import headless_auth

def test_secret_empty_string():
    """Test that an error is raised when secret is an empty string"""
    with patch.dict(os.environ, {'IBKR_USERNAME': 'test', 'IBKR_PASSWORD': 'test', 'IBKR_SECRET': ''}, clear=True):
        # Clear the module cache to force reimport
        if 'headless_auth' in sys.modules:
            del sys.modules['headless_auth']

        with pytest.raises(Exception):
            import headless_auth
