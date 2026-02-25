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


## 💡 Usage and Interaction

1. Visualization of simualtion process:

    * Start backend service via `python src/simulation_server.py` at project root directory;
    * Open VS Code;
    * User press `cmd` + `shift` + `p` (on MacOS) or `ctrl` + `shift` + `p` (on Windows/Linux) to open command palette;
    * User type `Commit simulation` and press `enter` to activate the simulation assistant.
    * Users enter the `commit URL` to be simulated, then select the `System under test` and `Suggestion type`.
    * User can watch the simulation:
        * Check edit suggestions (location + content) at each timestamp;
        * Check the flow keeping status of each suggestion;
        * Watch the simulation process in real time;
        * The plugin pauses after each edit suggestion is simulated, waiting for user confirmation to continue;
        * Click the `Resume Simulation` button to start simulating the next edit.
        * View the `Evaluation Results` after the simulation completes.

2. Batch simulation:
    * Set `Suggestion type`, `System under test` in `src/simulation/main.py: __main__`;
    * Run `python -m simulation.main` at `src` directory;

3. Optimize existing code editing assistants:
    * Start backend service via `python src/optimization_server.py` at project root directory;
    * Open VS Code;
    * User press `cmd` + `shift` + `p` (on MacOS) or `ctrl` + `shift` + `p` (on Windows/Linux) to open command palette;
    * User type `Flow-keeper: Suggest Next Edit` and press `enter` to activate the Optimization assistant.
    * Users select the `Test System`.
    * User can start editing on the project after initializing the assistant;
    * Click `Suggest Next Edit` button and enter edit description to get next edit suggestion.
    * Edit suggestions will appear in left side bar.
    * User can click each location, VS Code will jump to the corresponding location, with edit suggestion shown in `diff view`.
    * User can modify suggested content on the right panel, and click `Accept` button to apply, or `Reject` button to reject the suggestion.
    * Suggestions will not automatically be refreshed, user can continue to browse rest suggestions, until user click `Suggest Next Edit` button again

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

    * The default port set for simulation server is `5001`
    * The default port set for optimization server is `5002`
    * If you want to change the port, please refer to `server_config.ini` and remember to update the extension configuration at: `Settings > editflow` as well. # TODO: jiaxin please check the exact path

### Deploy as a developer

For debugging, customization purposes, please follow the instructions

1. Under directory `./extension`, install Node packages:
    
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
