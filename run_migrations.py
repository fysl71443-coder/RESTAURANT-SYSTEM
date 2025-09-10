#!/usr/bin/env python3
"""
Run database migrations safely within Flask app context
"""
import os
import sys

# Disable eventlet for CLI operations
os.environ['USE_EVENTLET'] = '0'
os.environ['DISABLE_SOCKETIO'] = '1'

def run_migrations():
    """Run Flask-Migrate upgrade within app context"""
    try:
        print("[run_migrations] Creating Flask app...")
        from app import create_app
        app = create_app()
        
        print("[run_migrations] Running migrations within app context...")
        with app.app_context():
            from flask_migrate import upgrade
            upgrade()
            print("[run_migrations] ✅ Migrations completed successfully!")
            
    except Exception as e:
        print(f"[run_migrations] ❌ Migration failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    run_migrations()
