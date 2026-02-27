import subprocess
import sys
import os

if __name__ == "__main__":
    repo_id = "code-philia/CoEdPilot-extension-beta"

    # Set Hugging Face mirror to the Chinese mirror
    os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com/'
    script_path = os.path.abspath(__file__)
    script_dir = os.path.dirname(script_path)
    local_dir = os.path.join(script_dir, "models")

    # execute huggingface-cli download command and show output in terminal
    try:
        subprocess.run(
            ["huggingface-cli", "download", repo_id, "--local-dir", local_dir],
            check=True,
            stdout=sys.stdout,  # Redirect stdout to terminal
            stderr=sys.stderr   # Redirect stderr to terminal
        )
        print(f"Successfully downloaded {repo_id}.")
    except subprocess.CalledProcessError as e:
        print(f"Error occurred while downloading {repo_id}: {e}")
        