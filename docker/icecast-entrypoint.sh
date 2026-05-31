#!/bin/sh
set -eu

: "${ICECAST_SOURCE_PASSWORD:?ICECAST_SOURCE_PASSWORD is required}"
: "${ICECAST_ADMIN_PASSWORD:?ICECAST_ADMIN_PASSWORD is required}"

export ICECAST_HOSTNAME="${ICECAST_HOSTNAME:-localhost}"
export ICECAST_LOCATION="${ICECAST_LOCATION:-OMV}"
export ICECAST_ADMIN_EMAIL="${ICECAST_ADMIN_EMAIL:-admin@example.local}"
export ICECAST_SOURCE_USER="${ICECAST_SOURCE_USER:-source}"
export ICECAST_RELAY_PASSWORD="${ICECAST_RELAY_PASSWORD:-change-me-relay-password}"
export ICECAST_ADMIN_USER="${ICECAST_ADMIN_USER:-admin}"

envsubst < /etc/icecast2/icecast.xml.template > /etc/icecast2/icecast.xml

mkdir -p /var/log/icecast2
touch /var/log/icecast2/access.log /var/log/icecast2/error.log
chown -R icecast2:icecast /var/log/icecast2

tail -n 0 -F /var/log/icecast2/error.log /var/log/icecast2/access.log &

exec icecast2 -c /etc/icecast2/icecast.xml
