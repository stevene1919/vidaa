"""Mock stubs for third-party libraries (voluptuous, aiohttp) if not installed."""

from __future__ import annotations

import sys
import types

# Mock voluptuous if not installed
if "voluptuous" not in sys.modules:
    try:
        import voluptuous as vol
    except ImportError:
        vol = types.ModuleType("voluptuous")

        class Schema:
            def __init__(self, schema):
                self.schema = schema

            def __call__(self, val):
                return val

            def extend(self, schema):
                new_schema = dict(self.schema) if isinstance(self.schema, dict) else {}
                if isinstance(schema, dict):
                    new_schema.update(schema)
                return Schema(new_schema)

        class Invalid(Exception):
            pass

        class All:
            def __init__(self, *validators):
                self.validators = validators

            def __call__(self, val):
                return val

        def Required(key, default=None):
            return key

        def Optional(key, default=None):
            return key

        def In(container):
            return lambda x: x

        def Any(*validators):
            return validators[0] if validators else None

        class Coerce:
            def __init__(self, target):
                self.type = target

            def __call__(self, value):
                return self.type(value)

        vol.Schema = Schema
        vol.Invalid = Invalid
        vol.All = All
        vol.Required = Required
        vol.Optional = Optional
        vol.In = In
        vol.Any = Any
        vol.Coerce = Coerce
        sys.modules["voluptuous"] = vol

# Mock aiohttp if not installed
if "aiohttp" not in sys.modules:
    try:
        import aiohttp
    except ImportError:
        aiohttp = types.ModuleType("aiohttp")

        class ClientError(Exception):
            pass

        class ClientSession:
            def __init__(self, *args, **kwargs):
                self.closed = False

            async def close(self):
                self.closed = True

        class ClientTimeout:
            def __init__(self, total=None):
                self.total = total

        aiohttp.ClientError = ClientError
        aiohttp.ClientSession = ClientSession
        aiohttp.ClientTimeout = ClientTimeout
        sys.modules["aiohttp"] = aiohttp
