"""
Fabric Builder Module - Phase 4
Ingests BOM (Excel/CSV), builds an in-memory VXLAN spine-leaf fabric model,
generates NX-OS config, exports to YAML/NX-OS CLI, and provides
traffic simulation with failover capabilities.
"""
from .bom_parser import BomParser
from .fabric_model import FabricModel
from .config_engine import ConfigEngine
from .yaml_exporter import YamlExporter
from .nxos_exporter import NxosExporter
from .endpoint_model import EndpointStore, FabricEndpoint, ENDPOINT_TYPES
from .traffic_engine import TrafficEngine
from .failover_sim import FailoverSimulator

__all__ = [
    "BomParser",
    "FabricModel",
    "ConfigEngine",
    "YamlExporter",
    "NxosExporter",
    "EndpointStore",
    "FabricEndpoint",
    "ENDPOINT_TYPES",
    "TrafficEngine",
    "FailoverSimulator",
]
