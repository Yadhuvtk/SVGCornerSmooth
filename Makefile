run-dev:
	python api_server.py

run-prod:
	gunicorn backend.wsgi:app --workers 2 --timeout 120 --bind 127.0.0.1:5050 --log-level info
