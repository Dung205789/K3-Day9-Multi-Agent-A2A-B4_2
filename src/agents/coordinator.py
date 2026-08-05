import json
import time
from typing import Dict, Any, Tuple
from src.schema import CaseInput, CaseOutput
from src.agents.order_seller_agent import OrderSellerAgent
from src.agents.payment_agent import PaymentAgent
from src.agents.delivery_agent import DeliveryAgent
from src.agents.policy_agent import PolicyAgent
from src.agents.verifier_agent import VerifierAgent
from src.config import get_active_model_info

class CoordinatorAgent:
    """Master Orchestrator Agent responsible for receiving client claims, dispatching tasks to specialist agents,

    collecting verifiable evidence, managing handoff communication, and writing execution logs to trace.jsonl.
    """
    def __init__(self):
        self.agent_name = "Coordinator Agent"
        self.order_seller_agent = OrderSellerAgent()
        self.payment_agent = PaymentAgent()
        self.delivery_agent = DeliveryAgent()
        self.policy_agent = PolicyAgent()
        self.verifier_agent = VerifierAgent()
        self.model_info = get_active_model_info()

    def process_case(self, raw_json: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Processes a single case dictionary and returns (submission_dict, trace_entry)."""
        start_time = time.time()
        case_input = CaseInput(**raw_json)
        case_id = case_input.case_id
        claimed_order_id = case_input.customer_request.claimed_order_id
        claim_msg = case_input.customer_request.message
        
        print(f"\n================================================================================")
        print(f"[{self.agent_name}] Initiating A2A Dispute Resolution Workflow for Case: {case_id}")
        print(f"Claimed Order ID: {claimed_order_id} | Model Config (<10B): {self.model_info['model_name']}")
        print(f"================================================================================")
        
        # --- Step 1: Handoff to Order & Seller Agent ---
        print(f"[{self.agent_name}] Handoff #1 -> Order & Seller Agent...")
        order_facts = self.order_seller_agent.investigate(claimed_order_id)
        
        # --- Step 2: Handoff to Payment Agent ---
        print(f"[{self.agent_name}] Handoff #2 -> Payment Agent...")
        payment_facts = self.payment_agent.investigate(
            order_id=claimed_order_id,
            item_total_brl=order_facts.get("item_total_brl", 0.0),
            freight_total_brl=order_facts.get("freight_total_brl", 0.0)
        )
        
        # --- Step 3: Handoff to Delivery Agent ---
        print(f"[{self.agent_name}] Handoff #3 -> Delivery Agent...")
        delivery_facts = self.delivery_agent.investigate(order_facts)
        
        # --- Step 4: Handoff to Policy Agent ---
        print(f"[{self.agent_name}] Handoff #4 -> Policy Agent for priority rule adjudication...")
        policy_verdict = self.policy_agent.adjudicate(
            order_facts=order_facts,
            payment_facts=payment_facts,
            delivery_facts=delivery_facts,
            claim_message=claim_msg
        )
        
        # --- Step 5: Handoff to Verifier Agent (Hard Gate Defense) ---
        print(f"[{self.agent_name}] Handoff #5 -> Verifier Agent for Hard Gate QA certification...")
        final_output: CaseOutput = self.verifier_agent.verify_and_format(
            case_id=case_id,
            order_facts=order_facts,
            payment_facts=payment_facts,
            policy_verdict=policy_verdict
        )
        
        submission_dict = final_output.to_submission_dict()
        duration_ms = int((time.time() - start_time) * 1000)
        
        # Construct explicit multi-agent chronological trace log entry
        trace_entry = {
            "case_id": case_id,
            "claimed_order_id": claimed_order_id,
            "timestamp": case_input.opened_at,
            "llm_model_declared": self.model_info["model_name"],
            "parameter_size": self.model_info["parameters"],
            "execution_duration_ms": duration_ms,
            "agent_handoffs_trace": [
                {
                    "step": 1,
                    "from_agent": "Coordinator Agent",
                    "to_agent": "Order & Seller Agent",
                    "action": "Query orders, order_items, and sellers CSV tables & synthesize LLM domain assessment",
                    "result_summary": order_facts.get("reasoning_summary", f"Found order status: '{order_facts.get('order_status')}', items count: {len(order_facts.get('item_ids', []))}, seller handoff late: {order_facts.get('seller_handoff_late')}")
                },
                {
                    "step": 2,
                    "from_agent": "Coordinator Agent",
                    "to_agent": "Payment Agent",
                    "action": "Audit payment rows & generate LLM financial reconciliation report",
                    "result_summary": payment_facts.get("reasoning_summary", f"Total payment: {payment_facts.get('payment_total_brl')} BRL, Reconciled: {payment_facts.get('is_reconciled')}")
                },
                {
                    "step": 3,
                    "from_agent": "Coordinator Agent",
                    "to_agent": "Delivery Agent",
                    "action": "Compare customer delivered date against estimate & produce LLM delay attribution",
                    "result_summary": delivery_facts.get("reasoning_summary", f"Is late delivery: {delivery_facts.get('is_late_delivery')}, Attribution: {delivery_facts.get('late_attribution')}")
                },
                {
                    "step": 4,
                    "from_agent": "Coordinator Agent",
                    "to_agent": "Policy Agent",
                    "action": "Apply EC_POLICY_V1 priority table rules (1-6) & formulate LLM legal verdict",
                    "result_summary": policy_verdict.get("adjudication_explanation", f"Primary issue adjudicated: '{policy_verdict.get('primary_issue')}', Refund BRL: {policy_verdict.get('recommended_refund_brl')}")
                },
                {
                    "step": 5,
                    "from_agent": "Policy Agent",
                    "to_agent": "Verifier / Critic Agent",
                    "action": "Verify 100% of Evidence IDs against real CSV records & enforce schema limits",
                    "result_summary": f"Hard Gate QA passed. Verified evidence IDs count: {len(submission_dict.get('evidence_ids', []))}"
                }
            ],
            "final_assessment_status": submission_dict["assessment"]["case_status"],
            "final_confidence": submission_dict["assessment"]["confidence"]
        }
        
        print(f"[{self.agent_name}] Case {case_id} resolved successfully in {duration_ms}ms! Primary Issue: {submission_dict['assessment']['primary_issue']}")
        return submission_dict, trace_entry
