from typing import Protocol, runtime_checkable

__all__ = ["KeyValueStore"]


@runtime_checkable
class KeyValueStore(Protocol):
	"""Where state that another worker must read is written, such as a stop.

	A missing key reads as `None`. An implementation may expire a key early or lose
	everything on restart, so a reader treats absence as the safe default.
	"""

	async def get(self, key: str) -> str | None: ...

	async def set(self, key: str, value: str, *, ttl: int | None = None) -> None: ...

	async def delete(self, key: str) -> None: ...
