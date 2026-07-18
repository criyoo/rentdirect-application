#!/bin/sh

# Health check script for frontend container
# This script checks if nginx is running and serving content

# Check if nginx is running
if ! pgrep nginx > /dev/null; then
    echo "Nginx is not running"
    exit 1
fi

# Check if the health endpoint responds
if ! wget --quiet --tries=1 --spider http://localhost/health; then
    echo "Health endpoint is not responding"
    exit 1
fi

# Check if the main page is accessible
if ! wget --quiet --tries=1 --spider http://localhost/; then
    echo "Main page is not accessible"
    exit 1
fi

echo "Frontend is healthy"
exit 0