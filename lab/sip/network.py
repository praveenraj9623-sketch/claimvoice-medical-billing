"""Select a lab /24 and render the two files that Compose bind-mounts."""
import sys
from ipaddress import IPv4Network, ip_network
from pathlib import Path


def select_subnet(subnets):
    occupied = [ip_network(line.strip(), strict=False) for line in subnets if line.strip()]
    pools = ("172.29.231.0/24", "172.30.231.0/24", "172.16.0.0/12", "10.0.0.0/8", "192.168.0.0/16")
    for pool in pools:
        for candidate in IPv4Network(pool).subnets(new_prefix=24):
            if all(existing.version != 4 or not candidate.overlaps(existing) for existing in occupied):
                return candidate
    raise ValueError("No free private IPv4 /24 on this Docker engine")


def render(subnet, directory):
    prefix = str(subnet.network_address).rsplit(".", 1)[0]
    for name in ("server.yaml", "pjsip.conf"):
        template = Path(__file__).with_name(name).read_text(encoding="utf-8")
        (directory / name).write_text(template.replace("@PREFIX@", prefix), encoding="utf-8")
    return prefix


if __name__ == "__main__":
    print(render(select_subnet(sys.stdin), Path(sys.argv[1])))
