"""
AWS Deployment Orchestrator.
Coordinates ECR repository management, Docker image building and pushing,
ECS Fargate task registrations, and CloudWatch observability.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from infragenie.config import settings
from infragenie.deployer.cloudwatch import ObservabilityClient
from infragenie.deployer.ecr import ECRClient
from infragenie.deployer.ecs import ECSClient
from infragenie.utils.exceptions import DeployerError, DockerNotFoundError
from infragenie.utils.os_helper import get_docker_install_guide
from infragenie.utils.logger import get_logger

if TYPE_CHECKING:
    from infragenie.analyzer.models import AnalysisReport

log = get_logger(__name__)


class DeploymentResult:
    """Represents a completed deployment."""

    def __init__(
        self,
        image_uri: str,
        task_definition_arn: str,
        service_arn: str,
        service_name: str,
        cluster: str,
        region: str,
        public_url: str = "",
    ) -> None:
        self.image_uri = image_uri
        self.task_definition_arn = task_definition_arn
        self.service_arn = service_arn
        self.service_name = service_name
        self.cluster = cluster
        self.region = region
        self.public_url = public_url

    def to_dict(self) -> dict:
        return {
            "image_uri": self.image_uri,
            "task_definition_arn": self.task_definition_arn,
            "service_arn": self.service_arn,
            "service_name": self.service_name,
            "cluster": self.cluster,
            "region": self.region,
        }


class AWSDeployer:
    """
    End-to-end orchestrator for AWS container deployments.
    Builds and pushes Docker containers to Amazon ECR and updates ECS Fargate.
    """

    def __init__(self) -> None:
        self._ecr = ECRClient()
        self._ecs = ECSClient()
        self._obs = ObservabilityClient()

    def check_docker_available(self) -> bool:
        """Check if Docker CLI is installed and the daemon is responsive."""
        if not shutil.which("docker"):
            return False
        try:
            res = subprocess.run(
                ["docker", "info"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=4,
            )
            return res.returncode == 0
        except Exception:
            return False

    def deploy(
        self,
        local_image: str,
        report: AnalysisReport,
        image_tag: str = "latest",
        desired_count: int = 1,
        project_path: Optional[Path] = None,
    ) -> DeploymentResult:
        """
        Execute full deployment pipeline:
            1. Verify local Docker engine
            2. Push image to Amazon ECR
            3. Register ECS Task Definition
            4. Deploy / Update ECS Service
            5. Stream CloudWatch logs
        """
        repo_name = report.project_name.lower().replace("_", "-")
        log.info("Starting deployment", image=local_image, project=repo_name)

        if not self.check_docker_available():
            install_cmd = get_docker_install_guide()
            raise DockerNotFoundError(f"Docker is not running or not installed.\n  • Install: {install_cmd}\n  • Or test locally without AWS: infragenie run . -s")

        # Step 0: Build Docker Image
        log.info("Building Docker image locally", image=local_image)
        build_dir = str(project_path) if project_path else "."
        build_proc = subprocess.run(
            ["docker", "build", "-t", local_image, build_dir],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if build_proc.returncode != 0:
            raise DeployerError(f"Docker build failed: {build_proc.stderr}")
        log.info("Docker image built successfully", image=local_image)

        log.info("Step 1/3: Pushing image to Amazon ECR")
        self._ecr.create_or_get_repository(repo_name)
        remote_image_uri = self._ecr.push_image(local_image, repo_name, image_tag)

        log.info("Step 2/3: Registering ECS Task Definition")
        task_def = self._ecs.build_task_definition(remote_image_uri, report)
        task_def_arn = self._ecs.register_task_definition(task_def)

        log.info("Step 3/3: Deploying ECS Fargate Service")
        service_name = f"{repo_name}-service"
        service_arn = self._ecs.deploy_service(
            service_name=service_name,
            task_definition_arn=task_def_arn,
            desired_count=desired_count,
        )

        public_url = ""
        try:
            import time
            import boto3
            time.sleep(2)
            tasks_res = self._ecs._ecs.list_tasks(cluster=settings.ecs_cluster_name, serviceName=service_name)
            task_arns = tasks_res.get("taskArns", [])
            if task_arns:
                desc = self._ecs._ecs.describe_tasks(cluster=settings.ecs_cluster_name, tasks=task_arns[:1])
                for t in desc.get("tasks", []):
                    for attachment in t.get("attachments", []):
                        if attachment.get("type") == "ElasticNetworkInterface":
                            for detail in attachment.get("details", []):
                                if detail.get("name") == "networkInterfaceId":
                                    eni_id = detail["value"]
                                    ec2 = boto3.client("ec2", region_name=settings.aws_region)
                                    eni_info = ec2.describe_network_interfaces(NetworkInterfaceIds=[eni_id])
                                    association = eni_info["NetworkInterfaces"][0].get("Association", {})
                                    ip = association.get("PublicIp")
                                    if ip:
                                        port = getattr(report.runtime_needs, "exposed_port", 8080)
                                        public_url = f"http://{ip}:{port}"
                                        break
        except Exception:
            pass

        result = DeploymentResult(
            image_uri=remote_image_uri,
            task_definition_arn=task_def_arn,
            service_arn=service_arn,
            service_name=service_name,
            cluster=settings.ecs_cluster_name,
            region=settings.aws_region,
            public_url=public_url,
        )

        self._obs.log_deployment_event(result, report)
        log.info("Deployment complete!", service=service_name, image=remote_image_uri)
        return result

    def destroy(self, project_name: str, delete_ecr: bool = True) -> None:
        """Tear down AWS resources associated with a project."""
        clean_name = project_name.lower().replace("_", "-")
        # Handle if user passed service name directly (e.g. my-python-app-service)
        if clean_name.endswith("-service"):
            clean_name = clean_name[:-8]
        service_name = f"{clean_name}-service"

        log.info("Starting AWS resource teardown", project=clean_name, service=service_name)
        self._ecs.delete_service(service_name)
        self._ecs.deregister_task_definitions(f"infragenie-{clean_name}")

        if delete_ecr:
            self._ecr.delete_repository(clean_name, force=True)

        log.info("AWS teardown completed successfully!", project=clean_name)
