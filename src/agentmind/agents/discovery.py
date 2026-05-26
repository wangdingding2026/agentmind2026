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
        id="ollama",
        name="Ollama",
        type="api",
        detect_commands=["ollama"],
        tags=["local-model", "general"],
        timeout=120,
        config={
            "endpoint": "http://localhost:11434/api/chat",
            "method": "POST",
            "body_template": {
                "model": "llama3",
                "messages": [{"role": "user", "content": "{instruction}"}],
                "stream": False,
            },
            "response_path": "message.content",
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


# 通用探测模式：依次尝试常见 CLI 调用约定
_PROBE_PATTERNS = [
    "-p {message}",
    "exec {message}",
    "agent --message {message} --local",
    "ask {message}",
    "{message}",
]
_PROBE_TIMEOUT = 5  # 每种模式超时秒数
_TEST_MESSAGE = "hello"
_BLOCKED_KEYWORDS = ["usage:", "error:", "not found", "command not found"]


async def _probe_unknown_executable(cmd: str) -> dict | None:
    """对未知命令行工具尝试常见调用模式，命中则返回配置"""
    if not shutil.which(cmd):
        return None

    # 0. 先验证 --version
    try:
        proc = await asyncio.create_subprocess_exec(
            cmd, "--version",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=_PROBE_TIMEOUT)
        if proc.returncode != 0:
            return None
    except Exception:
        return None

    # 1. 尝试通信模式
    for pattern in _PROBE_PATTERNS:
        cmd_str = pattern.replace("{message}", _TEST_MESSAGE)
        try:
            parts = shlex.split(cmd_str)
            proc = await asyncio.create_subprocess_exec(
                cmd, *parts,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_PROBE_TIMEOUT)
            except asyncio.TimeoutError:
                proc.kill(); await proc.wait()
                continue

            if proc.returncode != 0:
                continue

            output = stdout.decode("utf-8", errors="replace").strip()
            err_output = stderr.decode("utf-8", errors="replace").lower()
            if not output or len(output) < 2:
                continue
            # 排除帮助信息
            combined = (output + err_output).lower()
            if any(kw in combined for kw in _BLOCKED_KEYWORDS):
                continue

            # 命中！生成配置
            health_cmd = f"{cmd} --version"
            full_cmd = pattern.replace("{message}", "{instruction}")
            command = f"{cmd} {full_cmd}"
            return {
                "id": cmd,
                "name": cmd.title(),
                "type": "cli",
                "tags": ["auto"],
                "timeout": 120,
                "enabled": True,
                "auto_discovered": True,
                "config": {
                    "command": command,
                    "health_check": health_cmd,
                    "credibility": 0.3,
                },
            }
        except Exception:
            continue

    return None


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
    """双重策略扫描：KNOWN_AGENTS 优先，未知工具自动探测兜底"""
    discovered = []
    known_ids = {p.id for p in KNOWN_AGENTS}

    # 第 1 层：KNOWN_AGENTS 快路径
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

    # 第 2 层：通用探测未知工具（限制数量和总时长）
    import os as _os
    import time as _time

    # 读取已有 agents.yaml 的 ID，避免重复探测
    from agentmind.storage.db import CONFIG_DIR
    existing_ids = load_existing_agent_ids(CONFIG_DIR / "agents.yaml")
    all_known = known_ids | existing_ids

    probe_start = _time.time()
    PROBE_MAX_COUNT = 20   # 最多探测 20 个未知工具
    PROBE_MAX_SECS = 30    # 总探测时长上限 30 秒
    probe_count = 0
    path_dirs = _os.environ.get("PATH", "").split(_os.pathsep)
    scanned = set()
    for d in path_dirs:
        try:
            for f in _os.scandir(d):
                if f.is_file() and _os.access(f.path, _os.X_OK):
                    name = f.name
                    if name in all_known or name in scanned:
                        continue
                    if name.startswith(".") or name in ("agentmind",):
                        continue
                    scanned.add(name)
                    probe_count += 1
                    if probe_count > PROBE_MAX_COUNT or _time.time() - probe_start > PROBE_MAX_SECS:
                        break
                    config = await _probe_unknown_executable(name)
                    if config:
                        profile = AgentProfile(
                            id=config["id"], name=config["name"], type=config["type"],
                            detect_commands=[config["id"]], tags=config["tags"],
                            timeout=config["timeout"], config=config["config"],
                            auto_discovered=True,
                        )
                        discovered.append(profile)
                        logger.info("自动探测发现 Agent: %s", config["name"])
            if probe_count > PROBE_MAX_COUNT or _time.time() - probe_start > PROBE_MAX_SECS:
                break
        except PermissionError:
            continue

    if not discovered:
        logger.info("未发现健康可用的 Agent")

    return discovered


def profiles_to_yaml(profiles: list[AgentProfile]) -> str:
    """将发现的 AgentProfile 列表转为 agents.yaml 内容"""
    agents_data = {"agents": []}
    for p in profiles:
        agent = {
            "id": p.id,
            "name": p.name,
            "type": p.type,
            "tags": p.tags,
            "enabled": True,
            "timeout": p.timeout,
            "config": p.config,
        }
        if p.auto_discovered:
            agent["auto_discovered"] = True
        agents_data["agents"].append(agent)
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

    added = []
    for p in new_profiles:
        if p.id not in existing_ids:
            entry = {
                "id": p.id, "name": p.name, "type": p.type,
                "tags": p.tags, "enabled": True, "timeout": p.timeout,
                "config": p.config,
            }
            if p.auto_discovered:
                entry["auto_discovered"] = True
            existing_agents.append(entry)
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
