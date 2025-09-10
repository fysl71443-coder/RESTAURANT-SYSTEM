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
    """Run database migrations safely"""
    try:
        print("[run_migrations] Creating Flask app...")
        from app import create_app
        app = create_app()

        print("[run_migrations] Running migrations within app context...")
        with app.app_context():
            from flask_migrate import upgrade

            # Run upgrade to latest head
            print("[run_migrations] Upgrading to latest migration head...")
            upgrade()

            # Verify migration success
            from flask_migrate import current
            current_rev = current()
            print(f"[run_migrations] Current migration revision: {current_rev}")

            print("[run_migrations] ✅ Migrations completed successfully!")

    except Exception as e:
        print(f"[run_migrations] ❌ Migration failed: {e}")
        print("[run_migrations] Attempting fallback migration method...")

        # Fallback: try direct alembic
        try:
            import subprocess
            result = subprocess.run([
                'python', '-m', 'alembic', '-c', 'alembic.ini', 'upgrade', 'head'
            ], capture_output=True, text=True, timeout=60)

            if result.returncode == 0:
                print("[run_migrations] ✅ Fallback migration successful!")
                return
            else:
                print(f"[run_migrations] Fallback failed: {result.stderr}")
        except Exception as fallback_error:
            print(f"[run_migrations] Fallback error: {fallback_error}")

        print("[run_migrations] ⚠️ Migration failed, but continuing startup...")
        # Don't exit - let the app start even if migrations fail

if __name__ == '__main__':
    run_migrations()
