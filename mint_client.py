"""One authenticated asynchronous HTTP session per plugin instance."""
import asyncio
from urllib.parse import urlsplit
import aiohttp
from .service import Request


class MintAPIError(Exception):
    def __init__(self, status: int, detail: str = "", retry_after: str | None = None):
        super().__init__(f"MintAPI returned HTTP {status}")
        self.status, self.detail, self.retry_after = status, detail, retry_after


class MintClient:
    def __init__(self, base_url: str, token: str, timeout: int = 90, concurrency: int = 2):
        parsed = urlsplit(base_url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.query or parsed.fragment or parsed.username:
            raise ValueError("请在插件配置中填写有效的 MintAPI HTTP 地址。")
        if not token.strip():
            raise ValueError("请在插件配置中填写 MintAPI 接口密钥。")
        if not 1 <= timeout <= 300 or not 1 <= concurrency <= 10:
            raise ValueError("请求超时应为 1～300 秒，并发数应为 1～10。")
        self.base_url = base_url.strip().rstrip("/")
        self._session = aiohttp.ClientSession(headers={"access_token": token}, timeout=aiohttp.ClientTimeout(total=timeout))
        self._semaphore = asyncio.Semaphore(concurrency)

    async def request(self, request: Request) -> bytes | dict:
        params = {key: str(value).lower() if isinstance(value, bool) else value for key, value in request.params.items()}
        async with self._semaphore:
            async with self._session.request(request.method, self.base_url + request.path, params=params,
                                             json=request.body, allow_redirects=False) as response:
                # Cap attachments and errors independently; never send API URLs to a platform.
                limit = 20 * 1024 * 1024 if request.image and response.status == 200 else 64 * 1024
                data = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    data.extend(chunk)
                    if len(data) > limit:
                        raise MintAPIError(502, "Response too large")
                if response.status != 200:
                    raise MintAPIError(response.status, data.decode("utf-8", errors="replace"), response.headers.get("Retry-After"))
                if request.image:
                    if response.content_type != "image/png" or not data.startswith(b"\x89PNG\r\n\x1a\n"):
                        raise MintAPIError(502, "Invalid image response")
                    return bytes(data)
                import json
                try:
                    result = json.loads(data)
                except (ValueError, UnicodeDecodeError) as exc:
                    raise MintAPIError(502, "Invalid JSON response") from exc
                if not isinstance(result, dict):
                    raise MintAPIError(502, "Invalid JSON response")
                return result

    async def close(self):
        await self._session.close()
