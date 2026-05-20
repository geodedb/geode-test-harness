"""Tests for cluster mode in the runner."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestResultClusterNode:
    def test_result_has_cluster_node_field(self) -> None:
        from geodetestlab.lib.runner_types import TestResult

        result = TestResult(name="test1", passed=True, duration_ms=100, cluster_node=2)
        assert result.cluster_node == 2

    def test_result_cluster_node_default_none(self) -> None:
        from geodetestlab.lib.runner_types import TestResult

        result = TestResult(name="test1", passed=True, duration_ms=100)
        assert result.cluster_node is None


class TestRunTestsClusterMode:
    def test_cluster_mode_calls_start_cluster(self) -> None:
        from geodetestlab.lib.cluster_types import ClusterConfig, ClusterNodeState, ClusterState
        from geodetestlab.lib.spec import TestSpec

        spec = TestSpec(
            name="cluster test",
            description="",
            mode="cluster",
            cluster_config=ClusterConfig.from_size(2),
            tests=[],
        )

        mock_cluster_state = ClusterState(
            nodes=[
                ClusterNodeState(node_id=0, port=4000, grpc_port=None, data_dir="/tmp/n0", process=MagicMock()),
                ClusterNodeState(node_id=1, port=4001, grpc_port=None, data_dir="/tmp/n1", process=MagicMock()),
            ]
        )

        with (
            patch("geodetestlab.lib.runner.start_cluster", return_value=mock_cluster_state) as mock_start,
            patch("geodetestlab.lib.runner.stop_cluster") as mock_stop,
            patch("geodetestlab.lib.runner.find_geode_binary", return_value="/usr/bin/geode"),
        ):
            from geodetestlab.lib.runner import run_tests

            exit_code, summary = run_tests(
                spec=spec,
                secrets={},
                env_overrides={},
                verbose=False,
            )
            mock_start.assert_called_once()
            mock_stop.assert_called_once()
            assert exit_code == 0
