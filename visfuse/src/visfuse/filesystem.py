"""fsspec filesystem that serves a directory of Measurement Sets as Zarr stores.

This wraps MSZarrStore into the fsspec interface, giving you:
- Programmatic access via fsspec's open/ls/cat API
- Optional FUSE mounting via fsspec.fuse.run()
- Compatibility with any tool that speaks fsspec (Zarr, xarray, Dask, etc.)
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import fsspec
from fsspec.spec import AbstractFileSystem

from visfuse.store import MSZarrStore


class MSFileSystem(AbstractFileSystem):
    """An fsspec filesystem that presents .ms directories as .zarr stores.

    Parameters
    ----------
    ms_root : str
        Directory containing one or more Measurement Sets (.ms directories).

    Example
    -------
    >>> fs = MSFileSystem("/data/observations")
    >>> fs.ls("/")
    ['observation1.zarr', 'observation2.zarr']
    >>> import xarray as xr
    >>> ds = xr.open_zarr(fs.get_mapper("observation1.zarr"))
    """

    protocol = "msfs"

    def __init__(self, ms_root: str, **kwargs):
        super().__init__(**kwargs)
        self.ms_root = str(Path(ms_root).resolve())
        self._stores: dict[str, MSZarrStore] = {}
        self._discover_ms()

    def _discover_ms(self):
        """Find all .ms directories under ms_root."""
        root = Path(self.ms_root)
        if not root.exists():
            return
        for entry in root.iterdir():
            if entry.is_dir() and entry.suffix == ".ms":
                zarr_name = entry.stem + ".zarr"
                self._stores[zarr_name] = MSZarrStore(str(entry))

    def _get_store_and_key(self, path: str) -> tuple[MSZarrStore | None, str]:
        """Split a path into (store, internal_key)."""
        path = self._strip_protocol(path).strip("/")
        if not path:
            return None, ""
        parts = path.split("/", 1)
        store_name = parts[0]
        key = parts[1] if len(parts) > 1 else ""
        store = self._stores.get(store_name)
        return store, key

    def ls(self, path: str, detail: bool = False, **kwargs):
        path = self._strip_protocol(path).strip("/")

        if not path:
            entries = []
            for name in sorted(self._stores):
                info = {"name": name, "type": "directory", "size": 0}
                entries.append(info if detail else info["name"])
            return entries

        store, key = self._get_store_and_key(path)
        if store is None:
            raise FileNotFoundError(path)

        loop = asyncio.new_event_loop()
        try:
            items = loop.run_until_complete(self._async_list_dir(store, key))
        finally:
            loop.close()

        entries = []
        for item in sorted(items):
            full = f"{path}/{item}" if path else item
            info = {"name": full, "type": "file", "size": 0}
            entries.append(info if detail else info["name"])
        return entries

    async def _async_list_dir(self, store: MSZarrStore, prefix: str) -> list[str]:
        return [item async for item in store.list_dir(prefix)]

    def _open(self, path, mode="rb", **kwargs):
        if "w" in mode or "a" in mode:
            raise PermissionError("MSFileSystem is read-only")

        store, key = self._get_store_and_key(path)
        if store is None:
            raise FileNotFoundError(path)

        loop = asyncio.new_event_loop()
        try:
            buf = loop.run_until_complete(store.get(key))
        finally:
            loop.close()

        if buf is None:
            raise FileNotFoundError(path)

        import io
        return io.BytesIO(bytes(buf))

    def info(self, path, **kwargs):
        path = self._strip_protocol(path).strip("/")
        if not path:
            return {"name": "", "type": "directory", "size": 0}

        store, key = self._get_store_and_key(path)
        if store is None:
            raise FileNotFoundError(path)

        if not key:
            return {"name": path, "type": "directory", "size": 0}

        loop = asyncio.new_event_loop()
        try:
            exists = loop.run_until_complete(store.exists(key))
        finally:
            loop.close()

        if exists:
            return {"name": path, "type": "file", "size": 0}

        raise FileNotFoundError(path)
