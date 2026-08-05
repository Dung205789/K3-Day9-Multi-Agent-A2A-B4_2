from .base import Agent
from .coordinator import CoordinatorAgent
from .delivery import DeliveryAgent
from .order_seller import OrderSellerAgent
from .payment import PaymentAgent
from .policy_agent import PolicyAgent
from .verifier import VerifierAgent

AGENT_REGISTRY = {
    "coordinator": CoordinatorAgent,
    "order_seller": OrderSellerAgent,
    "payment": PaymentAgent,
    "delivery": DeliveryAgent,
    "policy": PolicyAgent,
    "verifier": VerifierAgent,
}

AGENT_ROLES = {
    "coordinator": CoordinatorAgent.role,
    "order_seller": OrderSellerAgent.role,
    "payment": PaymentAgent.role,
    "delivery": DeliveryAgent.role,
    "policy": PolicyAgent.role,
    "verifier": VerifierAgent.role,
}

__all__ = [
    "Agent", "CoordinatorAgent", "DeliveryAgent", "OrderSellerAgent",
    "PaymentAgent", "PolicyAgent", "VerifierAgent",
    "AGENT_REGISTRY", "AGENT_ROLES",
]
