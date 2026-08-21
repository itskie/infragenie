"""
CloudWatch observability and feedback loop.
Logs deployment events and scan results for model fine-tuning.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import boto3
import botocore.exceptions

from infragenie.config import settings
from infragenie.utils.logger import get_logger

log = get_logger(__name__)

LOG_GROUP = "/infragenie/deployments"


class ObservabilityClient:
    """Logs InfraGenie events to CloudWatch for monitoring and feedback."""

    def __init__(self) -> None:
        session = boto3.Session(
            region_name=settings.aws_region,
            profile_name=settings.aws_profile or None,
        )
        self._logs = session.client("logs")
        self._ensure_log_group()

    def _ensure_log_group(self) -> None:
        try:
            self._logs.create_log_group(logGroupName=LOG_GROUP)
        except self._logs.exceptions.ResourceAlreadyExistsException:
            pass
        except botocore.exceptions.ClientError as e:
            log.warning("Could not create CW log group", error=str(e))

    def log_deployment(self, project: str, event: dict[str, Any]) -> None:
        """Log a deployment event to CloudWatch."""
        stream = f"{project}/{datetime.now(timezone.utc).strftime('%Y/%m/%d')}"
        try:
            self._logs.create_log_stream(
                logGroupName=LOG_GROUP,
                logStreamName=stream,
            )
        except self._logs.exceptions.ResourceAlreadyExistsException:
            pass
        except botocore.exceptions.ClientError:
            return

        try:
            self._logs.put_log_events(
                logGroupName=LOG_GROUP,
                logStreamName=stream,
                logEvents=[{
                    "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
                    "message": json.dumps({"project": project, **event}),
                }],
            )
            log.debug("Deployment event logged to CloudWatch", project=project)
        except botocore.exceptions.ClientError as e:
            log.warning("Failed to log to CloudWatch", error=str(e))

    def log_deployment_event(self, result: Any, report: Any) -> None:
        """Log a deployment event object to CloudWatch."""
        project = getattr(report, "project_name", "app")
        event = {
            "service_name": getattr(result, "service_name", ""),
            "image_uri": getattr(result, "image_uri", ""),
            "cluster": getattr(result, "cluster", ""),
            "region": getattr(result, "region", ""),
        }
        self.log_deployment(project, event)
