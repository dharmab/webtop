#!/usr/bin/env python3

from . import api, cli
import asyncio

__all__ = ["api", "cli"]

if __name__ == "__main__":
    asyncio.run(cli.main())
