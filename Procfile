web: python run_migrations.py && gunicorn --worker-class sync --workers 1 -b 0.0.0.0:$PORT wsgi:application
