"""
Vertical Registry — loads and serves all LockerSphere vertical configurations.
"""

from threading import Lock
from typing import Callable

from apps.verticals.base import VerticalConfig, VerticalType
from apps.verticals.hospital import build_hospital_config
from apps.verticals.bank import build_bank_config
from apps.verticals.insurance import build_insurance_config
from apps.verticals.content_creator import build_content_creator_config
from apps.verticals.general import build_general_config


_REGISTRY: dict[VerticalType, VerticalConfig] = {}
_REGISTRY_LOCK = Lock()
_LOADED = False

_BUILDERS: dict[VerticalType, Callable[[], VerticalConfig]] = {
    VerticalType.HOSPITAL: build_hospital_config,
    VerticalType.BANK: build_bank_config,
    VerticalType.INSURANCE: build_insurance_config,
    VerticalType.CONTENT_CREATOR: build_content_creator_config,
    VerticalType.GENERAL: build_general_config,
}


def _ensure_loaded():
    global _LOADED
    if _LOADED:
        return
    with _REGISTRY_LOCK:
        if _LOADED:
            return
        new_registry: dict[VerticalType, VerticalConfig] = {}
        for vertical_type, builder in _BUILDERS.items():
            new_registry[vertical_type] = builder()
        _REGISTRY.clear()
        _REGISTRY.update(new_registry)
        _LOADED = True


def get_vertical(vertical_type: VerticalType) -> VerticalConfig:
    _ensure_loaded()
    cfg = _REGISTRY.get(vertical_type)
    if cfg is None:
        raise KeyError(f"Unknown vertical: {vertical_type}")
    return cfg


def list_verticals() -> list[VerticalConfig]:
    _ensure_loaded()
    return list(_REGISTRY.values())


def list_vertical_types() -> list[str]:
    _ensure_loaded()
    return [v.value for v in _REGISTRY.keys()]
