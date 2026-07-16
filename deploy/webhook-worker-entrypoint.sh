#!/bin/sh
set -eu

# Webhook/Notify worker 使用独立队列与出站防火墙（webhooks 与 notify 两个队列
# 的 worker 共用本入口）。先放行运行所需的 DNS/Redis，
# 再拒绝所有特殊地址，业务请求只能访问公网 TCP/443。
iptables -F OUTPUT
iptables -A OUTPUT -o lo -j ACCEPT
iptables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A OUTPUT -p udp --dport 53 -j ACCEPT
iptables -A OUTPUT -p tcp --dport 53 -j ACCEPT

REDIS_ADDRESSES="$(getent ahostsv4 redis | awk '{print $1}' | sort -u)"
if [ -z "${REDIS_ADDRESSES}" ]; then
  echo "无法解析 Redis 地址，拒绝启动 Webhook worker。" >&2
  exit 1
fi
for address in ${REDIS_ADDRESSES}; do
  iptables -A OUTPUT -p tcp -d "${address}" --dport 6379 -j ACCEPT
done

for network in \
  0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 \
  172.16.0.0/12 192.0.0.0/24 192.0.2.0/24 192.168.0.0/16 \
  198.18.0.0/15 198.51.100.0/24 203.0.113.0/24 224.0.0.0/4 240.0.0.0/4; do
  iptables -A OUTPUT -d "${network}" -j REJECT
done
iptables -A OUTPUT -p tcp --dport 443 -j ACCEPT
iptables -P OUTPUT DROP

ip6tables -F OUTPUT
ip6tables -A OUTPUT -o lo -j ACCEPT
ip6tables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
ip6tables -A OUTPUT -p udp --dport 53 -j ACCEPT
ip6tables -A OUTPUT -p tcp --dport 53 -j ACCEPT
for network in ::/128 fc00::/7 fe80::/10 ff00::/8 2001:db8::/32; do
  ip6tables -A OUTPUT -d "${network}" -j REJECT
done
ip6tables -A OUTPUT -p tcp --dport 443 -j ACCEPT
ip6tables -P OUTPUT DROP

exec runuser -u easyauth -- "$@"
