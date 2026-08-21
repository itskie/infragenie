"""
OS-aware package manager and installation suggestion helper.
Dynamically tailors installation commands for macOS (Darwin), Ubuntu/Debian, Fedora/RHEL, Arch, Alpine, and Windows.
"""
from __future__ import annotations

import platform
import shutil
from pathlib import Path


def get_os_info() -> str:
    """Return human-readable OS name (e.g. macOS Sonoma, Ubuntu 24.04, Fedora 40)."""
    sys_name = platform.system()
    if sys_name == "Darwin":
        ver = platform.mac_ver()[0]
        return f"macOS {ver}" if ver else "macOS"
    elif sys_name == "Linux":
        os_release = Path("/etc/os-release")
        if os_release.exists():
            for line in os_release.read_text().splitlines():
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip('"')
        return "Linux"
    elif sys_name == "Windows":
        return f"Windows {platform.release()}"
    return sys_name


def get_docker_install_guide() -> str:
    """Return OS-specific command to install and start Docker."""
    sys_name = platform.system()
    if sys_name == "Darwin":
        return "brew install --cask docker"
    elif sys_name == "Linux":
        os_release = Path("/etc/os-release")
        if os_release.exists():
            content = os_release.read_text().lower()
            if "ubuntu" in content or "debian" in content:
                return "sudo apt update && sudo apt install -y docker.io && sudo systemctl start docker"
            elif "fedora" in content or "rhel" in content or "centos" in content:
                return "sudo dnf install -y docker && sudo systemctl start docker"
            elif "arch" in content:
                return "sudo pacman -S --noconfirm docker && sudo systemctl start docker"
            elif "alpine" in content:
                return "apk add docker && rc-service docker start"
        return "curl -fsSL https://get.docker.com | sh && sudo systemctl start docker"
    elif sys_name == "Windows":
        return "Install Docker Desktop for Windows (https://docs.docker.com/desktop/setup/install/windows-install/)"
    return "Visit https://docs.docker.com/engine/install/"


def get_trivy_install_guide() -> str:
    """Return OS-specific command to install Trivy security scanner."""
    sys_name = platform.system()
    if sys_name == "Darwin":
        return "brew install trivy"
    elif sys_name == "Linux":
        os_release = Path("/etc/os-release")
        if os_release.exists():
            content = os_release.read_text().lower()
            if "ubuntu" in content or "debian" in content:
                return "sudo apt install trivy (or https://aquasecurity.github.io/trivy)"
            elif "fedora" in content or "rhel" in content or "centos" in content:
                return "sudo dnf install trivy"
            elif "arch" in content:
                return "sudo pacman -S trivy"
        return "curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sh"
    elif sys_name == "Windows":
        return "choco install trivy (or scoop install trivy)"
    return "Visit https://aquasecurity.github.io/trivy/"

def get_docker_install_command_list() -> list[str]:
    """Return OS-specific command as a list of shell commands to execute."""
    sys_name = platform.system()
    if sys_name == "Darwin":
        if shutil.which("brew"):
            return ["brew", "install", "--cask", "orbstack"]
        return ["curl", "-fsSL", "https://orbstack.dev/download/mac/latest", "-o", "/tmp/orbstack.dmg"]
    elif sys_name == "Linux":
        os_release = Path("/etc/os-release")
        if os_release.exists():
            content = os_release.read_text().lower()
            if "ubuntu" in content or "debian" in content:
                return ["sudo", "apt", "update", "&&", "sudo", "apt", "install", "-y", "docker.io", "&&", "sudo", "systemctl", "enable", "--now", "docker"]
            elif "fedora" in content or "rhel" in content or "centos" in content:
                return ["sudo", "dnf", "install", "-y", "docker", "&&", "sudo", "systemctl", "enable", "--now", "docker"]
            elif "arch" in content:
                return ["sudo", "pacman", "-S", "--noconfirm", "docker", "&&", "sudo", "systemctl", "enable", "--now", "docker"]
            elif "alpine" in content:
                return ["apk", "add", "docker", "&&", "rc-service", "docker", "start"]
        return ["curl", "-fsSL", "https://get.docker.com", "|", "sh"]
    return []


