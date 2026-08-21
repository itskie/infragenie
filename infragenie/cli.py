"""
InfraGenie CLI — AI-Native DevSecOps Orchestration from the terminal.
Supports full Linux-style short & long flags (-v, -o, -d, -f, -t, -c, -s).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from infragenie.config import settings
from infragenie.utils.exceptions import InfraGenieError, DockerNotFoundError
from infragenie.utils.logger import configure_logging, get_logger

log = get_logger(__name__)

app = typer.Typer(
    name="infragenie",
    help="🧞 AI-Native DevSecOps Orchestrator — secure containerization without the manual work.",
    add_completion=True,
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
console = Console()


def _banner() -> None:
    console.print(
        Panel.fit(
            "[bold cyan]🧞 InfraGenie[/bold cyan] [dim]v0.1.0[/dim]\n[dim]AI-Native DevSecOps Orchestrator[/dim]",
            border_style="cyan",
        )
    )


@app.callback()
def main(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """Global configuration callback."""
    log_level = "DEBUG" if verbose else settings.log_level
    configure_logging(level=log_level, log_format=settings.log_format)


# ---------------------------------------------------------------------------
# 1. ANALYZE
# ---------------------------------------------------------------------------
@app.command(name="analyze")
def analyze(
    path: Path = typer.Argument(
        default=Path("."),
        help="Path to the project directory to analyze",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Save analysis report as JSON to this file path",
    ),
) -> None:
    """🔍 Analyze a project's tech stack, port, env vars, and runtime requirements."""
    _banner()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        t = progress.add_task("Analyzing project...", total=None)
        try:
            from infragenie.analyzer import SemanticAnalyzer
            analyzer = SemanticAnalyzer()
            report = analyzer.analyze(path)
            progress.update(t, description="✅ Analysis complete")
        except InfraGenieError as e:
            progress.update(t, description="❌ Analysis failed")
            console.print(f"[bold red]Error: {e}[/bold red]")
            raise typer.Exit(code=1)

    table = Table(title=f"Analysis: {report.project_name}", show_lines=True)
    table.add_column("Property", style="cyan", no_wrap=True)
    table.add_column("Value", style="green")

    table.add_row("Language", report.stack.language.value)
    table.add_row("Framework", report.stack.framework.value)
    table.add_row("Runtime", report.runtime_needs.base_image)
    table.add_row("Port", str(report.runtime_needs.exposed_port or "None detected"))
    table.add_row("Start Command", report.runtime_needs.start_command or "None")
    table.add_row("Files Parsed", str(report.ast_insights.files_parsed))
    table.add_row("Env Vars Detected", str(len(report.ast_insights.env_var_usages)))
    table.add_row("Health Endpoints", str(len(report.ast_insights.health_check_endpoints)))
    table.add_row("Dependencies", str(len(report.stack.dependencies)))

    console.print(table)

    if output and isinstance(output, Path):
        output.write_text(report.to_json())
        console.print(f"[dim]Report saved to {output}[/dim]")


