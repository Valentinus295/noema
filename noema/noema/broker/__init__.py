"""Broker package for Noema — abstract broker interface + implementations."""
from noema.broker.base import BrokerBase
from noema.broker.mt5 import MT5Broker
from noema.broker.mt5_linux import MT5LinuxBroker
from noema.broker.fbs import FBSBroker
from noema.broker.paper import PaperBroker
from noema.broker.gateway import (
    MultiBrokerGateway,
    BrokerHealth,
    BrokerStatus,
    BrokerTick,
    OrderRoutingPolicy,
)
from noema.broker.fix import (
    FIXSession,
    FIXSessionConfig,
    FIXMessage,
    NewOrderSingle,
    ExecutionReport,
    build_new_order_single,
    parse_execution_report,
    parse_fix_message,
)
from noema.broker.reconciliation import (
    PositionReconciler,
    PositionRecord,
    PositionDrift,
    ReconciliationResult,
    ReconciliationTolerances,
    DriftSeverity,
    DriftAction,
)

__all__ = [
    # Base
    "BrokerBase",
    # Implementations
    "MT5Broker",
    "MT5LinuxBroker",
    "FBSBroker",
    "PaperBroker",
    # Gateway
    "MultiBrokerGateway",
    "BrokerHealth",
    "BrokerStatus",
    "BrokerTick",
    "OrderRoutingPolicy",
    # FIX
    "FIXSession",
    "FIXSessionConfig",
    "FIXMessage",
    "NewOrderSingle",
    "ExecutionReport",
    "build_new_order_single",
    "parse_execution_report",
    "parse_fix_message",
    # Reconciliation
    "PositionReconciler",
    "PositionRecord",
    "PositionDrift",
    "ReconciliationResult",
    "ReconciliationTolerances",
    "DriftSeverity",
    "DriftAction",
]
