"""Custom Zarr v3 store backed by xarray-ms / arcae.

Maps Zarr chunk reads to lazy xarray-ms reads of a Casacore Measurement Set,
so the MS appears as a Zarr store without copying data.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

import numpy as np
import xarray as xr
from zarr.abc.store import Store
from zarr.core.buffer import Buffer, BufferPrototype


def _datatree_from_ms(ms_path: str) -> xr.DataTree:
    """Open an MS as an MSv4 DataTree via xarray-ms."""
    return xr.open_datatree(ms_path, engine="xarray-ms")


def _encode_zarray(var: xr.Variable) -> bytes:
    """Build a .zarray JSON blob from an xarray Variable."""
    dtype = var.dtype
    meta = {
        "zarr_format": 3,
        "node_type": "array",
        "shape": list(var.shape),
        "data_type": dtype.str,
        "chunk_grid": {
            "name": "regular",
            "configuration": {"chunk_shape": list(var.shape)},
        },
        "chunk_key_encoding": {
            "name": "default",
            "separator": ".",
        },
        "fill_value": None,
        "codecs": [{"name": "bytes", "configuration": {"endian": "little"}}],
    }
    return json.dumps(meta, indent=2).encode()


def _encode_zattrs(attrs: dict) -> bytes:
    """Serialize xarray attributes to .zattrs JSON."""
    safe = {}
    for k, v in attrs.items():
        try:
            json.dumps(v)
            safe[k] = v
        except (TypeError, ValueError):
            safe[k] = str(v)
    return json.dumps(safe, indent=2).encode()


def _encode_chunk(var: xr.Variable) -> bytes:
    """Materialize an xarray Variable to raw bytes (a single Zarr chunk)."""
    data = var.values
    if not data.dtype.isnative:
        data = data.astype(data.dtype.newbyteorder("="))
    return data.tobytes()


class MSZarrStore(Store):
    """A read-only Zarr v3 store that serves data from a Casacore MS.

    Usage::

        store = MSZarrStore("observation.ms")
        ds = xr.open_zarr(store)
    """

    def __init__(self, ms_path: str, *, read_only: bool = True):
        super().__init__(read_only=read_only)
        self.ms_path = ms_path
        self._tree: xr.DataTree | None = None

    @property
    def tree(self) -> xr.DataTree:
        if self._tree is None:
            self._tree = _datatree_from_ms(self.ms_path)
        return self._tree

    def _resolve(self, key: str) -> tuple[bytes | None, bool]:
        """Resolve a Zarr key to bytes content.

        Returns (content_bytes, found).
        """
        parts = key.strip("/").split("/")

        if key == "zarr.json" or key == ".zgroup":
            meta = {"zarr_format": 3, "node_type": "group"}
            return json.dumps(meta).encode(), True

        node = self.tree
        remaining = list(parts)
        while remaining:
            name = remaining[0]
            if name in ("zarr.json", ".zarray", ".zattrs", ".zgroup"):
                break
            children = {child.name: child for child in node.children.values()}
            if name in children:
                node = children[name]
                remaining.pop(0)
            elif hasattr(node, "ds") and node.ds is not None and name in node.ds:
                var = node.ds[name]
                remaining.pop(0)
                leaf = remaining[0] if remaining else None
                if leaf == "zarr.json" or leaf == ".zarray":
                    return _encode_zarray(var), True
                elif leaf == ".zattrs":
                    return _encode_zattrs(var.attrs), True
                elif leaf is None or leaf == "0":
                    return _encode_chunk(var), True
                else:
                    return None, False
            else:
                return None, False

        leaf = remaining[0] if remaining else None
        if leaf == "zarr.json" or leaf == ".zgroup":
            meta = {"zarr_format": 3, "node_type": "group"}
            return json.dumps(meta).encode(), True
        if leaf == ".zattrs":
            attrs = node.ds.attrs if hasattr(node, "ds") and node.ds is not None else {}
            return _encode_zattrs(dict(attrs)), True

        return None, False

    async def get(
        self,
        key: str,
        prototype: BufferPrototype | None = None,
        byte_range: tuple[int, int | None] | None = None,
    ) -> Buffer | None:
        content, found = self._resolve(key)
        if not found or content is None:
            return None
        if byte_range is not None:
            start, end = byte_range
            content = content[start:end]
        if prototype is not None:
            return prototype.buffer.from_bytes(content)
        return Buffer.from_bytes(content)

    async def set(self, key: str, value: Buffer) -> None:
        raise ReadOnlyError()

    async def delete(self, key: str) -> None:
        raise ReadOnlyError()

    async def exists(self, key: str) -> bool:
        _, found = self._resolve(key)
        return found

    def __eq__(self, other: object) -> bool:
        return isinstance(other, MSZarrStore) and other.ms_path == self.ms_path

    def __repr__(self) -> str:
        return f"MSZarrStore({self.ms_path!r})"

    @property
    def supports_writes(self) -> bool:
        return False

    @property
    def supports_deletes(self) -> bool:
        return False

    @property
    def supports_partial_writes(self) -> bool:
        return False

    @property
    def supports_listing(self) -> bool:
        return True

    async def list(self) -> AsyncGenerator[str, None]:
        yield "zarr.json"
        for name in self._list_node(self.tree, ""):
            yield name

    async def list_prefix(self, prefix: str) -> AsyncGenerator[str, None]:
        async for key in self.list():
            if key.startswith(prefix):
                yield key

    async def list_dir(self, prefix: str) -> AsyncGenerator[str, None]:
        prefix = prefix.strip("/")
        seen: set[str] = set()
        async for key in self.list():
            if not key.startswith(prefix + "/") and prefix:
                continue
            rest = key[len(prefix):].strip("/") if prefix else key.strip("/")
            top = rest.split("/")[0]
            if top and top not in seen:
                seen.add(top)
                yield top

    def _list_node(self, node: xr.DataTree, prefix: str) -> list[str]:
        entries = []
        p = f"{prefix}/" if prefix else ""

        entries.append(f"{p}zarr.json")
        entries.append(f"{p}.zattrs")

        if hasattr(node, "ds") and node.ds is not None:
            for var_name in node.ds:
                vp = f"{p}{var_name}"
                entries.append(f"{vp}/.zarray")
                entries.append(f"{vp}/.zattrs")
                entries.append(f"{vp}/0")

        for child in node.children.values():
            entries.extend(self._list_node(child, f"{p}{child.name}"))

        return entries


class ReadOnlyError(Exception):
    pass
