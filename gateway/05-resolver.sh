#!/bin/sh
# Use whatever DNS server the container was given (127.0.0.11 in Docker, kube-dns in Kubernetes),
# so nginx can start even if a backend is not up yet and re-resolves names at run time.
ns=$(awk '/^nameserver/ {print $2; exit}' /etc/resolv.conf)
echo "resolver ${ns} valid=10s ipv6=off;" > /etc/nginx/resolver.conf
