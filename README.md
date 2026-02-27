# EditFlow

EditFlow is the official repository for the OOPSLA 2026 paper: **EditFlow: Benchmarking and Optimizing Code Edit Recommendation Systems via Reconstruction of Developer Flows** by Chenyan Liu, Yun Lin, Jiaxin Chang, Jiawei Liu, Binhang Qi, Bo Jiang, Zhiyong Huang, Jin Song Dong.

This repository contains both the [prompt auto-tuning implementation](prompt_tuning/README.md) and the VS Code extension for both editing process simulation and developer flow optimization.

## 🚀 Demonstrations
>[!NOTE]
>Please click the image to watch the demo video on YouTube.

<table align="center"><tr>
<td align="center"><b>Optimization</b><br>
   <a href="https://www.youtube.com/watch?v=_6uc_iH4zG0">
   <img src="media\optimizer_demo.jpg" width="300" />
   </a>
</td>
<td align="center"><b>Simulation (digital twin)</b><br>
   <a href="https://www.youtube.com/watch?v=3ME_UqBphkI">
   <img src="media\simulator_demo.png" width="300" />
   </a>
</td>
</tr></table>

## 📌 Core Modules
EditFlow extension includes two independent but complementary core modules:
1. **Digital twin simulator**
   - **Purpose**: Reconstruct and simulate the entire developer code editing flow based on commit history, visualize edit suggestions at each timestamp, and evaluate the effectiveness of code edit recommendation systems.
   - **Backend Service**: `simulation_server.py` (default port: 5001)
   - **Configuration**: VS Code `Settings > Digital Twin Simulator: Server URL`

2. **EditFlow Optimization**
   - **Purpose**: Optimize existing code editing assistants by maintaining the consistency of developer editing flows, providing context-aware next-edit suggestions, and supporting interactive modification/validation of suggestions.
   - **Backend Service**: `optimization_server.py` (default port: 5002)
   - **Configuration**: VS Code `Settings > Edit Flow: Server URL`


## 💡 Usage and Interaction

### Prerequisite
Start the corresponding backend service before using each module:
- For Digital twin simulator: Run `python src/simulation_server.py` at project root (Default port 5001)
- For EditFlow Optimization: Run `python src/optimization_server.py` at project root (Default port 5002)
- For both modules: Start both backend services
- If you want to change the port, please refer to `server_config.ini` and remember to update the extension configuration at: `Settings > Digital Twin Simulator: Server URL` or `Settings > Edit Flow: Server URL` as well.

### 1. Digital twin simulator (Simulation process visualization)
- Start the Digital twin simulator backend service: Run `python src/simulation_server.py` at project root directory (port 5001);
- Open VS Code;
- Press `cmd` + `shift` + `p` (MacOS) or `ctrl` + `shift` + `p` (Windows/Linux) to open the command palette;
- Type `Commit simulation` and press `enter` to activate the simulation assistant;
- Enter the `commit URL` to be simulated, then select the `System under test` and `Suggestion type`;
- Watch the simulation process:
  - Check edit suggestions (location + content) at each timestamp;
  - Check the flow keeping status of each suggestion;
  - View the simulation process in real time;
  - The plugin pauses after each edit suggestion is simulated (wait for user confirmation to continue);
  - Click the `Resume Simulation` button to simulate the next edit;
  - View the `Evaluation Results` after simulation completes.


### 2. Batch simulation (Digital twin simulator)
- Set `Suggestion type` and `System under test` in `src/simulation/main.py: __main__`;
- Run the batch simulation command: `python -m simulation.main` at `src` directory (ensure the Digital twin simulator backend service is running first);

### 3. EditFlow Optimization (Optimize existing code editing assistants)
- Start the EditFlow Optimization backend service: Run `python src/optimization_server.py` at project root directory (port 5002);
- Open VS Code;
- Press `cmd` + `shift` + `p` (MacOS) or `ctrl` + `shift` + `p` (Windows/Linux) to open the command palette;
- Type `Flow-keeper: Suggest Next Edit` and press `enter` to activate the Optimization assistant;
- Select the `Test System`;
- Start editing the project after initializing the assistant;
- Click the `Suggest Next Edit` button and enter an edit description to get the next edit suggestion;
- View edit suggestions in the left sidebar:
  - Click any suggested location to jump to the corresponding code position (edit suggestion shown in `diff view`);
  - Modify the suggested content in the right panel:
    - Click `Accept` button to apply the suggestion;
    - Click `Reject` button to discard the suggestion;
  - Suggestions do not refresh automatically – continue browsing remaining suggestions until you click `Suggest Next Edit` again.


## 🕹️ Deployments

### Deploy as a user

For end-users, simply follow the instructions:
1. install the extension from the [VS Code Marketplace](https://marketplace.visualstudio.com/items?itemName=CodePhilia.code-trace).[TBD]

2. Install Python and dependencies:
    * Python 3.10 +
    * If you are using `conda`, please make sure to activate the environment before running the command.

    ```bash
    pip install -r requirements.txt
    ```
3. Install Node.js and dependencies:

    * Node.js 18 +
    ```bash
    npm install -g @anthropic-ai/claude-code
    ```

4. Download the backend models via command:

    ```bash
    python src/systemUnderTest/CoEdPilot/download.py
    ```

5. Set configurations at `.config` file.

6. Start backend models via command:

    ```bash
    python src/simulation_server.py
    python src/optimization_server.py
    ```

### Deploy as a developer

For debugging, customization purposes, please follow the instructions

1. Install Node.js dependencies in the project root directory (~/EditFlow):
    
    ```bash
    npm install
    ```

2. Open the project directory in VS Code, press `F5`, choose `Run Extension` if you are required to choose a configuration;

3. A new VS Code window (the "development host") will open with CoEdPilot extension loaded;

4. You may debug or customize the extension via the development host;

5. To pack your customized extension, make sure `yarn` is installed:

    ```bash
    npm install -g yarn
    npm install -g vsce
    ```

6. Under the project root directory:
    
    ```bash
    yarn package
    ```
    
    The command will generate a `.vsix` file under `./extension`, based on `package.json` file.

7. For public usage, you may release it to VS Code extension market
    
    > - Please follow the [VS Code Extension Marketplace guidelines](https://code.visualstudio.com/api/working-with-extensions/publishing-extension);
	> - If you modify and redistribute this extension, please clearly indicate that your version is a fork or modification, and **credit this project as the original**.

8. For personal usage, you may open the VS Code command palette (`Ctrl` + `Shift` + `P` / `Cmd` + `Shift` + `P`), then select `Extensions: Install from VSIX...` and choose the `.vsix` file generated in the previous step.

## ✍️ Citation

If you find our work helpful, please consider citing our paper:

```bibtex
@article{liu2026editflow,
  author = {Liu, Chenyan and Lin, Yun and Chang, Jiaxin and Liu, Jiawei and Qi, Binhang and Jiang, Bo and Huang, Zhiyong and Dong, Jin Song},
  title = {EditFlow: Benchmarking and Optimizing Code Edit Recommendation Systems via Reconstruction of Developer Flows},
  journal = {Proceedings of the ACM on Programming Languages},
  volume = {10},
  number = {OOPSLA1},
  year = {2026},
  doi = {10.1145/3798249}
}
```

## 🐛 Issues

You are welcomed report any bugs or feature requests through the GitHub issues page. 

**Enjoy!**
