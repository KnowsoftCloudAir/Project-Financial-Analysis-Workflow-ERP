"""WSGI entry for Gunicorn / Railway.
Loads Flask app from server.py.
"""
from server import app

# Gunicorn may use wsgi:app or wsgi:application
try:
    from server import application  # noqa: F401
except ImportError:
    application = app

__all__ = ["app", "application"]
