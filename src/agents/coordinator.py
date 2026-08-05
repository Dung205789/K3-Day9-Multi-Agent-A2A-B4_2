import datetime
import json
from typing import Dict, Any, List
from src.utils.data_loader import DataLoader
from src.utils.llm_client import LLMClient
from src.agents.order_seller_agent import OrderSellerAgent
from src.agents.payment_agent import PaymentAgent
from src.agents.delivery_agent import DeliveryAgent
from src.agents.policy_agent import PolicyAgent
from src.agents.verifier_agent import VerifierAgent

class CoordinatorAgent:
    def __init__(self, data_loader: DataLoader, llm_client: LLMClient):
        self.agent_name = "CoordinatorAgent"
        self.order_seller_agent = OrderSellerAgent(data_loader)
        self.payment_agent = PaymentAgent(data_loader)
        self.delivery_agent = DeliveryAgent()
        self.policy_agent = PolicyAgent()
        self.verifier_agent = VerifierAgent(llm_client)
        self.trace_logs: List[dict] = []

    def _log_trace(self, case_id: str, agent: str, action: str, details: Dict[str, Any] = None):
        log_entry = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "case_id": case_id,
            "agent": agent,
            "action": action,
            "details": details or {}
        }
        self.trace_logs.append(log_entry)

    def process_case(self, case_input: Dict[str, Any]) -> Dict[str, Any]:
        case_id = case_input.get("case_id")
        claimed_order_id = case_input.get("customer_request", {}).get("claimed_order_id")

        self._log_trace(case_id, self.agent_name, "receive_case", {"claimed_order_id": claimed_order_id})

        # 1. Handoff to OrderSellerAgent
        order_info = self.order_seller_agent.analyze(claimed_order_id)
        self._log_trace(case_id, self.order_seller_agent.agent_name, "analyze_order_seller", {
            "order_found": order_info["order_found"],
            "order_status": order_info["order_status"],
            "item_total_brl": order_info["item_total_brl"],
            "freight_total_brl": order_info["freight_total_brl"]
        })

        # 2. Handoff to PaymentAgent
        payment_info = self.payment_agent.analyze(
            claimed_order_id,
            order_info["item_total_brl"],
            order_info["freight_total_brl"]
        )
        self._log_trace(case_id, self.payment_agent.agent_name, "analyze_payment", {
            "payment_total_brl": payment_info["payment_total_brl"],
            "has_split_payment": payment_info["has_split_payment"],
            "is_reconciled": payment_info["is_reconciled"]
        })

        # 3. Handoff to DeliveryAgent
        delivery_info = self.delivery_agent.analyze(order_info)
        self._log_trace(case_id, self.delivery_agent.agent_name, "analyze_delivery", {
            "is_customer_delivery_late": delivery_info["is_customer_delivery_late"],
            "has_seller_late_handoff": delivery_info["has_seller_late_handoff"]
        })

        # 4. Handoff to PolicyAgent
        policy_output = self.policy_agent.evaluate(case_id, order_info, payment_info, delivery_info)
        self._log_trace(case_id, self.policy_agent.agent_name, "evaluate_policy", {
            "primary_issue": policy_output["assessment"]["primary_issue"],
            "recommended_refund_brl": policy_output["financial_resolution"]["recommended_refund_brl"]
        })

        # 5. Handoff to VerifierAgent
        final_output = self.verifier_agent.verify_and_refine(policy_output, case_input)
        self._log_trace(case_id, self.verifier_agent.agent_name, "verify_and_refine", {
            "case_status": final_output["assessment"]["case_status"],
            "confidence": final_output["assessment"]["confidence"]
        })

        return final_output

    def get_and_clear_traces(self) -> List[dict]:
        traces = list(self.trace_logs)
        self.trace_logs.clear()
        return traces