# ---------------------------------------------------------------------------
# 2. GENERATE
# ---------------------------------------------------------------------------
@app.command(name="generate")
def generate(
    path: Path = typer.Argument(
        default=Path("."),
        help="Path to the project directory",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
    output_dir: Optional[Path] = typer.Option(
        None,
        "--output-dir",
        "-o",
        help="Directory to write Dockerfile and .dockerignore",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-d",
        help="Print generated files to terminal without writing to disk",
    ),
) -> None:
    """🐳 Generate a secure multi-stage Dockerfile using AI."""
    _banner()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        t1 = progress.add_task("Analyzing project...", total=None)
        from infragenie.analyzer import SemanticAnalyzer
        from infragenie.generator import DockerfileGenerator

        report = SemanticAnalyzer().analyze(path)
        progress.update(t1, description="✅ Analysis complete")

        t2 = progress.add_task("Generating Dockerfile via AI + RAG...", total=None)
        generator = DockerfileGenerator()
        artifacts = generator.generate(report)
        progress.update(t2, description="✅ Dockerfile generated")

    if dry_run:
        console.print("\n[bold green]Generated Dockerfile:[/bold green]")
        console.print(Panel(artifacts.dockerfile, border_style="green"))
        console.print("\n[bold green]Generated .dockerignore:[/bold green]")
        console.print(Panel(artifacts.dockerignore, border_style="green"))
    else:
        out = output_dir or path
        generator.write_artifacts(artifacts, out)
        console.print(f"[bold green]✅ Dockerfile written to {out / 'Dockerfile'}[/bold green]")
        console.print(f"[bold green]✅ .dockerignore written to {out / '.dockerignore'}[/bold green]")

    if artifacts.notes:
        console.print("\n[bold]📝 Notes:[/bold]")
        for note in artifacts.notes:
            console.print(f"  • {note}")


# ---------------------------------------------------------------------------
# 3. SCAN
# ---------------------------------------------------------------------------
@app.command(name="scan")
def scan(
    target: str = typer.Argument(
        default=".",
        help="Path to project directory or image name to scan",
    ),
    image: bool = typer.Option(
        False,
        "--image",
        "-i",
        help="Scan a Docker image instead of filesystem directory",
    ),
) -> None:
    """🔒 Run Trivy security scan on filesystem or Docker image."""
    _banner()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        t = progress.add_task(f"Scanning {target}...", total=None)
        try:
            from infragenie.scanner import SecurityScanner
            scanner = SecurityScanner()

            if image:
                report = scanner.scan_image(target)
            else:
                report = scanner.scan_filesystem(Path(target))

            progress.update(t, description="✅ Scan complete")
        except InfraGenieError as e:
            progress.update(t, description="❌ Scan failed")
            console.print(f"[bold red]Error: {e}[/bold red]")
            raise typer.Exit(code=1)

    table = Table(title=f"Security Scan: {target}", show_lines=True)
    table.add_column("Severity", style="bold")
    table.add_column("Count", justify="right")

    severities = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"]
    colors = {
        "CRITICAL": "bold red",
        "HIGH": "red",
        "MEDIUM": "yellow",
        "LOW": "blue",
        "UNKNOWN": "dim",
    }

    for sev in severities:
        count = report.summary.get(sev, 0)
        table.add_row(f"[{colors.get(sev, 'white')}]{sev}[/{colors.get(sev, 'white')}]", str(count))

    console.print(table)

    if report.passed:
        console.print("\n[bold green]✅ Security scan PASSED! No critical vulnerabilities found.[/bold green]")
    else:
        console.print(
            f"\n[bold red]❌ Security scan FAILED! Found {report.critical_count} CRITICAL, "
            f"{report.high_count} HIGH vulnerabilities.[/bold red]"
        )
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# 4. DEPLOY
# ---------------------------------------------------------------------------
@app.command(name="deploy")
def deploy(
    path: Path = typer.Argument(
        default=Path("."),
        help="Path to project directory",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
    image_tag: str = typer.Option(
        "latest",
        "--tag",
        "-t",
        help="Tag for the container image (e.g. v1.0.0)",
    ),
    count: int = typer.Option(
        1,
        "--count",
        "-c",
        help="Desired number of ECS Fargate tasks",
    ),
) -> None:
    """🚀 Deploy to AWS ECS Fargate (ECR push + service update)."""
    _banner()

    from infragenie.analyzer import SemanticAnalyzer
    from infragenie.deployer import AWSDeployer
    from infragenie.utils.os_helper import install_docker_interactively

    report = SemanticAnalyzer().analyze(path)
    local_image = f"{report.project_name.lower().replace('_', '-')}:{image_tag}"

    deployer = AWSDeployer()

    # Pre-flight Docker Check (Outside progress spinner to avoid terminal lock)
    if not deployer.check_docker_available():
        installed = install_docker_interactively(console=console)
        if not installed or not deployer.check_docker_available():
            console.print("[bold red]❌ Deployment halted: Docker Engine is required for cloud deployment.[/bold red]")
            console.print("[dim]Tip: You can test locally without AWS by running: infragenie run . -s[/dim]")
            raise typer.Exit(code=1)
        console.print("[bold green]✅ Docker Engine active! Continuing deployment...[/bold green]\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        t = progress.add_task("Deploying to AWS ECS Fargate...", total=None)
        try:
            result = deployer.deploy(local_image, report, image_tag, count, project_path=path)
            progress.update(t, description="✅ Deployed to AWS")
        except InfraGenieError as e:
            progress.update(t, description="❌ Deployment failed")
            console.print(f"[bold red]Deployment error: {e}[/bold red]")
            raise typer.Exit(code=1)

    console.print(
        Panel.fit(
            f"[bold green]✨ Deployed successfully![/bold green]\n\n"
            f"[cyan]Service:[/cyan]  {result.service_name}\n"
            f"[cyan]Image:[/cyan]    {result.image_uri}\n"
            f"[cyan]Cluster:[/cyan]  {result.cluster}\n"
            f"[cyan]Region:[/cyan]   {result.region}",
            title="Deployment Result",
            border_style="green",
        )
    )


# ---------------------------------------------------------------------------
# 5. RUN (PIPELINE)
# ---------------------------------------------------------------------------
@app.command(name="run")
def run(
    ctx: typer.Context,
    path: Path = typer.Argument(
        default=Path("."),
        help="Path to the project directory",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
    skip_deploy: bool = typer.Option(
        False,
        "--skip-deploy",
        "-s",
        help="Stop after scan (do not deploy to AWS)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-d",
        help="Dry run mode (do not write to disk or deploy)",
    ),
) -> None:
    """🧞 Full pipeline: Analyze → Generate → Scan → Deploy."""
    _banner()
    console.print("[bold cyan]Running full InfraGenie pipeline...[/bold cyan]\n")

    ctx.invoke(analyze, path=path, output=None)
    ctx.invoke(generate, path=path, output_dir=None, dry_run=dry_run)
    try:
        ctx.invoke(scan, target=str(path), image=False)
    except Exception as e:
        console.print(f"[yellow]⚠️ Security scan note: {e}[/yellow]")

    if not skip_deploy and not dry_run:
        ctx.invoke(deploy, path=path, image_tag="latest", count=1)



# ---------------------------------------------------------------------------
# 6. RM / DESTROY (Linux style `rm`)
# ---------------------------------------------------------------------------
@app.command(name="rm")
@app.command(name="destroy", hidden=True)
@app.command(name="down", hidden=True)
def rm(
    path_or_name: str = typer.Argument(
        default=".",
        help="Path to project directory or project name",
    ),
    delete_ecr: bool = typer.Option(
        True,
        "--ecr/--no-ecr",
        help="Also delete Amazon ECR repository and container images",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Force removal without confirmation prompt (Linux `rm -f` style)",
    ),
) -> None:
    """🗑️ Remove deployed AWS resources (ECS Service, Tasks, ECR) — Linux `rm -f` style."""
    _banner()

    p = Path(path_or_name)
    if p.exists() and p.is_dir():
        proj_name = p.resolve().name
    else:
        proj_name = path_or_name

    clean_name = proj_name.lower().replace("_", "-")

    if not force:
        confirm = typer.confirm(
            f"Remove all AWS cloud resources for '{clean_name}' (ECS service, ECR repo)?",
            default=False,
        )
        if not confirm:
            console.print("[yellow]Removal cancelled.[/yellow]")
            return

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        t = progress.add_task(f"Removing AWS resources for {clean_name}...", total=None)
        try:
            from infragenie.deployer import AWSDeployer
            deployer = AWSDeployer()
            deployer.destroy(clean_name, delete_ecr=delete_ecr)
            progress.update(t, description="✅ AWS resources removed")
        except Exception as e:
            progress.update(t, description="❌ Removal failed")
            console.print(f"[bold red]Removal error: {e}[/bold red]")
            raise typer.Exit(code=1)

    console.print(f"[bold green]✨ Successfully removed all AWS resources for '{clean_name}'![/bold green]")



# ---------------------------------------------------------------------------
# 7. DOCTOR (Health & System Diagnostics)
# ---------------------------------------------------------------------------
@app.command(name="doctor")
@app.command(name="doc", hidden=True)
def doctor(
    install: bool = typer.Option(
        False,
        "--install",
        "-i",
        help="Attempt auto-installing missing CLI tools (Homebrew, Docker/OrbStack, Trivy)",
    ),
) -> None:
    """🩺 Run diagnostic health check on local system, AI keys, Docker & AWS credentials."""
    import platform
    import shutil
    import subprocess
    import boto3

    _banner()
    console.print("[bold cyan]🩺 Running InfraGenie System Diagnostics...[/bold cyan]\n")

    table = Table(title="System & Cloud Health Check", show_lines=True)
    table.add_column("Component", style="cyan", no_wrap=True)
    table.add_column("Status", style="bold")
    table.add_column("Details & Action Items", style="dim")

    from infragenie.utils.os_helper import get_os_info, get_docker_install_guide, get_trivy_install_guide

    # 1. OS & Python Check
    os_name = get_os_info()
    py_ver = platform.python_version()
    table.add_row("Operating System", "[green]✅ Detected[/green]", f"{os_name}")
    table.add_row("Python Runtime", "[green]✅ Ready[/green]", f"Python {py_ver} ({sys.executable})")

    # 2. AI Provider Check
    try:
        from infragenie.llm import LLMFactory
        provider = LLMFactory.create()
        table.add_row(
            "AI LLM Provider",
            "[green]✅ Configured[/green]",
            f"Provider: {provider.provider_name} (Model: {provider.model_name})",
        )
    except Exception as e:
        table.add_row("AI LLM Provider", "[red]❌ Missing Key[/red]", f"Error: {e}")

    # 3. Docker Engine Check
    docker_bin = shutil.which("docker")
    docker_running = False
    if docker_bin:
        try:
            r = subprocess.run(["docker", "info"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=4)
            docker_running = (r.returncode == 0)
        except Exception:
            pass

    if docker_running:
        table.add_row("Docker Engine", "[green]✅ Active[/green]", f"Binary: {docker_bin} (Daemon responding)")
    elif docker_bin:
        table.add_row("Docker Engine", "[yellow]⚠️ Daemon Stopped[/yellow]", "Docker installed but daemon not running (Start Docker app)")
    else:
        table.add_row("Docker Engine", "[red]❌ Not Installed[/red]", f"Install: {get_docker_install_guide()}")

    # 4. Trivy Security Scanner Check
    trivy_bin = shutil.which("trivy")
    if trivy_bin:
        table.add_row("Trivy Scanner", "[green]✅ Installed[/green]", f"Binary: {trivy_bin}")
    else:
        table.add_row("Trivy Scanner", "[yellow]⚠️ Not Installed[/yellow]", f"Install: {get_trivy_install_guide()}")

    # 5. AWS Cloud Credentials Check
    try:
        sts = boto3.client("sts", region_name=settings.aws_region)
        ident = sts.get_caller_identity()
        table.add_row(
            "AWS Cloud Connection",
            "[green]✅ Connected[/green]",
            f"Account: {ident['Account']} (User: {ident['Arn'].split('/')[-1]}, Region: {settings.aws_region})",
        )
    except Exception as e:
        table.add_row(
            "AWS Cloud Connection",
            "[yellow]⚠️ Not Configured[/yellow]",
            f"AWS error: {e}. Set ~/.aws/credentials or AWS_PROFILE.",
        )

    console.print(table)
    console.print()
    if install:
        if not docker_running:
            from infragenie.utils.os_helper import install_docker_interactively
            install_docker_interactively(console=console)
        if not trivy_bin:
            from infragenie.utils.os_helper import install_trivy_interactively
            install_trivy_interactively(console=console)

if __name__ == "__main__":
    app()
