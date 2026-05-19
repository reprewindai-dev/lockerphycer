"""
Vertical Registry — loads and serves all LockerSphere vertical configurations.
"""

from apps.verticals.base import VerticalConfig, VerticalType
from apps.verticals.hospital import build_hospital_config
from apps.verticals.bank import build_bank_config
from apps.verticals.insurance import build_insurance_config
from apps.verticals.content_creator import build_content_creator_config
from apps.verticals.general import build_general_config


_REGISTRY: dict[VerticalType, VerticalConfig] = {}


def _ensure_loaded():
    if _REGISTRY:
        return
    for builder in (
        build_hospital_config,
        build_bank_config,
        build_insurance_config,
        build_content_creator_config,
        build_general_config,
    ):
        cfg = builder()
        _REGISTRY[cfg.vertical_type] = cfg


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
