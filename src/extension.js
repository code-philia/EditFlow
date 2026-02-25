const vscode = require('vscode');
const { Simulate, initializeSimulationView, testDiffParsing, validateSimulationServerConnection, resetSimulation } = require('./simulate.js');
const { initializeFlowKeeper, runOptimization, acceptDiff, rejectDiff, validateOptimizationServerConnection} = require('./optimization.js');
const { EntropyScoreboardViewProvider } = require('./entropyScoreboardViewProvider');
const { EditFlowTrackingViewProvider } = require('./editFlowTrackingViewProvider');

let lastInputValue = '';

/**
 * Show a persistent input box that doesn't close on focus loss
 */
function showPersistentInputBox(options) {
    return new Promise((resolve) => {
        const inputBox = vscode.window.createInputBox();
        inputBox.prompt = options.prompt;
        inputBox.placeholder = options.placeHolder;
        inputBox.ignoreFocusOut = true;
        
        if (lastInputValue) {
            inputBox.value = lastInputValue;
        }
        
        let isResolved = false;
        
        inputBox.onDidAccept(() => {
            if (!isResolved) {
                isResolved = true;
                const value = inputBox.value;
                if (value && value.trim()) {
                    lastInputValue = value;
                }
                inputBox.dispose();
                resolve(value);
            }
        });
        
        inputBox.onDidHide(() => {
            if (!isResolved) {
                isResolved = true;
                inputBox.dispose();
                resolve(null);
            }
        });
        
        inputBox.show();
    });
}

/**
 * @param {vscode.ExtensionContext} context
 */
