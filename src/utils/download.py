import aiohttp
from typing import List, Any, Callable
import logging
import asyncio


logger = logging.getLogger(__name__)


async def get(url: str, session: aiohttp.ClientSession, json: bool, timeout=0, parser: None|Callable=None) -> Any:
    try:
        async with session.get(url=url, timeout=timeout) as response:
            if json:
                resp = await response.json(content_type=None)
            else:
                resp = await response.text()

            if not parser: return resp

            if (ret := parser(resp)) and ret:
                return ret
            else:
                raise ValueError("return data parsed failed")
    except ValueError as e:
        logger.error(f"fetch {url} with error: mismatch config schema")
    except Exception as e:
        logger.error(f"fetch {url} with error: network issue")
        raise e

async def parallel_download(urls: List[str], json=False, timeout=0, parser: None|Callable=None) -> Any:
    ''' Get first result from multiple URLs concurrently. '''
    try:
        ret = None
        async with aiohttp.ClientSession() as session:
            tasks = [asyncio.create_task(get(url, session, json, timeout, parser)) for url in urls]

            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            while len(pending) > 0:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    try:
                        ret = task.result()
                    except Exception as e:
                        continue

                if ret:
                    for task in pending:
                        task.cancel()
                    break

            return ret
    except Exception as e:
        raise e
