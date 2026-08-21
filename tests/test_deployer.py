from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from infragenie.analyzer.models import (
    ASTInsights,
    AnalysisReport,
    Framework,
    Language,
    RuntimeNeeds,
    StackDetectionResult,
)
from infragenie.deployer.deployer import AWSDeployer, DeploymentResult
from infragenie.deployer.ecr import ECRClient
from infragenie.deployer.ecs import ECSClient
from infragenie.deployer.cloudwatch import ObservabilityClient


class TestAWSDeployer:
    def test_deploy_calls_ecr_and_ecs(self, tmp_path):
        """Full deploy() calls ECR push and ECS service deployment."""
        from infragenie.analyzer import SemanticAnalyzer

        analyzer = SemanticAnalyzer()
        (tmp_path / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
        (tmp_path / "requirements.txt").write_text("fastapi==0.111.0\n")
        (tmp_path / "Dockerfile").write_text("FROM python:3.12-slim\n")
        report = analyzer.analyze(tmp_path)

        with (
            patch.object(AWSDeployer, "check_docker_available", return_value=True),
            patch("infragenie.deployer.deployer.ECRClient") as mock_ecr_cls,
            patch("infragenie.deployer.deployer.ECSClient") as mock_ecs_cls,
            patch("infragenie.deployer.deployer.ObservabilityClient") as mock_obs_cls,
        ):
            mock_ecr = MagicMock()
            mock_ecr.push_image.return_value = "123.dkr.ecr.us-east-1.amazonaws.com/test:latest"
            mock_ecr_cls.return_value = mock_ecr

            mock_ecs = MagicMock()
            mock_ecs.build_task_definition.return_value = {"family": "test"}
            mock_ecs.register_task_definition.return_value = "arn:aws:ecs:us-east-1:123:task-definition/test:1"
            mock_ecs.deploy_service.return_value = "arn:aws:ecs:us-east-1:123:service/test-service"
            mock_ecs_cls.return_value = mock_ecs

            mock_obs = MagicMock()
            mock_obs_cls.return_value = mock_obs

            deployer = AWSDeployer()
            result = deployer.deploy(
                local_image="test-project:latest",
                report=report,
                image_tag="latest",
                desired_count=1,
                project_path=tmp_path,
            )

            assert isinstance(result, DeploymentResult)
            assert result.service_name == f"{report.project_name.lower().replace('_', '-')}-service"
            mock_ecr.create_or_get_repository.assert_called_once()
            mock_ecr.push_image.assert_called_once()
            mock_ecs.build_task_definition.assert_called_once()
            mock_ecs.register_task_definition.assert_called_once()
            mock_ecs.deploy_service.assert_called_once()


class TestDoctor:
    def test_doctor_command_runs(self):
        from typer.testing import CliRunner
        from infragenie.cli import app
        runner = CliRunner()
        res = runner.invoke(app, ["doctor"])
        assert res.exit_code == 0
        assert "System & Cloud Health Check" in res.stdout
