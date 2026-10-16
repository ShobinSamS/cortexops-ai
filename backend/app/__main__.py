import asyncio
import os
import uvicorn

async def main():
    config = uvicorn.Config("app.main:app", host=os.getenv("API_HOST", "127.0.0.1"), port=int(os.getenv("API_PORT", "8000")), log_level="info")
    await uvicorn.Server(config).serve()

if __name__ == "__main__":
    asyncio.run(main())
