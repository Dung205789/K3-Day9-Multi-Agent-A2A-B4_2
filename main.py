import os
import glob
import json
from src.utils.data_loader import DataLoader
from src.utils.llm_client import LLMClient
from src.agents.coordinator import CoordinatorAgent

def main():
    print("Initializing Multi-Agent System...")
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    input_dir = os.path.join(base_dir, "input")
    output_dir = os.path.join(base_dir, "output")
    logging_dir = os.path.join(base_dir, "logging")

    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(logging_dir, exist_ok=True)

    data_loader = DataLoader(os.path.join(base_dir, "data"))
    llm_client = LLMClient()
    coordinator = CoordinatorAgent(data_loader, llm_client)

    input_files = sorted(glob.glob(os.path.join(input_dir, "EC_*.json")))
    if not input_files:
        input_files = sorted(glob.glob(os.path.join(input_dir, "*.json")))

    print(f"Found {len(input_files)} cases to process.")

    all_traces = []

    for file_path in input_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                case_input = json.load(f)

            case_id = case_input.get("case_id", os.path.basename(file_path).replace(".json", ""))
            print(f"Processing case: {case_id}...")

            output_data = coordinator.process_case(case_input)

            # Write individual output file
            output_file = os.path.join(output_dir, f"{case_id}.json")
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)

            traces = coordinator.get_and_clear_traces()
            all_traces.extend(traces)

        except Exception as e:
            print(f"Error processing {file_path}: {e}")

    # Write trace.jsonl
    trace_path = os.path.join(logging_dir, "trace.jsonl")
    with open(trace_path, "w", encoding="utf-8") as f:
        for trace_item in all_traces:
            f.write(json.dumps(trace_item, ensure_ascii=False) + "\n")
        f.flush()

    # Write metadata.json
    metadata = {
        "model": os.getenv("OPENAI_MODEL", "meta/llama-3.1-8b-instruct"),
        "parameter_size": "8B",
        "framework": "Custom Python Multi-Agent Framework (Agent-to-Agent Handoff)",
        "runtime": "Python 3.13"
    }
    metadata_path = os.path.join(logging_dir, "metadata.json")
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    print(f"Completed processing all cases successfully. Wrote {len(all_traces)} trace entries to {trace_path}.")

if __name__ == "__main__":
    main()
