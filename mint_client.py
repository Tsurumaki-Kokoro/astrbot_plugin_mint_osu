"""One authenticated asynchronous HTTP session per plugin instance."""
import asyncio
from urllib.parse import urlsplit
import aiohttp
from .service import Request


class MintAPIError(Exception):
    def __init__(self, status: int, detail: str = "", retry_after: str | None = None):
        super().__init__(f"MintAPI returned HTTP {status}")
        self.status, self.detail, self.retry_after = status, detail, retry_after


class ImagePayload(bytes):
    def __new__(cls, data: bytes, headers: dict):
        instance = super().__new__(cls, data)
        instance.headers = headers
        return instance


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
                    detected = None
                    if data.startswith(b"\x89PNG\r\n\x1a\n"):
                        detected = "png"
                    elif data.startswith((b"GIF87a", b"GIF89a")):
                        detected = "gif"
                    elif data.startswith(b"\xff\xd8\xff"):
                        detected = "jpeg"
                    elif data.startswith(b"RIFF") and data[8:12] == b"WEBP":
                        detected = "webp"
                    if detected not in request.image_types or response.content_type not in {"image/" + kind for kind in request.image_types}:
                        raise MintAPIError(502, "Invalid image response")
                    headers = {key: response.headers[key] for key in ("X-Page", "X-Page-Count", "X-Total", "X-Next-Cursor") if key in response.headers}
                    return ImagePayload(bytes(data), headers)
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
