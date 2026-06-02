import asyncio
import shlex
import shutil
import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger("agentmind")


@dataclass
class AgentProfile:
    """已知 Agent 的特征描述，用于自动发现"""

    id: str
    name: str
    type: str  # cli / api / mcp / a2a
    detect_commands: list[str]  # 用于检测是否安装的命令，如 ["claude", "claude --version"]
    tags: list[str] = field(default_factory=list)
    timeout: int = 120
    config: dict = field(default_factory=dict)
    auto_discovered: bool = False  # 自动探测发现的标记


# 已知 Agent 特征库：常见 AI Agent 工具的检测信息
# 新 Agent 不断涌现，只需在此追加即可
KNOWN_AGENTS: list[AgentProfile] = [
    AgentProfile(
        id="claude_code",
        name="Claude Code",
        type="cli",
        detect_commands=["claude"],
        tags=["code", "analysis", "refactor"],
        timeout=120,
        config={
            "command": "claude -p '{instruction}'",
            "health_check": "claude --version",
            "credibility": 0.8,
        },
    ),
    AgentProfile(
        id="hermes",
        name="Hermes",
        type="cli",
        detect_commands=["hermes"],
        tags=["general", "search", "writing"],
        timeout=120,
        config={
            "command": "hermes -z '{instruction}'",
            "health_check": "hermes --version",
            "credibility": 0.8,
        },
    ),
    AgentProfile(
        id="codex",
        name="Codex CLI",
        type="cli",
        detect_commands=["codex"],
        tags=["code", "completion"],
        timeout=120,
        config={
            "command": "codex exec --skip-git-repo-check '{instruction}'",
            "health_check": "codex --version",
            "credibility": 0.8,
        },
    ),
    AgentProfile(
        id="aider",
        name="Aider",
        type="cli",
        detect_commands=["aider"],
        tags=["code", "pair-programming"],
        timeout=120,
        config={
            "command": "aider --message '{instruction}'",
            "health_check": "aider --version",
            "credibility": 0.7,
        },
    ),
    AgentProfile(
        id="cursor_agent",
        name="Cursor Agent",
        type="cli",
        detect_commands=["cursor"],
        tags=["code", "ide"],
        timeout=120,
        config={
            "command": "cursor --prompt '{instruction}'",
            "health_check": "cursor --version",
            "credibility": 0.7,
        },
    ),
    AgentProfile(
        id="warp_agent",
        name="Warp AI",
        type="cli",
        detect_commands=["warp"],
        tags=["terminal", "general"],
        timeout=120,
        config={
            "command": "warp ask '{instruction}'",
            "health_check": "warp --version",
            "credibility": 0.6,
        },
    ),
    AgentProfile(
        id="openclaw",
        name="OpenClaw",
        type="cli",
        detect_commands=["openclaw"],
        tags=["general", "agent"],
        timeout=120,
        config={
            "command": "openclaw agent --message '{instruction}' --local --agent main --json",
            "health_check": "openclaw --version",
            "response_path": "payloads.0.text",
            "credibility": 0.7,
        },
    ),
]


