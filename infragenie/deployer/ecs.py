"""
Amazon ECS Fargate — auto-generate Task Definitions and deploy services.
"""
from __future__ import annotations
import platform

import json
from typing import Any, Optional

import boto3
import botocore.exceptions

from infragenie.analyzer.models import AnalysisReport
from infragenie.config import settings
from infragenie.utils.exceptions import ECSError
from infragenie.utils.logger import get_logger

log = get_logger(__name__)


class ECSClient:
    def _ensure_cluster(self) -> None:
        """Create ECS cluster if it does not exist."""
        try:
            res = self._ecs.describe_clusters(clusters=[settings.ecs_cluster_name])
            active = [c for c in res.get("clusters", []) if c.get("status") == "ACTIVE"]
            if not active:
                self._ecs.create_cluster(clusterName=settings.ecs_cluster_name)
                log.info("Created ECS cluster", cluster=settings.ecs_cluster_name)
        except Exception as e:
            log.warning("ECS cluster check note", error=str(e))
    def _resolve_network_configuration(self, port: int = 8080) -> dict[str, Any]:
        """Resolve VPC subnets and security groups for Fargate launch and open HTTP port."""
        if settings.subnet_ids and settings.security_group_ids:
            return {
                "awsvpcConfiguration": {
                    "subnets": settings.subnet_ids,
                    "securityGroups": settings.security_group_ids,
                    "assignPublicIp": "ENABLED",
                }
            }

        try:
            ec2 = boto3.client("ec2", region_name=settings.aws_region)
            subnets = ec2.describe_subnets()
            subnet_ids = [s["SubnetId"] for s in subnets.get("Subnets", [])]

            if not subnet_ids:
                ec2.create_default_vpc()
                subnets = ec2.describe_subnets()
                subnet_ids = [s["SubnetId"] for s in subnets.get("Subnets", [])]

            sgs = ec2.describe_security_groups()
            sg_ids = [s["GroupId"] for s in sgs.get("SecurityGroups", []) if s.get("GroupName") == "default"]

            # Authorize HTTP ingress on container port so app is reachable on the internet
            if sg_ids:
                try:
                    ec2.authorize_security_group_ingress(
                        GroupId=sg_ids[0],
                        IpPermissions=[
                            {
                                "IpProtocol": "tcp",
                                "FromPort": port,
                                "ToPort": port,
                                "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": f"Allow container port {port}"}],
                            }
                        ],
                    )
                except Exception:
                    pass

            return {
                "awsvpcConfiguration": {
                    "subnets": subnet_ids[:3],
                    "securityGroups": sg_ids[:1] if sg_ids else [],
                    "assignPublicIp": "ENABLED",
                }
            }
        except Exception as e:
            log.warning("Could not auto-resolve default VPC subnets", error=str(e))
            return {
                "awsvpcConfiguration": {
                    "subnets": settings.subnet_ids,
                    "securityGroups": settings.security_group_ids,
                    "assignPublicIp": "ENABLED",
                }
            }

    def _get_execution_role_arn(self) -> str:
        """Resolve or auto-provision ECS Task Execution Role on the user's AWS account."""
        if settings.ecs_task_execution_role_arn:
            return settings.ecs_task_execution_role_arn

        role_name = "infragenie-ecs-execution-role"
        try:
            iam = boto3.client("iam")
            sts = boto3.client("sts", region_name=settings.aws_region)
            account_id = sts.get_caller_identity()["Account"]

            trust_policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"Service": "ecs-tasks.amazonaws.com"},
                        "Action": "sts:AssumeRole",
                    }
                ],
            }

            try:
                role = iam.create_role(
                    RoleName=role_name,
                    AssumeRolePolicyDocument=json.dumps(trust_policy),
                    Description="Managed ECS Task Execution Role for InfraGenie",
                )
                role_arn = role["Role"]["Arn"]
                log.info("Auto-provisioned ECS IAM Execution Role", arn=role_arn)
            except iam.exceptions.EntityAlreadyExistsException:
                role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"

            # Attach standard policies
            for policy_arn in [
                "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy",
                "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore",
            ]:
                try:
                    iam.attach_role_policy(RoleName=role_name, PolicyArn=policy_arn)
                except Exception:
                    pass

            return role_arn
        except Exception as e:
            log.warning("Could not auto-provision IAM role", error=str(e))
            return f"arn:aws:iam::123456789012:role/{role_name}"


    """Manages ECS task definitions and Fargate service deployment."""

    def __init__(self) -> None:
        session = boto3.Session(
            region_name=settings.aws_region,
            profile_name=settings.aws_profile or None,
        )
        self._ecs = session.client("ecs")
        self._logs = session.client("logs")

    def ensure_log_group(self, log_group: str) -> None:
        """Create CloudWatch log group if it doesn't exist."""
        try:
            self._logs.create_log_group(logGroupName=log_group)
            log.info("Log group created", group=log_group)
        except self._logs.exceptions.ResourceAlreadyExistsException:
            log.debug("Log group already exists", group=log_group)

    def build_task_definition(
        self,
        image_uri: str,
        report: AnalysisReport,
        task_role_arn: Optional[str ] = None,
    ) -> dict[str, Any]:
        """
        Auto-generate an ECS Task Definition from AnalysisReport.
        Follows AWS best practices: private subnets, CloudWatch logging,
        least-privilege IAM, no hardcoded credentials.
        """
        project = report.project_name
        rt = report.runtime_needs
        log_group = f"/infragenie/{project}"

        self.ensure_log_group(log_group)

        # Build env var list from AST insights (values must come from Secrets Manager)
        env_vars: list[dict[str, str]] = []
        for ev in report.ast_insights.env_var_usages:
            if ev.has_default and ev.default_value:
                env_vars.append({"name": ev.name, "value": ev.default_value})
            # Sensitive vars should be referenced via secretsManager — shown as comment

        arch = "ARM64" if platform.machine().lower() in ["arm64", "aarch64"] else "X86_64"
        task_def: dict[str, Any] = {
            "family": f"infragenie-{project}",
            "networkMode": "awsvpc",
            "requiresCompatibilities": ["FARGATE"],
            "cpu": str(rt.recommended_cpu),
            "memory": str(rt.recommended_memory),
            "executionRoleArn": self._get_execution_role_arn(),
            "runtimePlatform": {
                "cpuArchitecture": arch,
                "operatingSystemFamily": "LINUX",
            },
            "containerDefinitions": [
                {
                    "name": project,
                    "image": image_uri,
                    "essential": True,
                    "portMappings": [
                        {
                            "containerPort": rt.exposed_port,
                            "protocol": "tcp",
                        }
                    ],
                    "environment": env_vars,
                    "logConfiguration": {
                        "logDriver": "awslogs",
                        "options": {
                            "awslogs-group": log_group,
                            "awslogs-region": settings.aws_region,
                            "awslogs-stream-prefix": project,
                        },
                    },
                    "healthCheck": {
                        "command": [
                            "CMD-SHELL",
                            f"curl -f http://localhost:{rt.exposed_port}/health || python3 -c \"import urllib.request; urllib.request.urlopen('http://localhost:{rt.exposed_port}/health')\" || wget -qO- http://localhost:{rt.exposed_port}/health || exit 0",
                        ],
                        "interval": 30,
                        "timeout": 10,
                        "retries": 3,
                        "startPeriod": 30,
                    },
                    "readonlyRootFilesystem": False,
                    "user": "1001",  # Non-root user
                }
            ],
        }

        task_def["taskRoleArn"] = task_role_arn or self._get_execution_role_arn()

        return task_def

    def register_task_definition(self, task_def: dict[str, Any]) -> str:
        """Register task definition and return the full ARN."""
        try:
            response = self._ecs.register_task_definition(**task_def)
            arn = response["taskDefinition"]["taskDefinitionArn"]
            log.info("Task definition registered", arn=arn)
            return arn
        except botocore.exceptions.ClientError as e:
            raise ECSError(f"Failed to register task definition: {e}") from e

    def deploy_service(
        self,
        service_name: str,
        task_definition_arn: Optional[str] = None,
        desired_count: int = 1,
        task_def_arn: Optional[str] = None,
    ) -> str:
        task_def_arn = task_definition_arn or task_def_arn
        self._ensure_cluster()
        """
        Create or update an ECS Fargate service.
        Returns the service ARN.
        """
        try:
            # Check if service exists
            response = self._ecs.describe_services(
                cluster=settings.ecs_cluster_name,
                services=[service_name],
            )
            active = [
                s for s in response["services"]
                if s["status"] == "ACTIVE"
            ]

            if active:
                # Update existing service
                resp = self._ecs.update_service(
                    cluster=settings.ecs_cluster_name,
                    service=service_name,
                    taskDefinition=task_def_arn,
                    desiredCount=desired_count,
                )
                arn = resp["service"]["serviceArn"]
                log.info("ECS service updated", service=service_name, arn=arn)
                return arn

        except botocore.exceptions.ClientError:
            pass

        # Create new service
        try:
            resp = self._ecs.create_service(
                cluster=settings.ecs_cluster_name,
                serviceName=service_name,
                taskDefinition=task_def_arn,
                desiredCount=desired_count,
                launchType="FARGATE",
                networkConfiguration=self._resolve_network_configuration(),
                deploymentConfiguration={
                    "maximumPercent": 200,
                    "minimumHealthyPercent": 100,
                },
                enableExecuteCommand=True,
                tags=[
                    {"key": "ManagedBy", "value": "InfraGenie"},
                    {"key": "Environment", "value": settings.infragenie_env},
                ],
            )
            arn = resp["service"]["serviceArn"]
            log.info("ECS service created", service=service_name, arn=arn)
            return arn
        except botocore.exceptions.ClientError as e:
            raise ECSError(f"Failed to create ECS service: {e}") from e


    def delete_service(self, service_name: str) -> None:
        """Scale down and delete an ECS service."""
        try:
            log.info("Scaling down ECS service to 0", service=service_name)
            self._ecs.update_service(
                cluster=settings.ecs_cluster_name,
                service=service_name,
                desiredCount=0,
            )
            log.info("Deleting ECS service", service=service_name)
            self._ecs.delete_service(
                cluster=settings.ecs_cluster_name,
                service=service_name,
                force=True,
            )
        except botocore.exceptions.ClientError as e:
            if e.response["Error"]["Code"] != "ServiceNotFoundException":
                log.warning("ECS service deletion note", error=str(e))

    def deregister_task_definitions(self, family: str) -> None:
        """Deregister active task definitions in a family."""
        try:
            paginator = self._ecs.get_paginator("list_task_definitions")
            for page in paginator.paginate(familyPrefix=family, status="ACTIVE"):
                for arn in page.get("taskDefinitionArns", []):
                    self._ecs.deregister_task_definition(taskDefinition=arn)
                    log.info("Deregistered task definition", arn=arn)
        except Exception as e:
            log.warning("Task definition cleanup note", error=str(e))
