"""Compatibility entrypoint for the Finance LangGraph agent."""

import asyncio

from app.agent.finance_graph import main


if __name__ == "__main__":
    asyncio.run(main())
