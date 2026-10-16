"""CortexOps application."""
import asyncio
import sys

# psycopg's async adapter requires selector-based loops on Windows/Python 3.12.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
