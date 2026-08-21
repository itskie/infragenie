"""
Amazon ECR — authenticate, create repository, push Docker image.
Uses IAM roles (no hardcoded credentials).
"""
from __future__ import annotations

import base64
import subprocess
from pathlib import Path

import boto3
import botocore.exceptions

from infragenie.config import settings
from infragenie.utils.exceptions import AWSAuthError, ECRError
from infragenie.utils.logger import get_logger

log = get_logger(__name__)


class ECRClient:
    """
    Manages ECR authentication, repository lifecycle, and image push.
    """

    def __init__(self) -> None:
        try:
            session = boto3.Session(
                region_name=settings.aws_region,
                profile_name=settings.aws_profile or None,
            )
            self._ecr = session.client("ecr")
            self._sts = session.client("sts")
            self._account_id = self._get_account_id()
        except botocore.exceptions.NoCredentialsError as e:
            raise AWSAuthError() from e

    def _get_account_id(self) -> str:
        """Get AWS account ID via STS."""
        try:
            return self._sts.get_caller_identity()["Account"]
        except botocore.exceptions.ClientError as e:
            raise AWSAuthError() from e

    @property
    def registry_uri(self) -> str:
        """Return ECR registry URI."""
        if settings.ecr_registry_uri:
            return settings.ecr_registry_uri
        return f"{self._account_id}.dkr.ecr.{settings.aws_region}.amazonaws.com"

    def create_or_get_repository(self, repo_name: str) -> str:
        """
        Create ECR repository if it doesn't exist.
        Returns the repository URI.
        """
        try:
            response = self._ecr.describe_repositories(repositoryNames=[repo_name])
            uri = response["repositories"][0]["repositoryUri"]
            log.info("ECR repository exists", repo=repo_name, uri=uri)
            return uri
        except self._ecr.exceptions.RepositoryNotFoundException:
            pass

        try:
            response = self._ecr.create_repository(
                repositoryName=repo_name,
                imageScanningConfiguration={"scanOnPush": True},
                encryptionConfiguration={"encryptionType": "AES256"},
                tags=[
                    {"Key": "ManagedBy", "Value": "InfraGenie"},
                    {"Key": "Environment", "Value": settings.infragenie_env},
                ],
            )
            uri = response["repository"]["repositoryUri"]
            log.info("ECR repository created", repo=repo_name, uri=uri)

            # Set lifecycle policy to clean up untagged images
            self._ecr.put_lifecycle_policy(
                repositoryName=repo_name,
                lifecyclePolicyText='{"rules":[{"rulePriority":1,"description":"Remove untagged images after 30 days","selection":{"tagStatus":"untagged","countType":"sinceImagePushed","countUnit":"days","countNumber":30},"action":{"type":"expire"}}]}',
            )
            return uri
        except botocore.exceptions.ClientError as e:
            raise ECRError(f"Failed to create ECR repository: {e}") from e

    def authenticate_docker(self) -> None:
        """Run docker login for ECR using temporary credentials."""
        try:
            response = self._ecr.get_authorization_token()
            token = response["authorizationData"][0]["authorizationToken"]
            decoded = base64.b64decode(token).decode("utf-8")
            _, password = decoded.split(":", 1)

            # Ensure no GUI credsStore blocks headless docker login
            cfg_path = Path.home() / ".docker" / "config.json"
            if cfg_path.exists():
                try:
                    import json
                    cfg = json.loads(cfg_path.read_text())
                    if cfg.get("credsStore") == "desktop":
                        del cfg["credsStore"]
                        cfg_path.write_text(json.dumps(cfg, indent=2))
                except Exception:
                    pass

            domain = self.registry_uri.replace("https://", "").replace("http://", "")
            cmd = [
                "docker", "login",
                "--username", "AWS",
                "--password-stdin",
                domain,
            ]
            proc = subprocess.run(
                cmd,
                input=password,
                capture_output=True,
                text=True,
                timeout=20,
            )
            if proc.returncode != 0:
                raise ECRError(f"docker login failed: {proc.stderr}")
            log.info("Docker authenticated with ECR", registry=self.registry_uri)
        except botocore.exceptions.ClientError as e:
            raise ECRError(f"Failed to get ECR auth token: {e}") from e

    def push_image(self, local_tag: str, repo_name: str, image_tag: str = "latest") -> str:
        """
        Tag and push a local Docker image to ECR.
        Returns the full ECR image URI.
        """
        repo_uri = self.create_or_get_repository(repo_name)
        self.authenticate_docker()

        ecr_tag = f"{repo_uri}:{image_tag}"

        # Tag
        tag_result = subprocess.run(
            ["docker", "tag", local_tag, ecr_tag],
            capture_output=True, text=True, timeout=60,
        )
        if tag_result.returncode != 0:
            raise ECRError(f"docker tag failed: {tag_result.stderr}")

        # Push
        log.info("Pushing image to ECR", tag=ecr_tag)
        push_result = subprocess.run(
            ["docker", "push", ecr_tag],
            capture_output=True, text=True, timeout=600,
        )
        if push_result.returncode != 0:
            raise ECRError(f"docker push failed: {push_result.stderr}")

        log.info("Image pushed to ECR", uri=ecr_tag)
        return ecr_tag


    def delete_repository(self, repository_name: str, force: bool = True) -> None:
        """Delete an ECR repository and its images."""
        try:
            log.info("Deleting ECR repository", repo=repository_name)
            self._ecr.delete_repository(
                repositoryName=repository_name,
                force=force,
            )
        except botocore.exceptions.ClientError as e:
            if e.response["Error"]["Code"] != "RepositoryNotFoundException":
                log.warning("ECR repository deletion note", error=str(e))
