import frappe

__all__ = ["FrappeCacheStore"]


class FrappeCacheStore:
	"""A `KeyValueStore` over the site's Redis cache, which every worker of the site shares."""

	async def get(self, key: str) -> str | None:
		# `expires=True` skips the request-local copy `get_value` otherwise keeps, which
		# would hide a stop written by another worker after this request first looked.
		return frappe.cache.get_value(key, expires=True)

	async def set(self, key: str, value: str, *, ttl: int | None = None) -> None:
		frappe.cache.set_value(key, value, expires_in_sec=ttl)

	async def delete(self, key: str) -> None:
		frappe.cache.delete_value(key)
