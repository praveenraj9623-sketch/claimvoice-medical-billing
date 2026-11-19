import unittest
from ipaddress import ip_network
from pathlib import Path
from tempfile import TemporaryDirectory

from lab.sip.network import render, select_subnet


class SipSubnetTests(unittest.TestCase):
    def test_voxops_supernet_is_excluded(self):
        subnet = select_subnet(["172.29.0.0/16", "fd00::/64", ""])
        self.assertEqual(subnet, ip_network("172.30.231.0/24"))
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.assertEqual(render(subnet, directory), "172.30.231")
            self.assertIn('node_ip: "172.30.231.10"', (directory / "server.yaml").read_text())
            self.assertIn("match=172.30.231.11/32", (directory / "pjsip.conf").read_text())

    def test_smaller_occupied_subnet(self):
        occupied = ["172.29.0.0/16", "172.30.231.128/25"]
        subnet = select_subnet(occupied)
        self.assertFalse(any(subnet.overlaps(ip_network(item)) for item in occupied))

    def test_preferred_pool_is_available(self):
        self.assertEqual(select_subnet([]), ip_network("172.29.231.0/24"))

    def test_exhaustion(self):
        with self.assertRaisesRegex(ValueError, "No free"):
            select_subnet(["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"])
