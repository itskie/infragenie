# AWS Well-Architected & Container Security Best Practices

## Security Pillar (Section 14)
- Apply Least Privilege IAM to all ECS tasks.
- Store secrets in AWS Secrets Manager; reference ARNs in task definitions.
- Enable GuardDuty and Inspector for runtime threat detection.
- All container images must be scanned with Amazon Inspector before deployment.

## Dockerfile Security Rules (CIS Benchmark)
- NEVER run containers as root. Always add a non-root user and switch to it.
- Use minimal base images: python:slim, node:alpine, golang:alpine, distroless.
- Pin base image versions with SHA digests in production.
- Remove build tools from the final runtime image (use multi-stage builds).
- Include a HEALTHCHECK instruction in every Dockerfile.
- Do not COPY .git, .env, secrets, or private keys into the image.
- Add a .dockerignore file to prevent accidental secret leakage.
- Use --no-cache-dir for pip installs to reduce image size.
- Use --omit=dev for npm installs to exclude dev dependencies.

## Multi-Stage Build Pattern
- Stage 1 (builder): Install build tools, compile, install dependencies.
- Stage 2 (runtime): Copy only built artifacts. No build tools.
- Label final stage: FROM base AS runtime

## Networking (Section 6)
- Backend services must run in private subnets.
- Outbound traffic only via NAT Gateway.
- Security groups: allow only the required port inbound.
- Use VPC endpoints for ECR, S3, and CloudWatch to avoid public internet.

## DevOps Flow (Section 15)
- Source → Build → Test (Trivy scan) → Deploy → Monitor
- Use ECR lifecycle policies to delete untagged images older than 30 days.
- Use ECS rolling deployments with health check grace period.

## Cost Optimization (Section 17)
- Dev environments: t3.micro / Fargate 256 CPU / 512 MB.
- Prod environments: Auto Scaling based on CPU/memory CloudWatch alarms.
- Use Savings Plans for sustained ECS Fargate workloads.
- Prefer Graviton (ARM) instances for 20% cost reduction.

## ECS Fargate Best Practices
- Set CPU and memory limits at task level, not container level.
- Enable execute-command for debugging without SSH.
- Use task roles (not instance profiles) for IAM permissions.
- Enable CloudWatch Container Insights for observability.