function activate(context) {
    console.log('Extension activated!');
    // kick off backend health checks (5001, 5002)
    try { validateSimulationServerConnection(true, 3000); } catch (_) {}
    try { validateOptimizationServerConnection(true, 3000); } catch (_) {}
    
    let entropyScoreboardProvider = new EntropyScoreboardViewProvider(context);
    let editFlowTrackingProvider = new EditFlowTrackingViewProvider(context);
    context.subscriptions.push(
        vscode.window.registerWebviewViewProvider(
            'entropyScoreboardView',
            entropyScoreboardProvider
        )
    );
    context.subscriptions.push(
        vscode.window.registerWebviewViewProvider(
            'editFlowTrackingView',
            editFlowTrackingProvider
        )
    );

    // Register command to start simulation
    let queryUrl = vscode.commands.registerCommand('commit-recovery-simulator.simulateCommitRecoveryFromInput', async function () {
        const previousEdits = [];
        const targetFileSegments = []; // Will be automatically obtained from VS Code
        const refFiles = []; // Will be automatically obtained from VS Code

        let url = await vscode.window.showInputBox({
            prompt: 'Enter a commit URL',
            validateInput: (input) => {
                const commitUrlPattern = new RegExp('^https:\\/\\/github\\.com\\/[^\\/]+\\/[^\\/]+\\/commit\\/[a-f0-9]{7,40}$');
                if (!commitUrlPattern.test(input)) {
                    return "Please enter a valid commit URL";
                }
                return null;
            }
        });

        if (url) {
            const validSystems = ['CoEdPilot', 'Cursor', 'TRAE', 'Claude'];
            let systemUnderTest = await vscode.window.showQuickPick(validSystems, {
                placeHolder: 'Select system under test',
                canPickMany: false
            });

            if (!systemUnderTest) {
                vscode.window.showErrorMessage('System under test is required');
                return;
            }

            const validType = ['Original suggestion', 'Flow-aligned suggestion'];
            let suggestion_type = await vscode.window.showQuickPick(validType, {
                placeHolder: 'Select suggestion type',
                canPickMany: false
            });

            if (!suggestion_type) {
                vscode.window.showErrorMessage('Suggestion type is required');
                return;
            }

            try {
                const urlParts = url.split('/');
                const commitHash = urlParts[6];

                const workspaceRoot = vscode.workspace.workspaceFolders?.[0].uri.fsPath;
                if (!workspaceRoot) {
                    throw new Error('No workspace is open');
                }

                const { exec } = require('child_process');

                const executeGitCommand = (command) => {
                    return new Promise((resolve, reject) => {
                        exec(command, { cwd: workspaceRoot }, (error, stdout, stderr) => {
                            if (error) {
                                reject(new Error(`Git command failed: ${stderr}`));
                            } else {
                                resolve(stdout.trim());
                            }
                        });
                    });
                };

                const status = await executeGitCommand('git status --porcelain');
                const hasChanges = status.length > 0;

                if (hasChanges) {
                    await executeGitCommand('git stash');
                }

                try {
                    await executeGitCommand(`git checkout ${commitHash.substring(0, 7)}`);
                    vscode.window.showInformationMessage(`Checked out to commit: ${commitHash.substring(0, 7)}`);
                } catch (error) {
                    vscode.window.showErrorMessage(`Checkout failed: ${error.message}`);
                    return;
                }

                // Get parent commit
                const parentHash = await executeGitCommand(`git log -1 --pretty=%P ${commitHash}`);

                try {
                    await executeGitCommand(`git checkout ${parentHash.substring(0, 7)}`);
                    vscode.window.showInformationMessage(`Checked out to parent commit: ${parentHash.substring(0, 7)}`);
                } catch (error) {
                    vscode.window.showErrorMessage(`Checkout failed: ${error.message}`);
                }

                resetSimulation();
                await Simulate(url, context, previousEdits, targetFileSegments, refFiles, systemUnderTest, suggestion_type, entropyScoreboardProvider, editFlowTrackingProvider);
            } catch (error) {
                vscode.window.showErrorMessage(`Git command failed: ${error.message}`);
                return;
            }
        }
    });

    context.subscriptions.push(queryUrl);

    // Register command to start Flow-keeper
    let flowKeeperInit = vscode.commands.registerCommand('edit-suggestion-simulator.simulateEditSuggestion', async function () {
        const validTestSystems = ['CoEdPilot', 'Claude'];
        const systemUnderTest = await vscode.window.showQuickPick(validTestSystems, {
            placeHolder: 'Select test system',
            canPickMany: false
        });
        if (!systemUnderTest) {
            vscode.window.showErrorMessage('System under test is required');
            return;
        }
        try {
            await initializeFlowKeeper(systemUnderTest);
        } catch (e) {
            vscode.window.showErrorMessage(`Flow-keeper init failed: ${e.message}`);
        }
    });
    context.subscriptions.push(flowKeeperInit);

    // Register command bound to the toolbar icon to request next edit
    let flowKeeperSuggest = vscode.commands.registerCommand('edit-suggestion-simulator.suggestion', async function () {
        const editDescription = await showPersistentInputBox({
            prompt: 'Describe the next edit you want',
            placeHolder: 'e.g., Refactor function X to accept config Y'
        });
        if (editDescription !== null) {
            try {
                await runOptimization(context, editDescription);
            } catch (e) {
                vscode.window.showErrorMessage(`Optimization failed: ${e.message}`);
            }
        }
    });
    context.subscriptions.push(flowKeeperSuggest);

    // Register command to accept diff
    let acceptDiffCommand = vscode.commands.registerCommand('edit-suggestion-simulator.acceptDiff', async function () {
        try {
            await acceptDiff();
        } catch (e) {
            vscode.window.showErrorMessage(`Accept diff failed: ${e.message}`);
        }
    });
    context.subscriptions.push(acceptDiffCommand);

    // Register command to reject diff
    let rejectDiffCommand = vscode.commands.registerCommand('edit-suggestion-simulator.rejectDiff', async function () {
        try{
            await rejectDiff();
        }catch(e){
            vscode.window.showErrorMessage(`Reject diff failed: ${e.message}`);
        }
    });
    context.subscriptions.push(rejectDiffCommand);

}

function deactivate() {}

module.exports = {
    activate,
    deactivate
};