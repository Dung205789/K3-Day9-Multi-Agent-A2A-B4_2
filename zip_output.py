import os
import zipfile

def create_output_zip(output_dir="output", zip_filename="output.zip"):
    if not os.path.exists(output_dir):
        print(f"Directory {output_dir} does not exist.")
        return

    json_files = [f for f in os.listdir(output_dir) if f.endswith(".json") and f.startswith("EC_")]
    json_files.sort()

    print(f"Found {len(json_files)} JSON files in {output_dir}.")

    with zipfile.ZipFile(zip_filename, "w", zipfile.ZIP_DEFLATED) as zipf:
        for f in json_files:
            file_path = os.path.join(output_dir, f)
            zipf.write(file_path, arcname=f"output/{f}")

    print(f"Created {zip_filename} successfully with {len(json_files)} files.")

if __name__ == "__main__":
    create_output_zip()
