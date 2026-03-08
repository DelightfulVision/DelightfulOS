"""Runtime Layer — orchestrates the OS pipeline with manager-based composition.

Inspired by MentraOS's manager pattern: the Runtime owns specialized managers
(DeviceManager, PolicyManager, AIMediatorManager) that each handle a domain.

Signal flow:
  Device -> Bus -> SignalBatcher -> StateEstimator -> PolicyManager -> OutputRouter -> Device
                                                   +> AI Mediator (every 2s)       -> Device
"""

from delightfulos.runtime.managers import Runtime, runtime

__all__ = ["Runtime", "runtime"]
