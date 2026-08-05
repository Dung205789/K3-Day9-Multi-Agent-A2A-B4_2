import os
import json
import glob
import time
from src.config import INPUT_DIR, OUTPUT_DIR, TRACE_FILE, get_active_model_info
from src.agents.coordinator import CoordinatorAgent

def main():
    print("================================================================================")
    print("     OLIST MULTI-AGENT E-COMMERCE DISPUTE RESOLUTION ENGINE STARTING            ")
    print("================================================================================")
    
    model_info = get_active_model_info()
    print(f"[Engine Setup] Active Provider: {model_info['provider'].upper()}")
    print(f"[Engine Setup] Declared LLM Model: {model_info['model_name']} (Parameter limit: {model_info['parameters']})")
    print(f"[Engine Setup] Input Directory : {INPUT_DIR}")
    print(f"[Engine Setup] Output Directory: {OUTPUT_DIR}")
    print(f"[Engine Setup] Trace Log File  : {TRACE_FILE}")
    
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        print(f"[Engine Setup] Created output directory: {OUTPUT_DIR}")
        
    input_files = sorted(glob.glob(os.path.join(INPUT_DIR, "*.json")))
    if not input_files:
        print(f"[Warning] No JSON case files found inside '{INPUT_DIR}'. Please check directory.")
        return
        
    print(f"[Engine Setup] Discovered {len(input_files)} test case files for multi-agent evaluation.\n")
    
    # Initialize Master Coordinator Agent (this warms up the Olist CSV database cache in memory)
    coordinator = CoordinatorAgent()
    
    # Open trace log file in 'w' mode to generate a brand new run trace per README Section 8
    success_count = 0
    total_confidence = 0.0
    start_all = time.time()
    
    with open(TRACE_FILE, "w", encoding="utf-8") as trace_fp:
        for file_path in input_files:
            file_name = os.path.basename(file_path)
            try:
                with open(file_path, "r", encoding="utf-8") as in_fp:
                    raw_case = json.load(in_fp)
                    
                submission_dict, trace_entry = coordinator.process_case(raw_case)
                
                # Write individual submission output JSON
                output_file_path = os.path.join(OUTPUT_DIR, file_name)
                with open(output_file_path, "w", encoding="utf-8") as out_fp:
                    json.dump(submission_dict, out_fp, indent=2, ensure_ascii=False)
                
                # Write chronòlogical trace line
                trace_fp.write(json.dumps(trace_entry, ensure_ascii=False) + "\n")
                
                success_count += 1
                total_confidence += submission_dict["assessment"]["confidence"]
                
            except Exception as err:
                print(f"[ERROR] Failed processing case file '{file_name}': {err}")
                import traceback
                traceback.print_exc()
                
    total_duration = round(time.time() - start_all, 2)
    avg_conf = round(total_confidence / max(1, success_count), 2)
    
    print("\n================================================================================")
    print(f"                       MULTI-AGENT EXECUTION COMPLETE                          ")
    print("================================================================================")
    print(f"Total Cases Processed : {success_count} / {len(input_files)}")
    print(f"Total Execution Time  : {total_duration} seconds")
    print(f"Average Confidence    : {avg_conf}")
    print(f"Output Submission JSONs generated in : {OUTPUT_DIR}/")
    print(f"Chronological Trace Log saved to     : {TRACE_FILE}")
    print("================================================================================")

if __name__ == "__main__":
    main()
