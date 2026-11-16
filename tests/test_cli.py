"""Tests for the command-line interface."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from helpers import (
    FIXTURE_DIR,
    FIXTURE_INVENTORY,
    lldp_block,
    run_cli,
    write_topology,
)

COMMANDS = ["parse", "build", "check", "stats", "export", "version"]


def clean_topology_files() -> dict[str, str]:
    return {
        "a.txt": lldp_block("GigabitEthernet1/0/1", "b", "GigabitEthernet1/0/1", mgmt_ip="192.0.2.2"),
        "b.txt": lldp_block("GigabitEthernet1/0/1", "a", "GigabitEthernet1/0/1", mgmt_ip="192.0.2.1"),
    }


class HelpAndVersionTests(unittest.TestCase):
    def test_top_level_help(self) -> None:
        code, output, _ = run_cli(["--help"])
        self.assertEqual(code, 0)
        self.assertIn("usage: topomapper", output)
        for command in COMMANDS:
            self.assertIn(command, output)

    def test_no_command_is_usage_error(self) -> None:
        code, output, _ = run_cli([])
        self.assertEqual(code, 2)
        self.assertIn("usage: topomapper", output)

    def test_version_flag(self) -> None:
        code, output, _ = run_cli(["--version"])
        self.assertEqual(code, 0)
        self.assertIn("topomapper 1.0.0", output)

    def test_version_subcommand(self) -> None:
        code, output, _ = run_cli(["version"])
        self.assertEqual(code, 0)
        self.assertEqual(output.strip(), "topomapper 1.0.0")

    def test_every_subcommand_supports_help(self) -> None:
        for command in COMMANDS:
            with self.subTest(command=command):
                code, output, _ = run_cli([command, "--help"])
                self.assertEqual(code, 0)
                self.assertIn(f"usage: topomapper {command}", output)

    def test_unknown_command_is_usage_error(self) -> None:
        code, _, stderr = run_cli(["poll"])
        self.assertEqual(code, 2)
        self.assertIn("invalid choice", stderr)


class ParseCommandTests(unittest.TestCase):
    def test_human_output(self) -> None:
        code, output, _ = run_cli(["parse", "--dir", FIXTURE_DIR])
        self.assertEqual(code, 0)
        self.assertIn("13 neighbor records (8 LLDP, 5 CDP) from 4 device dumps", output)
        self.assertIn("core-sw", output)

    def test_json_output(self) -> None:
        code, output, _ = run_cli(["parse", "--dir", FIXTURE_DIR, "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(payload["counts"], {"total": 13, "lldp": 8, "cdp": 5})
        self.assertEqual(len(payload["neighbors"]), 13)
        self.assertEqual(payload["devices"], ["core-sw", "edge-rtr", "floor1-sw", "floor2-sw"])

    def test_name_override_requires_single_dump(self) -> None:
        code, _, stderr = run_cli(["parse", "--dir", FIXTURE_DIR, "--name", "custom"])
        self.assertEqual(code, 1)
        self.assertIn("--name can only be used with a single device dump", stderr)

    def test_name_override_with_single_dump(self) -> None:
        files = {"only.txt": lldp_block("Gi0/1", "peer", "Gi0/2")}
        with write_topology(files) as temp_dir:
            code, output, _ = run_cli(
                ["parse", "--dir", temp_dir, "--name", "renamed", "--json"]
            )
        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(payload["devices"], ["renamed"])
        self.assertEqual(payload["neighbors"][0]["local_device"], "renamed")


class BuildCommandTests(unittest.TestCase):
    def test_build_writes_graph_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir, "graph.json")
            code, output, _ = run_cli(
                [
                    "build",
                    "--dir",
                    FIXTURE_DIR,
                    "--inventory",
                    FIXTURE_INVENTORY,
                    "--out",
                    str(target),
                ]
            )
            self.assertEqual(code, 0)
            self.assertIn("Wrote graph JSON", output)
            document = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(document["summary"]["devices"], 5)
        self.assertEqual(len(document["findings"]), 4)

    def test_build_requires_out(self) -> None:
        code, _, _ = run_cli(["build", "--dir", FIXTURE_DIR])
        self.assertEqual(code, 2)


class CheckCommandTests(unittest.TestCase):
    def test_fixture_check_fails_with_error_findings(self) -> None:
        code, output, _ = run_cli(
            ["check", "--dir", FIXTURE_DIR, "--inventory", FIXTURE_INVENTORY]
        )
        self.assertEqual(code, 1)
        self.assertIn("TOPO-CYCLE", output)
        self.assertIn("TOPO-SPOF", output)
        self.assertIn("Result: FAILED", output)

    def test_fixture_check_json(self) -> None:
        code, output, _ = run_cli(
            ["check", "--dir", FIXTURE_DIR, "--inventory", FIXTURE_INVENTORY, "--json"]
        )
        self.assertEqual(code, 1)
        payload = json.loads(output)
        self.assertEqual(payload["counts"], {"error": 1, "warning": 3, "info": 0})
        self.assertEqual(len(payload["findings"]), 4)
        self.assertEqual(payload["findings"][0]["id"], "TOPO-CYCLE")

    def test_clean_topology_passes(self) -> None:
        with write_topology(clean_topology_files()) as temp_dir:
            code, output, _ = run_cli(["check", "--dir", temp_dir])
        self.assertEqual(code, 0)
        self.assertIn("Result: PASSED", output)

    def test_missing_directory_is_runtime_error(self) -> None:
        code, _, stderr = run_cli(["check", "--dir", str(Path(FIXTURE_DIR, "absent"))])
        self.assertEqual(code, 1)
        self.assertIn("topology directory not found", stderr)

    def test_invalid_inventory_is_runtime_error(self) -> None:
        with write_topology({"bad.json": "{oops"}) as temp_dir:
            code, _, stderr = run_cli(
                ["check", "--dir", FIXTURE_DIR, "--inventory", str(Path(temp_dir, "bad.json"))]
            )
        self.assertEqual(code, 1)
        self.assertIn("invalid inventory JSON", stderr)


class StatsCommandTests(unittest.TestCase):
    def test_human_output(self) -> None:
        code, output, _ = run_cli(
            ["stats", "--dir", FIXTURE_DIR, "--inventory", FIXTURE_INVENTORY]
        )
        self.assertEqual(code, 0)
        self.assertIn("Topology statistics:", output)
        self.assertIn("Degree", output)
        self.assertIn("average 2.0", output)

    def test_json_output(self) -> None:
        code, output, _ = run_cli(
            ["stats", "--dir", FIXTURE_DIR, "--inventory", FIXTURE_INVENTORY, "--json"]
        )
        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(payload["devices"], 5)
        self.assertEqual(payload["components"], 1)
        self.assertEqual(payload["roles"]["core"], 1)


class ExportCommandTests(unittest.TestCase):
    def test_export_mermaid(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir, "map.mmd")
            code, output, _ = run_cli(
                [
                    "export",
                    "--dir",
                    FIXTURE_DIR,
                    "--inventory",
                    FIXTURE_INVENTORY,
                    "--format",
                    "mermaid",
                    "--out",
                    str(target),
                ]
            )
            self.assertEqual(code, 0)
            self.assertIn("Wrote Mermaid map", output)
            content = target.read_text(encoding="utf-8")
        self.assertTrue(content.startswith("graph LR"))
        self.assertIn("core-sw", content)

    def test_export_dot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir, "map.dot")
            code, _, _ = run_cli(
                ["export", "--dir", FIXTURE_DIR, "--format", "dot", "--out", str(target)]
            )
            content = target.read_text(encoding="utf-8")
        self.assertEqual(code, 0)
        self.assertIn("graph topology {", content)

    def test_export_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir, "map.json")
            code, _, _ = run_cli(
                ["export", "--dir", FIXTURE_DIR, "--format", "json", "--out", str(target)]
            )
            document = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(document["summary"]["edges"], 5)
        self.assertEqual(len(document["findings"]), 4)

    def test_export_html(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir, "map.html")
            code, output, _ = run_cli(
                ["export", "--dir", FIXTURE_DIR, "--format", "html", "--out", str(target)]
            )
            content = target.read_text(encoding="utf-8")
        self.assertEqual(code, 0)
        self.assertIn("Wrote HTML map", output)
        self.assertIn("<svg", content)

    def test_invalid_format_is_usage_error(self) -> None:
        code, _, _ = run_cli(
            ["export", "--dir", FIXTURE_DIR, "--format", "png", "--out", "out.png"]
        )
        self.assertEqual(code, 2)

    def test_export_requires_out(self) -> None:
        code, _, _ = run_cli(["export", "--dir", FIXTURE_DIR, "--format", "dot"])
        self.assertEqual(code, 2)

    def test_directory_is_required(self) -> None:
        code, _, _ = run_cli(["stats"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
