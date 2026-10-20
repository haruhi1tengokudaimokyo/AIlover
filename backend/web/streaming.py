"""Iterate legacy SSE generators incrementally under ASGI without buffering them."""
from asgiref.sync import sync_to_async
from django.db import close_old_connections


async def async_stream(iterator):
    end = object()
    try:
        while True:
            item = await sync_to_async(next, thread_sensitive=True)(iterator, end)
            if item is end:
                break
            yield item
    finally:
        await sync_to_async(iterator.close, thread_sensitive=True)()
        await sync_to_async(close_old_connections, thread_sensitive=True)()
