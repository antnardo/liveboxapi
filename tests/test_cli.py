"""The command: mostly, that reading commands cannot write."""

import pytest

from liveboxapi import cli


class TestSafetyByDefault:
    @pytest.mark.parametrize(
        "command", ["health", "devices", "leases", "nat", "firewall", "wifi", "calls", "blocked"]
    )
    def test_reading_commands_open_a_read_only_session(self, command):
        """A typo in a read command must not be able to reconfigure anything."""
        assert command not in cli._WRITE_COMMANDS

    @pytest.mark.parametrize("command", ["reserve", "unreserve", "block", "unblock", "call"])
    def test_writing_commands_are_declared(self, command):
        assert command in cli._WRITE_COMMANDS


class TestParser:
    def test_a_command_is_required(self):
        with pytest.raises(SystemExit):
            cli.build_parser().parse_args([])

    def test_reserve_takes_an_address_and_an_ip(self):
        args = cli.build_parser().parse_args(["reserve", "aa:bb:cc:dd:ee:ff", "192.168.1.5"])
        assert (args.mac, args.ip) == ("aa:bb:cc:dd:ee:ff", "192.168.1.5")

    def test_functions_accepts_a_writes_flag(self):
        args = cli.build_parser().parse_args(["functions", "Firewall", "--writes"])
        assert args.writes and args.path == "Firewall"

    def test_the_box_address_can_be_overridden(self):
        args = cli.build_parser().parse_args(["--url", "http://other/", "health"])
        assert args.url == "http://other/"

    def test_every_command_has_a_handler(self):
        parser = cli.build_parser()
        for command in ["health", "devices", "leases", "nat", "firewall", "wifi", "blocked"]:
            assert hasattr(parser.parse_args([command]), "handler")
