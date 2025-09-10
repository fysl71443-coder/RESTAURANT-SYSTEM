#!/usr/bin/env python3
"""
Merge multiple Alembic heads into a single head
"""
import os
import sys

# Disable eventlet for CLI operations
os.environ['USE_EVENTLET'] = '0'
os.environ['DISABLE_SOCKETIO'] = '1'

def merge_heads():
    """Merge all heads into a single head"""
    try:
        print("[merge_heads] Setting up Flask app context...")
        from app import create_app
        app = create_app()
        
        print("[merge_heads] Merging heads within app context...")
        with app.app_context():
            from flask_migrate import merge

            # The heads we found
            heads = ['097c20248414', '20250909_03', '4539af27efad', '9fd032f321c7']

            print(f"[merge_heads] Merging heads: {heads}")
            # Flask-Migrate merge syntax: merge(revisions, message)
            merge(revisions=heads, message="merge all migration heads")
            print("[merge_heads] ✅ Heads merged successfully!")
            
    except Exception as e:
        print(f"[merge_heads] ❌ Merge failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    merge_heads()
