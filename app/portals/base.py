"""PortalAdapter ABC and registry."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from decimal import Decimal
from typing import Any, ClassVar

from app.mfa.bridge import MfaBridge
from app.models import PortalResult, Scenario
from app.secrets.store import Credentials


class AdapterNotFound(KeyError):
    pass


class PortalAdapter(ABC):
    LENDER: ClassVar[str]
    LOGIN_URL: ClassVar[str]

    @abstractmethod
    async def ensure_logged_in(
        self,
        page: Any,
        creds: Credentials | None,
        mfa_bridge: MfaBridge,
        session_id: str,
    ) -> None: ...

    @abstractmethod
    async def fill_scenario(self, page: Any, scenario: Scenario) -> None: ...

    @abstractmethod
    async def submit(self, page: Any) -> None: ...

    @abstractmethod
    async def parse_result(self, page: Any, target_rate: Decimal) -> PortalResult: ...


_REGISTRY: dict[str, type[PortalAdapter]] = {}


def register_adapter(
    lender: str,
) -> Callable[[type[PortalAdapter]], type[PortalAdapter]]:
    def deco(cls: type[PortalAdapter]) -> type[PortalAdapter]:
        _REGISTRY[lender] = cls
        return cls

    return deco


def get_adapter(lender: str) -> PortalAdapter:
    cls = _REGISTRY.get(lender)
    if cls is None:
        raise AdapterNotFound(f"No adapter registered for '{lender}'")
    return cls()
