#!/bin/bash

echo "entrypoint.sh"

iptables -t nat -N proxy_redirect
iptables -t nat -A proxy_redirect -p tcp -d 104.18.29.94 -j REDIRECT --to-ports 8443
iptables -t nat -A proxy_redirect -p tcp -d 104.18.28.94 -j REDIRECT --to-ports 8443

iptables -t nat -N proxy_output
iptables -t nat -A proxy_output -p tcp --dport 6379 -j RETURN
iptables -t nat -A proxy_output -p tcp -m owner --gid-owner 123 -j RETURN
iptables -t nat -A proxy_output -j proxy_redirect

# iptables -t nat -A OUTPUT -p tcp -j proxy_output

python httpserver.py

