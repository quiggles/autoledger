"""
version.py
----------
Single source of truth for the application version.

Kept in its own tiny module (rather than in ``app.py``) so any layer — the
health endpoint, the JSON export envelope, the reminders scheduler — can import
the version without importing the Flask app and risking a circular import.

Update this one constant on every release, then follow the Version Bump
Checklist in HANDOVER.md for the frontend/changelog touch-points.
"""

__version__ = "2.1.0"
