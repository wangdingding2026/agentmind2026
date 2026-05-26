import asyncio
import logging

from agentmind.startup import AgentMindBootstrapper, async_main, find_available_port
from agentmind.storage.db import DATA_HOME

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("agentmind")


def create_app(port: int):
    return AgentMindBootstrapper(port=port, data_home=DATA_HOME).create_app()


def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(async_main())
    loop.close()


if __name__ == "__main__":
    main()
