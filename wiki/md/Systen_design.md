# System Design

## Systems

### Simulation

This digital twin is designed to simulate real editing process of user, where we can test the actual performance of different system under test. Including features:

* Features supported
  * Support simulation type: `batch simulation` and `visualized simulation`;
  * Support suggestion type: `naive suggestion` and `flow-keeping suggestion`;
  * Support multiple system under test.
* Interaction:
  * Start backend service via `python src/server.py` at project root directory;
  * Open VS Code;
  * User press `cmd` + `shift` + `p` (on MacOS) or `ctrl` + `shift` + `p` (on Windows/Linux) to open command palette;
  * User type `Historian: Simulate Editing Process` and press `enter` to activate the simulation assistant.
  * User select `System under test` and `Suggestion type`.
  * User can watch the simulation:
    * Check edit suggestions (location + content) at each timestamp;
    * Check the flow keeping status of each suggestion;
    * Watch the simulation process in real time;
    * Can pause at any time.
* Batch simulation:
  * Run `python -m simulation.main` at `src` directory;
  * Set `Suggestion type`
  * User can select multiple system under test and suggestion type.

### Optimization

User use `Claude Code` / `CoEdPilot` as next edit suggestion assistant, where we filter and re-rank all suggestions before present to user.

* Features supported:
  * Filer out suggestions that are: `flow-breaking`, `flow-reverting` or `flow-jumping`;
  * Re-rank `flow-keeping` suggestions based on their confidence score.

* Interaction:
  * Open code project in VS Code;
  * User press `cmd` + `shift` + `p` (on MacOS) or `ctrl` + `shift` + `p` (on Windows/Linux) to open command palette;
  * User type `Flow-keeper: Suggest Next Edit` and press `enter`;
  * User select backend suggestion model to activate the suggestion assistant.
  * User can start editing on the project;
  * Click `Suggest Next Edit` button (or via shortcut key `TBD`) and enter edit description to get next edit suggestion.
  * Edit suggestions will appear in left side bar, ranked by their confidence.
  * User can click each location, VS Code will jump to the corresponding location, with edit suggestion shown in `diff view`.
  * User can modify suggested content on the right panel, and click `Apply` button (or via shortcut key `TBD`) to apply, or `Reject` button (or via shortcut key `TBD`) to reject the suggestion.
  * Suggestions will not automatically be refreshed, user can continue to browse rest suggestions, until user click `Suggest Next Edit` button (or via shortcut key `TBD`) again.

## Architecture

* Router layer and Docker layer is not a must.
* Docker layer wrap the `Task specific layer` and `SUT layer`.

| Layer Name    | Simulation                                                                                                                                                            | Optimization                                                                                                                                              |
| :-----------: | :-------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------- |
| User layer                | 1\. Enter commit url <br> 2. Select system under test <br> 3. Select suggestion type                                                                                   | 1\. Open any project <br> 2. Make edit and request for subsequent edit suggestion                                                                        |
| VS Code layer               | 1\. Display suggested subsequent edits (highlight + diff) <br> 2. Display the evaluation of suggestions                                            | 1\. Display suggested subsequent edits (highlight + diff) <br> 2. Allow user to apply suggestion to project <br> 3. Allow user to edit on suggested edit |
| Router layer                 | 1\. Based on commit sha, route frontend request to corresponding backend docker                                                                                       | 1\. Based on user id, route frontend request to corresponding backend docker                                                                             |
| Task specific layer        | (src/simulation) <br> 1\. Maintain a COMMIT instance, to track current simulation progress, evaluate flow-keeping status and entropy <br> 2. Sync the project for SUT <br> 3. If suggestion type being `flow-keeping`, then invoke rerank algorithm before return to VS Code layer.| (src/optimization) <br> 1\. Re-rank the subsequent edit suggestions for backend <br> 2. Sync the project for SUT  |
| SUT layer           | 1\. Set up system under test (open app, load models, etc.) <br> 2. Suggest subsequent edits and return a predict snapshot                                             |                                                                                                                                                          |

## Messages

* VS Code layer --> Simulation Backend (either the router or simulation layer):

  * `commit_url`: commit url of the project;
  * `system_under_test`: system under test, either `Cursor`, `CoEdPilot`, `TRAE`, `Claude`;
  * `status`: request type, either `init` or `suggestion`.
  * `suggestion_type`: type of suggestion, either `naive` or `flow-keeping`.

* VS Code layer --> Flow-keeper layer (either the router or flow-keeper layer):

  * `id`: identifier used to find the corresponding SUT instance, here is VS Code user id;
  * `system_under_test`: system under test, either `CoEdPilot`, `Claude`; # The rest is currently unsupported.
  * `status`: request type, either `init` or `suggestion`;
  * `project_name`: name of the project;
  * `project`: dict, keys are file path relative to project root, values are file content, of type list[str];
  * `sync_type`: either `full` or `delta`;
  * `prior_edits`: prior edits made by user, list[dict], each dict at least should contain keys: `file_path` (relative to project root), `before` (list[str]), and `after` (list[str]);
  * `edit_description`: description of the edit, either user input or commit message.

* Task specific layer --> SUT layer:

  * `id`: identifier used to find the corresponding SUT instance, here is commit sha;
  * `project_name`: name of the project;
  * `status`: request type, either `init` or `suggestion`;
  * `repo_dir`: directory of the project in backend;
  * `prior_edits`: prior edits made by user / simulation;
  * `edit_description`: description of the edit, either user input or commit message.

* SUT layer --> Task specific layer:

  * `pred_snapshots`: predicted snapshots, dict, key is file path relative to project root, value is predicted snapshot, of type list[list[str] | dict], where list[str] is file content remain unchanged, each str is 1 line of code, and dict is the predicted edit, should at least contain keys: `before` and `after`.