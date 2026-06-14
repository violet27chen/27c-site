#!/usr/bin/env python3
"""Gunicorn configuration for 27c.site"""

import multiprocessing

# Server socket
bind = '127.0.0.1:5000'

# Worker processes
workers = min(multiprocessing.cpu_count() * 2 + 1, 4)
worker_class = 'sync'
worker_connections = 1000
timeout = 30
keepalive = 5

# Logging
accesslog = '/var/log/27c-access.log'
errorlog = '/var/log/27c-error.log'
loglevel = 'info'
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = '27c-site'

# Server mechanics
preload_app = True

# Security
limit_request_line = 8190
limit_request_fields = 100
limit_request_field_size = 8190

# SSL (if needed, uncomment and set paths)
# certfile = '/etc/ssl/27c.site/fullchain.pem'
# keyfile = '/etc/ssl/27c.site/privkey.pem'

# Restart workers after this many requests (prevents memory leaks)
max_requests = 1000
max_requests_jitter = 50