async def _check_command_healthy(profile: AgentProfile) -> tuple[bool, str]:
    """使用 profile 的 health_check 配置检测 Agent 是否健康可用"""
    health_check = profile.config.get("health_check", "")
    if not health_check:
        # 无 health_check 时，回退到检测 detect_commands 首命令是否存在
        for cmd in profile.detect_commands:
            base_cmd = cmd.split()[0]
            if shutil.which(base_cmd):
                return True, "installed"
        return False, "not_found"

    try:
        parts = shlex.split(health_check)
    except Exception:
        return False, "invalid_health_check"

    if not parts:
        return False, "invalid_health_check"

    base_cmd = parts[0]
    if shutil.which(base_cmd) is None:
        return False, "not_found"

    try:
        process = await asyncio.create_subprocess_exec(
            *parts,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return False, "health_check_timeout"

        if process.returncode == 0:
            return True, "healthy"
        else:
            stderr_text = stderr.decode("utf-8", errors="replace")[:200] if stderr else ""
            logger.info("Agent %s health_check 返回非零退出码 %d: %s",
                        profile.id, process.returncode, stderr_text)
            return False, "health_check_failed"
    except Exception as e:
        logger.info("Agent %s health_check 异常: %s", profile.id, e)
        return False, "health_check_error"


async def scan_installed_agents() -> list[AgentProfile]:
    """扫描显式支持的 Agent，避免启动时执行任意本地程序。"""
    discovered = []

    check_tasks = [(p, _check_command_healthy(p)) for p in KNOWN_AGENTS]
    results = await asyncio.gather(*[t for _, t in check_tasks], return_exceptions=True)

    for (profile, _), result in zip(check_tasks, results):
        if isinstance(result, Exception):
            logger.warning("Agent %s 健康检测异常: %s", profile.id, result)
            continue
        is_healthy, status = result
        if is_healthy:
            discovered.append(profile)
            logger.info("发现已安装且健康的 Agent: %s (%s) status=%s", profile.name, profile.type, status)
        elif status != "not_found":
            logger.info("Agent %s 已安装但不健康: %s (%s) status=%s", profile.id, profile.name, profile.type, status)

    if not discovered:
        logger.info("未发现健康可用的 Agent")

    return discovered


def profile_to_agent_config(profile: AgentProfile) -> dict:
    """将发现结果转换为 AgentRegistry 可加载的持久化配置。"""
    agent = {
        "id": profile.id,
        "name": profile.name,
        "type": profile.type,
        "tags": profile.tags,
        "enabled": True,
        "timeout": profile.timeout,
        "config": profile.config,
    }
    if profile.auto_discovered:
        agent["auto_discovered"] = True
    return agent


def profiles_to_yaml(profiles: list[AgentProfile]) -> str:
    """将发现的 AgentProfile 列表转为 agents.yaml 内容"""
    agents_data = {"agents": [profile_to_agent_config(profile) for profile in profiles]}
    return yaml.dump(agents_data, allow_unicode=True, default_flow_style=False, sort_keys=False)


def load_existing_agent_ids(config_path: Path) -> set[str]:
    """读取已有配置中的 agent id，避免重复添加"""
    if not config_path.exists():
        return set()
    try:
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        logger.warning("agents.yaml 解析失败: %s，将视为空配置", e)
        return set()
    if not isinstance(data, dict):
        logger.warning("agents.yaml 顶层结构异常（非 dict），将视为空配置")
        return set()
    agents_list = data.get("agents", [])
    if not isinstance(agents_list, list):
        logger.warning("agents.yaml 的 agents 字段不是列表，将视为空配置")
        return set()
    ids = set()
    for i, a in enumerate(agents_list):
        if isinstance(a, dict) and "id" in a:
            ids.add(a["id"])
        else:
            logger.warning("跳过 agents.yaml 中第 %d 个无效条目", i + 1)
    return ids


def merge_discovered_agents(config_path: Path, new_profiles: list[AgentProfile]):
    """将新发现的 Agent 合并到已有配置中（不覆盖已有条目）"""
    existing_ids = load_existing_agent_ids(config_path)

    existing_agents = []
    if config_path.exists():
        try:
            with open(config_path) as f:
                data = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            logger.warning("agents.yaml 解析失败: %s，将重新生成", e)
            data = {}
        if not isinstance(data, dict):
            logger.warning("agents.yaml 顶层结构异常，将重新生成")
            data = {}
        existing_agents = data.get("agents", [])
        if not isinstance(existing_agents, list):
            logger.warning("agents.yaml 的 agents 字段不是列表，将重新生成")
            existing_agents = []
        # 过滤掉非 dict 条目
        existing_agents = [a for a in existing_agents if isinstance(a, dict)]
        existing_ids = {
            str(a.get("id"))
            for a in existing_agents
            if isinstance(a, dict) and a.get("id")
        }

    added = []
    for p in new_profiles:
        if p.id not in existing_ids:
            existing_agents.append(profile_to_agent_config(p))
            added.append(p.name)

    with open(config_path, "w") as f:
        yaml.dump({"agents": existing_agents}, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    if added:
        logger.info("新增 Agent: %s", ", ".join(added))
    else:
        logger.info("未发现新的 Agent")

    return added


async def discover_and_generate(config_path: Path):
    """扫描已安装 Agent 并生成/合并配置文件"""
    profiles = await scan_installed_agents()
    if not config_path.exists():
        # 首次：直接生成
        yaml_content = profiles_to_yaml(profiles)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(yaml_content, encoding="utf-8")
        logger.info("已生成 agents.yaml，发现 %d 个 Agent", len(profiles))
    else:
        # 非首次：合并
        merge_discovered_agents(config_path, profiles)
