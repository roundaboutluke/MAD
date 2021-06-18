import asyncio
import json
from typing import Optional, Mapping, Dict

import aiohttp
from aiohttp import ClientConnectionError, ClientError
from aiohttp.typedefs import LooseHeaders
from loguru import logger


class RestApiResult:
    def __init__(self):
        self.status_code: int = 0
        self.result_body: Optional[Dict] = None


class RestHelper:
    @staticmethod
    async def send_get(url: str, headers: Optional[LooseHeaders],
                       params: Optional[Mapping[str, str]],
                       timeout: int = 10) -> RestApiResult:
        result: RestApiResult = RestApiResult()
        timeout = aiohttp.ClientTimeout(total=timeout)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers, params=params) as resp:
                    result.status_code = resp.status
                    try:
                        result.result_body = json.loads(await resp.text())
                        logger.success("Successfully got data from our request to {}: {}", url, result)
                    except Exception as e:
                        logger.warning("Failed converting response of request to '{}' with raw result '{}' to json: {}",
                                       url, result.result_body, e)
        except (ClientConnectionError, asyncio.exceptions.TimeoutError) as e:
            logger.warning("Connecting to {} failed: {}", url, str(e))
        except ClientError as e:
            logger.warning("Request to {} failed: {}", url, e)
        return result

    @staticmethod
    async def send_post(url: str, data: dict,
                        headers: Optional[LooseHeaders], params: Optional[Mapping[str, str]],
                        timeout: int = 10) -> RestApiResult:
        result: RestApiResult = RestApiResult()
        timeout = aiohttp.ClientTimeout(total=timeout)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=data, headers=headers, params=params) as resp:
                    result.status_code = resp.status
                    try:
                        result.result_body = json.loads(await resp.text())
                        logger.success("Successfully got data from our request to {}: {}", url, result)
                    except Exception as e:
                        logger.warning("Failed converting response of request to '{}' with raw result '{}' to json: {}",
                                       url, result.result_body, e)
        except ClientConnectionError as e:
            logger.warning("Connecting to {} failed: ", url, e)
        except ClientError as e:
            logger.warning("Request to {} failed: ", url, e)
        return result
