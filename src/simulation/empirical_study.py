import os
import json
from .main import main
if __name__ == "__main__":
    to_simulate_fps = [
        "simulation/manual_dataset/pytorch_geometric-60c2c29c9bc80e722e13f1ddf57db949f5ec944.json",
        "simulation/manual_dataset/locust-747a55eb23364d2b89a867d2b5914026c4a2790f.json",
        "simulation/manual_dataset/models-19e1187a4071b62064d4f312ff6d816381c9de6a.json",
        "simulation/manual_dataset/localstack-d47f509bf2495f17f5716e1d7b8e3d80164adc81.json",
        "simulation/manual_dataset/pytorch_geometric-e8915ad1cb5831c33c77f0fa69ee8a2267074647.json",
        "simulation/manual_dataset/sherlock-25e0acd98e80e33e4c65086ce66cd3615d908d1c.json",
        "simulation/manual_dataset/core-153b69c971d81d7b1fb7de3d3640dfdca2f11a89.json",
        "simulation/manual_dataset/faceswap-e2d84bec50884c6d1ae4bf94fee7e4f10e836d69.json",
        "simulation/manual_dataset/ansible-afc196acf1275d4adb239a52505f42938c1a1449.json",
        "simulation/manual_dataset/core-28bebf338fd1aca55c5ebcfc3dd31273c419e5cf.json",
        "simulation/manual_dataset/vllm-85de0934727dc2c7b740b1d4a90d1a2e3c2d0585.json",
        "simulation/manual_dataset/airflow-e4d935e49007b17bf5c11f2ff1fdf4a1a3de164d.json",
        "simulation/manual_dataset/glances-7c9040688e2d7978426dbdab916c1185b6065199.json",
        "simulation/manual_dataset/core-a0bbe46c4a9637b40bcdc2d2eab574f916973033.json",
        "simulation/manual_dataset/core-52e8c7166b724126b39e22cbb8b52c27e8b8757c.json",
        "simulation/manual_dataset/core-a9b51f0255eb673d204bc0e536dbda41dc851584.json",
        "simulation/manual_dataset/kitty-ebcbed290fab4d4fb850fc587ddba4d217ac87cc.json",
        "simulation/manual_dataset/Gooey-fa4bf4dc5cd15c8662c7862073b4bfe6a84294c8.json",
        "simulation/manual_dataset/airflow-051fac0776b7e61e80653d1e91fdf2dfb1017a6f.json",
        "simulation/manual_dataset/cpython-636860354ee7be4b7bf55dddb0cbb129c989b681.json",
        "simulation/manual_dataset/examples-244e4eefb199f5e74e11d15c1b1c3186ccd2d313.json",
        "simulation/manual_dataset/scikit-learn-5aeeeefe31acd5444148fd89f3a8df9443b04889.json",
        "simulation/manual_dataset/localstack-f79fb82e933053efbe3f479751772b1bfd063ea1.json",
        "simulation/manual_dataset/pytorch-lightning-ab4c838ba394f7b92f28676d8bf758ecf499d7e8.json",
        "simulation/manual_dataset/ComfyUI-aaa9017302b75cf4453b5f8a58788e121f8e0a39.json",
        "simulation/manual_dataset/jax-98e114da4fee0bc1a656925cede41068475c5323.json",
        "simulation/manual_dataset/fairseq-eff39d5d453497a5a6e5e998e2a920fb5f0618e1.json",
        "simulation/manual_dataset/core-4b2cbbe8c2ce998c7ffaeea8654d3c9900c386b3.json",
        "simulation/manual_dataset/mitmproxy-09e995ab5c78b8bd098e1330df7aa40972e0b1bb.json",
        "simulation/manual_dataset/pandas-9310cb7d8dc6e6a36e0d9d17059f4d4b7a813d86.json",
        "simulation/manual_dataset/core-9acca1bf5833cfa000e663f156f13411702c8114.json",
        "simulation/manual_dataset/fairseq-6c006a34abbc0e8cb56445e57ebc0859739cad77.json",
        "simulation/manual_dataset/redash-46f1478e0d240bea18c6e287cc96870c69cd3f29.json",
        "simulation/manual_dataset/core-1883b1d2a264ebdae30c2dd975df95262c192ec5.json",
        "simulation/manual_dataset/jax-b1b4915c1caaf39309b88bd3f8492778fb3aeadb.json",
        "simulation/manual_dataset/sqlmap-6bbb8139a0e26652efacca19f736e997251a2c24.json",
        "simulation/manual_dataset/sentry-5cf12753665512f60b32a99dd8fd9aa27d0a4a3a.json",
        "simulation/manual_dataset/kitty-da1276d84a80ca1b42aa64750a34668021d2e008.json",
        "simulation/manual_dataset/celery-c22e68395868665737b56199f257fae75b91dd2c.json",
        "simulation/manual_dataset/zulip-a8d86d5fb2e851787c336883aa20b76f10b06c07.json","simulation/manual_dataset/scikit-learn-e9d660d80c8943471f0a3e80528168833a778f7d.json",
        "simulation/manual_dataset/ComfyUI-03e6e81629b0eb5351f82fcbaafad8698253bfbc.json",
        "simulation/manual_dataset/kitty-c4c62c1505c48f90d75554f02030b76414637f8a.json",
        "simulation/manual_dataset/transformers-c17e7cde326640a135bc7236a0e41ae52471cb90.json",
        "simulation/manual_dataset/core-5d7e9a6695eaa67b8319703fe1d10070fe493d75.json",
        "simulation/manual_dataset/glances-5496fcac2ff3f296853f9df9551a12848085a0c5.json",
        "simulation/manual_dataset/core-2e636f598eaa79f3634bed0981332b70840342be.json",
        "simulation/manual_dataset/diffusers-679c77f8ea05c2645285f8a0afc0c7fd3ede479d.json",
        "simulation/manual_dataset/glances-25b6b5c797b348318bf3f1bf110944c4f37d5e2d.json",
        "simulation/manual_dataset/zulip-96bfeeb9e604ef42ef30d699b00d1a23ff17d29c.json"
    ]
    
    sut = "Cursor_CLI"
    for filepath in to_simulate_fps:
        with open(filepath, "r") as f:
            data = json.load(f)
        print(f"Simulation commit: {data['commit_url']}")
        edit_hunk_num = 0
        for edit_file_path, snapshot in data["commit_snapshots"].items():
            for window in snapshot:
                if isinstance(window, dict):
                    edit_hunk_num += 1

        for i in range(edit_hunk_num):
            if i == 0:
                status = "init"
            else:
                status = "suggestion"

            input = {
                "commit_url": data["commit_url"],
                "system_under_test": sut,
                "status": status,
                "suggestion_type": "naive"
            }
            main(input)
