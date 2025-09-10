#!/usr/bin/env python3
"""
Simple WSGI entry point without SocketIO for production stability
"""
import os
import sys

# Force disable eventlet and SocketIO
os.environ['USE_EVENTLET'] = '0'
os.environ['DISABLE_SOCKETIO'] = '1'

# Block eventlet imports completely
class EventletBlocker:
    def find_spec(self, name, path, target=None):
        if name.startswith('eventlet') or name.startswith('flask_socketio'):
            raise ImportError(f"Blocked for stability: {name}")
        return None

sys.meta_path.insert(0, EventletBlocker())

# Import Flask and create minimal app
from flask import Flask, jsonify
from extensions import db, bcrypt, migrate, login_manager, babel, csrf

def create_simple_app():
    """Create a simple Flask app without SocketIO"""
    app = Flask(__name__)

    # Load configuration
    from config import Config
    app.config.from_object(Config)

    # Initialize extensions
    db.init_app(app)
    bcrypt.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    babel.init_app(app)
    csrf.init_app(app)

    # Configure login manager
    login_manager.login_view = 'login'

    @login_manager.user_loader
    def load_user(user_id):
        try:
            from models import User
            return db.session.get(User, int(user_id))
        except Exception:
            return None

    # Add essential routes
    @app.route('/health')
    def health():
        return jsonify({'status': 'ok', 'message': 'App is running (simple mode)'})

    @app.route('/test-dependencies')
    def test_dependencies():
        results = {}

        # Test pandas
        try:
            import pandas as pd
            results['pandas'] = {'status': 'OK', 'version': pd.__version__}
        except ImportError as e:
            results['pandas'] = {'status': 'MISSING', 'error': str(e)}
        except Exception as e:
            results['pandas'] = {'status': 'ERROR', 'error': str(e)}

        # Test openpyxl
        try:
            import openpyxl
            results['openpyxl'] = {'status': 'OK', 'version': openpyxl.__version__}
        except ImportError as e:
            results['openpyxl'] = {'status': 'MISSING', 'error': str(e)}
        except Exception as e:
            results['openpyxl'] = {'status': 'ERROR', 'error': str(e)}

        # Test Flask-Babel
        try:
            from flask_babel import gettext as _
            test_msg = _('Test message')
            results['flask_babel'] = {'status': 'OK', 'test': test_msg}
        except ImportError as e:
            results['flask_babel'] = {'status': 'MISSING', 'error': str(e)}
        except Exception as e:
            results['flask_babel'] = {'status': 'ERROR', 'error': str(e)}

        return jsonify(results)

    return app

# Create the application
application = create_simple_app()

if __name__ == "__main__":
    application.run(host='0.0.0.0', port=int(os.getenv('PORT', 8000)))