def install_docker_interactively(console=None) -> bool:
    """
    Prompt user and run cross-platform Docker installation.
    Returns True if successfully installed, False otherwise.
    """
    import subprocess
    import shutil
    import typer

    sys_name = platform.system()
    guide = get_docker_install_guide()

    if console:
        console.print(f"\n[bold yellow]⚠️ Docker Engine is not installed or not running on your {get_os_info()} system.[/bold yellow]")
        console.print(f"[dim]Recommended: {guide}[/dim]\n")

    confirm = typer.confirm("🤖 Would you like InfraGenie to attempt installing Docker automatically?", default=False)
    if not confirm:
        return False

    if console:
        console.print("[bold cyan]🚀 Starting automated Docker installation...[/bold cyan]")

    try:
        if sys_name == "Darwin":
            if shutil.which("brew"):
                cmd = ["brew", "install", "--cask", "docker"]
                subprocess.run(cmd, check=True)
                subprocess.run(["open", "-a", "Docker"], check=False)
                if console:
                    console.print("[dim]Waiting 10s for Docker daemon to initialize...[/dim]")
                import time
                for _ in range(15):
                    time.sleep(2)
                    r = subprocess.run(["docker", "info"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    if r.returncode == 0:
                        return True
                return True
            else:
                if console:
                    console.print("[red]Homebrew not found. Please install Homebrew or Docker Desktop manually.[/red]")
                return False
        elif sys_name == "Linux":
            os_release = Path("/etc/os-release")
            if os_release.exists():
                txt = os_release.read_text().lower()
                if "ubuntu" in txt or "debian" in txt:
                    subprocess.run(["sudo", "apt", "update"], check=True)
                    subprocess.run(["sudo", "apt", "install", "-y", "docker.io"], check=True)
                    subprocess.run(["sudo", "systemctl", "enable", "--now", "docker"], check=False)
                    return True
                elif "fedora" in txt or "rhel" in txt or "centos" in txt:
                    subprocess.run(["sudo", "dnf", "install", "-y", "docker"], check=True)
                    subprocess.run(["sudo", "systemctl", "enable", "--now", "docker"], check=False)
                    return True
                elif "arch" in txt:
                    subprocess.run(["sudo", "pacman", "-S", "--noconfirm", "docker"], check=True)
                    subprocess.run(["sudo", "systemctl", "enable", "--now", "docker"], check=False)
                    return True
            # Fallback to get.docker.com script
            subprocess.run("curl -fsSL https://get.docker.com | sh", shell=True, check=True)
            subprocess.run(["sudo", "systemctl", "enable", "--now", "docker"], check=False)
            return True
        elif sys_name == "Windows":
            if console:
                console.print("[yellow]On Windows, please install Docker Desktop from https://docker.com/products/docker-desktop[/yellow]")
            return False
    except Exception as e:
        if console:
            console.print(f"[red]Installation encountered an error: {e}[/red]")
        return False

    return False


def install_trivy_interactively(console=None) -> bool:
    """
    Prompt user and run cross-platform Trivy security scanner installation.
    Returns True if successfully installed, False otherwise.
    """
    import subprocess
    import shutil
    import typer

    sys_name = platform.system()
    guide = get_trivy_install_guide()

    if console:
        console.print(f"\n[bold yellow]⚠️ Trivy Security Scanner is not installed on your {get_os_info()} system.[/bold yellow]")
        console.print(f"[dim]Recommended: {guide}[/dim]\n")

    confirm = typer.confirm("🤖 Would you like InfraGenie to attempt installing Trivy automatically?", default=False)
    if not confirm:
        return False

    if console:
        console.print("[bold cyan]🚀 Starting automated Trivy installation...[/bold cyan]")

    try:
        if sys_name == "Darwin":
            if shutil.which("brew"):
                subprocess.run(["brew", "install", "trivy"], check=True)
                return True
            else:
                if console:
                    console.print("[red]Homebrew not found. Please install Homebrew or Trivy manually.[/red]")
                return False
        elif sys_name == "Linux":
            os_release = Path("/etc/os-release")
            if os_release.exists():
                txt = os_release.read_text().lower()
                if "ubuntu" in txt or "debian" in txt:
                    cmd = "sudo apt update && sudo apt install -y wget apt-transport-https gnupg && wget -qO - https://aquasecurity.github.io/trivy-repo/deb/public.key | gpg --dearmor | sudo tee /usr/share/keyrings/trivy.gpg > /dev/null && echo 'deb [signed-by=/usr/share/keyrings/trivy.gpg] https://aquasecurity.github.io/trivy-repo/deb generic main' | sudo tee -a /etc/apt/sources.list.d/trivy.list && sudo apt update && sudo apt install -y trivy"
                    subprocess.run(cmd, shell=True, check=True)
                    return True
                elif "fedora" in txt or "rhel" in txt or "centos" in txt:
                    subprocess.run(["sudo", "dnf", "install", "-y", "trivy"], check=True)
                    return True
                elif "arch" in txt:
                    subprocess.run(["sudo", "pacman", "-S", "--noconfirm", "trivy"], check=True)
                    return True
            # Fallback script
            subprocess.run("curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sh -s -- -b /usr/local/bin", shell=True, check=True)
            return True
        elif sys_name == "Windows":
            if shutil.which("choco"):
                subprocess.run(["choco", "install", "-y", "trivy"], check=True)
                return True
            if console:
                console.print("[yellow]On Windows, please install Trivy from https://aquasecurity.github.io/trivy/[/yellow]")
            return False
    except Exception as e:
        if console:
            console.print(f"[red]Installation encountered an error: {e}[/red]")
        return False

    return False
