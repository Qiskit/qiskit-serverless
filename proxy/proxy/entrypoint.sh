#!/bin/bash

echo "entrypoint.sh"

#sudo iptables -t nat -N proxy_redirect
#sudo iptables -t nat -A proxy_redirect -p tcp -d 104.18.29.94 -j REDIRECT --to-ports 8443
#sudo iptables -t nat -A proxy_redirect -p tcp -d 104.18.28.94 -j REDIRECT --to-ports 8443

#sudo iptables -t nat -N proxy_output
#sudo iptables -t nat -A proxy_output -p tcp --dport 6379 -j RETURN
#sudo iptables -t nat -A proxy_output -p tcp -m owner --gid-owner 123 -j RETURN
#sudo iptables -t nat -A proxy_output -j proxy_redirect

#sudo iptables -t nat -A OUTPUT -p tcp -j proxy_output

python httpserver.py
