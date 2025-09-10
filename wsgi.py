#!/usr/bin/env python3
"""
Safe WSGI entry point that falls back to simple app if main app fails
"""
import os
import sys

# Force disable eventlet
os.environ['USE_EVENTLET'] = '0'
os.environ['DISABLE_SOCKETIO'] = '1'

# Block problematic imports
class ImportBlocker:
    def find_spec(self, name, path, target=None):
        if name.startswith('eventlet') or name.startswith('flask_socketio'):
            raise ImportError(f"Blocked for stability: {name}")
        return None

sys.meta_path.insert(0, ImportBlocker())

try:
    # Try to import the main app safely
    print("[wsgi] Attempting to import main app...")
    from app import app
    application = app
    print("[wsgi] Successfully loaded main app")
except Exception as e:
    print(f"[wsgi] Main app import failed: {e}")
    print("[wsgi] Falling back to simple app...")

    # Fallback to simple app
    from wsgi_simple import application
    print("[wsgi] Successfully loaded simple app fallback")
