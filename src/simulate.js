const vscode = require('vscode');
const path = require('path');
const fs = require('fs');
const os = require('os');
const { PredictedLocationsFlatProvider, PredictedEditsTreeDataProvider, PriorEditsTreeDataProvider } = require('./simulatorViewProvider.js');
const { execFile } = require('child_process');

let isFirstRun = true; 
let isPausedForGroundTruth = false;
let isSimulationCompleted = false;
let totalTP = 0;
let totalFP = 0;
let totalFN = 0;

function calculateMetrics(tp, fp, fn) {
    const precision = tp + fp > 0 ? tp / (tp + fp) : 0;
    const recall = tp + fn > 0 ? tp / (tp + fn) : 0;
    const f1 = precision + recall > 0 ? 2 * (precision * recall) / (precision + recall) : 0;
    
    return {
        precision: precision.toFixed(4),
        recall: recall.toFixed(4),
        f1: f1.toFixed(4)
    };
}

// show evaluation metrics
function showEvaluationMetrics() {
    const metrics = calculateMetrics(totalTP, totalFP, totalFN);

    const precision = (Number(metrics.precision) * 100).toFixed(2);
    const recall = (Number(metrics.recall) * 100).toFixed(2);
    const f1 = (Number(metrics.f1) * 100).toFixed(2);

    vscode.window.showInformationMessage("📊 Simulation Evaluation Results");
    vscode.window.showInformationMessage(`Precision : ${precision}%`);
    vscode.window.showInformationMessage(`Recall    : ${recall}%`);
    vscode.window.showInformationMessage(`F1-Score  : ${f1}%`);
}

// update evaluation metrics
function updateEvaluationMetrics(tp, fp, fn) {
    totalTP += tp || 0;
    totalFP += fp || 0;
    totalFN += fn || 0;
}

let allHunks = [];
let currentHunkIndex = 0;
let predictedLocationsProvider = null;
let predictedEditsProvider = null;
let priorEditsProvider = null;
let viewInitialized = false;
let decorationType = null;
let decorationType1 = null; 
let highlightMapOrange = new Map();
let highlightMapCyan = new Map();
let currentTempFile = null;
let currentCommitUrl = null; 
let currentsystemUnderTest = null;
let currentsuggestion_type = null;

let isPaused = false;
async function updateContext() {
    await vscode.commands.executeCommand(
        'setContext',
        'commit-recovery-simulator.isPaused',
        isPaused
    );
}


// record temp file and original file mapping
const tempToOriginalMap = new Map();

function initializeSimulationView(context, commit_url, systemUnderTest, suggestion_type, entropyScoreboardProvider, editFlowTrackingProvider) {
    currentCommitUrl = commit_url;
    currentsystemUnderTest = systemUnderTest;
    currentsuggestion_type = suggestion_type;
    // initialize view and command
    if (!viewInitialized) {
        // initialize all tree data providers
        predictedLocationsProvider = new PredictedLocationsFlatProvider();
        // predictedEditsProvider = new PredictedEditsTreeDataProvider();
        // priorEditsProvider = new PriorEditsTreeDataProvider();

        // create all tree views
        context.subscriptions.push(
            vscode.window.createTreeView('simulatorView', {
                treeDataProvider: predictedLocationsProvider,
                showCollapseAll: true
            })
        );

        // context.subscriptions.push(
        //     vscode.window.createTreeView('simulatorFileView', {
        //         treeDataProvider: predictedEditsProvider,
        //         showCollapseAll: true
        //     })
        // );

        // context.subscriptions.push(
        //     vscode.window.createTreeView('simulatorPrevEditView', {
        //         treeDataProvider: priorEditsProvider,
        //         showCollapseAll: true
        //     })
        // );

        // create decorator
        decorationType = vscode.window.createTextEditorDecorationType({
            backgroundColor: '#FFA500',
            isWholeLine: true
        });

        decorationType1 = vscode.window.createTextEditorDecorationType({
            backgroundColor: '#00FFFF', 
            isWholeLine: true
        });

        // listen to file switch event, automatically restore highlight
        context.subscriptions.push(
            vscode.window.onDidChangeActiveTextEditor(editor => {
                if (!editor) return;
                const fileUri = editor.document.uri.toString();
                // restore orange
                if (highlightMapOrange.has(fileUri)) {
                    editor.setDecorations(decorationType, highlightMapOrange.get(fileUri));
                } else {
                    editor.setDecorations(decorationType, []);
                }
                // restore cyan
                if (highlightMapCyan.has(fileUri)) {
                    editor.setDecorations(decorationType1, highlightMapCyan.get(fileUri));
                } else {
                    editor.setDecorations(decorationType1, []);
                }
            })
        );

        // clean up temp file when extension is uninstalled
        context.subscriptions.push({
            dispose: () => {
                if (currentTempFile) {
                    try {
                        fs.unlinkSync(currentTempFile);
                    } catch (e) {
                        console.log('Failed to clean up temporary files:', e.message);
                    }
                    currentTempFile = null;
                }
            }
        });

        // click pause/continue button: show next hunk, and automatically jump
        context.subscriptions.push(
            vscode.commands.registerCommand('commit-recovery-simulator.pauseResume', async () => {
                isPaused = !isPaused;
                await updateContext();
                // clear all decorations
                for (const editor of vscode.window.visibleTextEditors) {
                    editor.setDecorations(decorationType, []);
                    editor.setDecorations(decorationType1, []);
                }
                highlightMapOrange.clear();
                highlightMapCyan.clear();
                // delete previous diff temp file
                if (currentTempFile) {
                    try {
                        fs.unlinkSync(currentTempFile);
                        currentTempFile = null;
                    } catch (e) {}
                }
                // find flowKeeping==true hunk
                let flowHunk = null;
                if (allHunks.length > 0) {
                    flowHunk = allHunks.find(h => h.flowKeeping === true);
                }
                if (flowHunk) {
                    // open diff and automatically accept
                    await showHunkDiff(flowHunk);
                    if (flowHunk.modelMake === true) {
                        if (predictedLocationsProvider) {
                            console.log('flowHunk.flowPattern:', flowHunk.flowPattern);
                            console.log('flowHunk:', flowHunk);
                            predictedLocationsProvider.updateItems([flowHunk], {
                                "flow_keeping": [
                                    flowHunk.idx
                                ],
                                "flow_jumping": [],
                                "flow_breaking": [],
                                "flow_reverting": []
                            });
                        }
                        if (isFirstRun) {
                            vscode.window.showInformationMessage('✅ The initial edit is applied to project.');
                            isFirstRun = false;
                        } else {
                            vscode.window.showInformationMessage('✅ This hunk is predicted by model.');
                        }
                        await new Promise(resolve => setTimeout(resolve, 3000)); // wait for diff view to open
                    }
                    if (flowHunk.modelMake === false) {
                        if (!isPausedForGroundTruth) {
                            if (predictedLocationsProvider) {
                                predictedLocationsProvider.updateItems([], null);
                            }
                            vscode.window.showInformationMessage('❌All suggestions violate user mental flow');
                            vscode.window.showInformationMessage('⚠️ Now applying ground-truth');
                            vscode.window.showInformationMessage('💡You may continue simulation');
                            isPausedForGroundTruth = true;
                            return;
                        } else {
                            await autoAcceptHunk(flowHunk);
                            isPausedForGroundTruth = false; 
                        }
                    } else { // flowHunk.modelMake === true
                        await autoAcceptHunk(flowHunk);
                        if (predictedLocationsProvider) {
                            predictedLocationsProvider.updateItems([], null);
                        }
                    }
                } else {
                    vscode.window.showInformationMessage('No more hunks');
                }

                // continue to request next hunk
                let changedHunks = [];
                let flowPattern = null;
                try {
                    const result = await vscode.window.withProgress({
                        location: vscode.ProgressLocation.Notification,
                        title: `Generating next edit`,
                        cancellable: false
                    }, async () => await simulateNextStep(currentCommitUrl, [], [], [], currentsystemUnderTest, currentsuggestion_type, entropyScoreboardProvider, editFlowTrackingProvider));
                    changedHunks = result.hunks;
                    flowPattern = result.flowPattern;
                    allHunks = [];
                    if (changedHunks && changedHunks.length > 0) {
                        // only add hunk with modelMake==true to view and highlight
                        for (const hunk of changedHunks) {
                            if (hunk.modelMake === true) {
                                allHunks.push(hunk);
                            }
                        }
                        currentHunkIndex = allHunks.length;
                        // update view
                        if (flowPattern) {
                            predictedLocationsProvider.updateItems(allHunks, flowPattern);
                        }
                        // predictedEditsProvider.updateHunks(allHunks);
                        // priorEditsProvider.updatePriorEdits([]);
                        await showLocation(allHunks);
                        for (const hunk of changedHunks) {
                            if (hunk.modelMake === false) {
                                allHunks.push(hunk);
                            }
                        }
                    } else {
                        vscode.window.showWarningMessage('Simulation completed.');
                    }
                } catch (error) {
                    console.error('Fail to find next hunks: ', error);
                }
            })
        );

        // click show hunk diff button: show diff view
        context.subscriptions.push(
            vscode.commands.registerCommand('simulator.showHunkDiff', async (hunk) => {
                if (hunk) {
                    await showHunkDiff(hunk);
                }
            })
        );
        viewInitialized = true;
    }
}

/**
 * 
 * @param {*} context 
 * @param {*} previousEdits 
 * @param {*} targetFileSegments 
 * @param {*} refFiles 
 * @param {any} systemUnderTest
 * @returns 
 */
async function Simulate(commit_url, context, previousEdits = [], targetFileSegments = [], refFiles = [], systemUnderTest, suggestion_type, entropyScoreboardProvider, editFlowTrackingProvider) {
    updateContext();
    let targetHunks = [];
    const workingDirectory = vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders.length > 0
        ? vscode.workspace.workspaceFolders[0].uri.fsPath
        : null;
    if (!workingDirectory) {
        vscode.window.showErrorMessage('Please open a workspace and try again.');
        return;
    }

    // initialize view
    initializeSimulationView(context, commit_url, systemUnderTest, suggestion_type, entropyScoreboardProvider, editFlowTrackingProvider);

    // get first hunk through simulateInitStep
    const { hunks: firstHunks, flowPattern: firstFlowPattern } = await vscode.window.withProgress({
        location: vscode.ProgressLocation.Notification,
        title: 'Recovering edit order and initializing edit simulation...',
        cancellable: false
    }, async () => await simulateInitStep(commit_url, previousEdits, targetFileSegments, refFiles, systemUnderTest, suggestion_type, entropyScoreboardProvider, editFlowTrackingProvider));

    // process first hunk
    allHunks = firstHunks;
    currentHunkIndex = allHunks.length;
    if (allHunks.length === 0) {
        vscode.window.showWarningMessage('No hunks generated in the initialization step.');
        return;
    }

    // show first hunk
    if (allHunks.length > 0) {
        await showLocation(allHunks[0]);
        // update view
        predictedLocationsProvider.updateItems(allHunks, firstFlowPattern);
        // predictedEditsProvider.updateHunks(allHunks);
        // priorEditsProvider.updatePriorEdits(previousEdits);
    }


}
async function simulateInitStep(commit_url, previousEdits, targetFileSegments, refFiles, systemUnderTest, suggestion_type, entropyScoreboardProvider, editFlowTrackingProvider) {
        try {
            const backendResponse = await sendBackendRequest(commit_url, systemUnderTest, "init", suggestion_type);
            
            if (backendResponse.success) {
                console.log('Backend request succeeded: ', backendResponse.data);
                vscode.window.showInformationMessage('Backend simulation request processed successfully');
                const response_message = backendResponse.data;

                // step 1: process pred_snapshots
                const hunks = processInitPredSnapshots(response_message["pred_snapshots"]);
                const flowPattern = response_message.evaluations && response_message.evaluations.flow_pattern ? response_message.evaluations.flow_pattern : null;
                console.log('Initial hunk:', hunks);
                
                // step 2: update Predicted Locations
                //if (entropyScoreboardProvider) {
                //    entropyScoreboardProvider.addEntryFromResponse(response_message);
                //}
                
                // step 3: calculate evaluation metrics
                if (response_message.evaluations && response_message.evaluations.tp !== undefined) {
                    const { tp, fp, fn } = response_message.evaluations;
                    updateEvaluationMetrics(tp, fp, fn);
                    console.log(`Init step - Updated evaluation metrics - TP: ${tp}, FP: ${fp}, FN: ${fn}, Total - TP: ${totalTP}, FP: ${totalFP}, FN: ${totalFN}`);
                }
                
                // step 4: update Edit Flow Tracking
                //if (editFlowTrackingProvider && flowPattern) {
                //    editFlowTrackingProvider.updateFlowData(flowPattern, hunks, response_message.evaluations);
                //}
                return { hunks, flowPattern };
            } else {
                console.error('Backend request failed:', backendResponse.error);
                vscode.window.showErrorMessage('Backend request failed: ' + backendResponse.error);
                return { hunks: [], flowPattern: null };
            }
        } catch (err) {
            console.error('Backend request failed:', err);
            vscode.window.showErrorMessage('Backend request failed: ' + err.message);
            return { hunks: [], flowPattern: null };
        }
    }

async function simulateNextStep(commit_url, previousEdits, targetFileSegments, refFiles, systemUnderTest, suggestion_type, entropyScoreboardProvider, editFlowTrackingProvider) {
    if (isSimulationCompleted) {
        vscode.window.showInformationMessage('Simulation completed!');
        setTimeout(() => {
            showEvaluationMetrics();
        }, 1000);
        return { hunks: [], flowPattern: null };
    }
    try {
        const backendResponse = await sendBackendRequest(commit_url, systemUnderTest, "suggestion", suggestion_type);
        if (backendResponse.success) {
            vscode.window.showInformationMessage('✅ Backend system returned successfully');
            const response_message = backendResponse.data;
            if (response_message.status === "done") {
                isSimulationCompleted = true; 
            }
            console.log('simulateNextStep entropy:', response_message.evaluation_entropy?.entropy);
            // step 1: process pred_snapshots
            let hunks = processNextPredSnapshots(response_message["pred_snapshots"]);
            const hunk = processNextEditSnapshots(response_message["next_edit_snapshots"]);
            if (hunk && Array.isArray(hunks) && hunks.every(h => h.flowKeeping === false)) {
                hunks.push(hunk);
            }
            const flowPattern = response_message.evaluations && response_message.evaluations.flow_pattern ? response_message.evaluations.flow_pattern : null;
            console.log("Generated hunks list:", hunks);
            // step 2: update Predicted Locations
            if (entropyScoreboardProvider) {
                console.log('Calling addEntryFromResponse with entropyScoreboardProvider');
                entropyScoreboardProvider.addEntryFromResponse(response_message);
            } else {
                console.log('entropyScoreboardProvider is null or undefined');
            }
            
            // step 3: calculate evaluation metrics
            if (response_message.evaluations && response_message.evaluations.tp !== undefined) {
                const { tp, fp, fn } = response_message.evaluations;
                updateEvaluationMetrics(tp, fp, fn);
            }
            
            // step 4: update Edit Flow Tracking
            //if (editFlowTrackingProvider && flowPattern) {
            //    editFlowTrackingProvider.updateFlowData(flowPattern, hunks, response_message.evaluations);
            //} 
            // update Predicted Locations view
            if (predictedLocationsProvider && flowPattern) {
                predictedLocationsProvider.updateItems(hunks, flowPattern);
            }
            return { hunks, flowPattern };
        } else {
            vscode.window.showErrorMessage('Backend request failed: ' + backendResponse.error);
            return { hunks: [], flowPattern: null };
        }
    } catch (err) {
        vscode.window.showErrorMessage('Backend request failed: ' + err.message);
        return { hunks: [], flowPattern: null };
    }
}



// send request to backend
async function sendBackendRequest(commit_url, system_under_test, status, suggestion_type) {
    const https = require('https');
    const http = require('http');
    
    return new Promise((resolve, reject) => {
        const serverURL = getSimulationServerURL();
        const url = new URL(serverURL);
        // backend service configuration
        const backendConfig = {
            hostname: url.hostname,
            port: url.port,
            path: '/api/simulate',
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            }
        };
        
        const requestData = {
            commit_url: commit_url,
            system_under_test: system_under_test,
            status: status,
            suggestion_type: suggestion_type
        };
        
        console.log('Send request to backend:', requestData);
    
        const client = parseInt(url.port) === 443 ? https : http;
        
        const req = client.request(backendConfig, (res) => {
            let data = '';
            
            res.on('data', (chunk) => {
                data += chunk;
            });
            
            res.on('end', () => {
                try {
                    const response = JSON.parse(data);
                    resolve(response);
                } catch (error) {
                    reject(new Error('Failed to parse backend response: ' + error.message));
                }
            });
        });
        
        req.on('error', (error) => {
            reject(new Error('Failed to send request to backend: ' + error.message));
        });
    req.setTimeout(1000000, () => {
        req.destroy();
        reject(new Error('Request to backend timed out'));
    });
    
    // send request data
    req.write(JSON.stringify(requestData));
    req.end();
});
}


// --------------------
// Health Check Helpers
// --------------------
let firstSimulationSuccess = true;

function getSimulationServerURL() {
    const config = vscode.workspace.getConfiguration('digitalTwinSimulator');
    return config.get('serverURL', 'http://localhost:5001');
}

async function makeHttpRequest(url, options) {
    const https = require('https');
    const http = require('http');
    return new Promise((resolve, reject) => {
        const isHttps = url.startsWith('https://');
        const lib = isHttps ? https : http;
        const req = lib.request(url, { method: options?.method || 'GET', timeout: options?.timeout || 5000 }, (res) => {
            let data = '';
            res.on('data', (chunk) => { data += chunk; });
            res.on('end', () => resolve({ status: res.statusCode, body: data }));
        });
        req.on('timeout', () => { req.destroy(); reject(new Error('request timeout')); });
        req.on('error', (err) => reject(err));
        req.end();
    });
}

async function validateSimulationServerConnection(showMessage = true, retryInterval = 3000) {
    try {
        const serverURL = getSimulationServerURL();
        const response = await makeHttpRequest(`${serverURL}/health`, {
            method: 'GET',
            timeout: 5000
        });
        if (response.status === 200) {
            if (showMessage || firstSimulationSuccess) {
                vscode.window.showInformationMessage('✅ Successfully connected to Digital twin simulator server! 🎉');
            }
            firstSimulationSuccess = false;
            return true;
        } else {
            firstSimulationSuccess = true;
            vscode.window.showErrorMessage('❌ Digital twin simulator server connection failed: invalid response');
            setTimeout(() => {
                validateSimulationServerConnection(showMessage, retryInterval);
            }, retryInterval);
            return false;
        }
    } catch (error) {
        firstSimulationSuccess = true;
        vscode.window.showErrorMessage(`❌ Digital twin simulator server connection failed: ${error.message}`);
        setTimeout(() => {
            validateSimulationServerConnection(showMessage, retryInterval);
        }, retryInterval);
        return false;
    }
}


// batch locate
async function showLocation(hunks) {
    if (!Array.isArray(hunks)) {
        hunks = [hunks];
    }
    // for storing all decorations to be highlighted
    const decorationsOrange = new Map(); // flowKeeping==false
    const decorationsCyan = new Map();   // flowKeeping==true
    for (const hunk of hunks) {
        const files = await vscode.workspace.findFiles(hunk.file);
        if (files.length > 0) {
            const fileUri = files[0];
            const doc = await vscode.workspace.openTextDocument(fileUri);
            const hunkLines = hunk.hunkText.split('\n');
            let startLine = hunk.startLineAfter ;
            let firstDeletionLine = -1;
            let firstAdditionLine = -1;
            let hasDeletion = false;
            for (let i = 0; i < hunkLines.length; i++) {
                const line = hunkLines[i];
                if (line.startsWith('-')) {
                    hasDeletion = true;
                    if (firstDeletionLine === -1) {
                        firstDeletionLine = startLine + i;
                    }
                } else if (line.startsWith('+')) {
                    if (firstAdditionLine === -1) {
                        firstAdditionLine = startLine + i;
                    }
                }
            }
            let range;
            if (hasDeletion) {
                const deletions = hunkLines.filter(line => line.startsWith('-')).length;
                const endLine = firstDeletionLine + deletions - 1;
                range = new vscode.Range(firstDeletionLine, 0, endLine, 0);
            } else {
                range = new vscode.Range(firstAdditionLine, 0, firstAdditionLine, 0);
            }
            // group by flowKeeping
            const targetMap = hunk.flowKeeping ? decorationsCyan : decorationsOrange;
            if (!targetMap.has(fileUri.toString())) {
                targetMap.set(fileUri.toString(), []);
            }
            targetMap.get(fileUri.toString()).push(range);
        }
    }
    // apply decorations
    for (const [fileUriString, ranges] of decorationsOrange) {
        const fileUri = vscode.Uri.parse(fileUriString);
        let editor = vscode.window.visibleTextEditors.find(e => e.document.uri.toString() === fileUriString);
        if (!editor) {
            const doc = await vscode.workspace.openTextDocument(fileUri);
            editor = await vscode.window.showTextDocument(doc, {
                preview: false,
                preserveFocus: true,
                viewColumn: vscode.ViewColumn.Active
            });
        }
        editor.setDecorations(decorationType, ranges);
        highlightMapOrange.set(fileUriString, ranges);
    }
    for (const [fileUriString, ranges] of decorationsCyan) {
        const fileUri = vscode.Uri.parse(fileUriString);
        let editor = vscode.window.visibleTextEditors.find(e => e.document.uri.toString() === fileUriString);
        if (!editor) {
            const doc = await vscode.workspace.openTextDocument(fileUri);
            editor = await vscode.window.showTextDocument(doc, {
                preview: false,
                preserveFocus: true,
                viewColumn: vscode.ViewColumn.Active
            });
        }
        editor.setDecorations(decorationType1, ranges);
        highlightMapCyan.set(fileUriString, ranges);
    }
}
// automatically accept hunk
async function autoAcceptHunk(hunk) {
    const activeEditor = vscode.window.activeTextEditor;
    if (!activeEditor) return;
    const tempUri = activeEditor.document.uri;
    const originalUri = tempToOriginalMap.get(tempUri.toString());
    if (!originalUri) {
        vscode.window.showErrorMessage('The file was not found, the hunk cannot be applied. ');
        return;
    }
    const newContent = activeEditor.document.getText();
    // overwrite original file
    await vscode.workspace.fs.writeFile(originalUri, Buffer.from(newContent, 'utf8'));
    // delete temp file
    try { 
        fs.unlinkSync(tempUri.fsPath); 
        // clean up current temp file record
        if (currentTempFile === tempUri.fsPath) {
            currentTempFile = null;
        }
    } catch (e) { }
    // close diff view, open original file
    await vscode.commands.executeCommand('workbench.action.closeActiveEditor');
    const doc = await vscode.workspace.openTextDocument(originalUri);
    const editor = await vscode.window.showTextDocument(doc, { preview: false });
    //center display the recently modified line
    if (hunk) {
        const targetLine = getFirstChangedLine(hunk);
        const range = new vscode.Range(targetLine, 0, targetLine, 0);
        editor.revealRange(range, vscode.TextEditorRevealType.InCenter);
    }
}

// fetchDiff function removed - now using ChatModelEditParticipant to generate diff text

function parseDiff(diffText) {
    const hunks = [];

    // check if input is valid
    if (!diffText || typeof diffText !== 'string') {
        console.error('Invalid diff text:', diffText);
        vscode.window.showErrorMessage('Generated diff text is invalid');
        return hunks;
    }

    // detect diff format type
    if (diffText.includes('Index:') && diffText.includes('===')) {
        // process unified diff format (jsdiff.createPatch generated format)
        console.log('Detected unified diff format');
        return parseUnifiedDiff(diffText);
    } else if (diffText.includes('diff --git')) {
        // process git diff format
        console.log('Detected git diff format');
        return parseGitDiff(diffText);
    } else {
        console.warn('Unrecognized diff format:', diffText.substring(0, 200));
        vscode.window.showWarningMessage('Unrecognized diff format, please check the generated diff text');
        return hunks;
    }
}

// parse unified diff format (jsdiff.createPatch generated format)
function parseUnifiedDiff(diffText) {
    const hunks = [];

    console.log('Parsing unified diff, full text:', diffText);

    // split by file
    const fileBlocks = diffText.split(/^Index: /gm).filter(block => block.trim());
    console.log('File blocks found:', fileBlocks.length);

    for (let blockIndex = 0; blockIndex < fileBlocks.length; blockIndex++) {
        const block = fileBlocks[blockIndex];
        console.log(`Processing block ${blockIndex}:`, block.substring(0, 200));

        // extract file name
        const lines = block.split('\n');
        const fileName = lines[0].trim();
        console.log('Extracted fileName:', fileName);

        // find hunk header
        const hunkRegex = /@@ -(\d+)(?:,\d+)? \+(\d+)(?:,(\d+))? @@/g;
        let hunkMatch;
        const hunkHeaders = [];

        while ((hunkMatch = hunkRegex.exec(block)) !== null) {
            hunkHeaders.push({
                startLineBefore: parseInt(hunkMatch[1]),
                startLineAfter: parseInt(hunkMatch[2]),
                headerStart: hunkMatch.index,
                headerEnd: hunkMatch.index + hunkMatch[0].length
            });
        }

        console.log(`Found ${hunkHeaders.length} hunk headers in block ${blockIndex}`);

        for (let i = 0; i < hunkHeaders.length; i++) {
            const { startLineBefore, startLineAfter, headerEnd } = hunkHeaders[i];
            const hunkEnd = i + 1 < hunkHeaders.length ? hunkHeaders[i + 1].headerStart : block.length;

            const hunkContent = block.slice(headerEnd, hunkEnd);
            const hunkFirstLineBreak = Math.max(0, hunkContent.search('\n'));
            const hunkHeader = hunkContent.slice(0, hunkFirstLineBreak);
            const hunkText = hunkContent.slice(hunkFirstLineBreak + 1);

            console.log('Parsed unified diff hunk:', hunkText);

            hunks.push({
                file: fileName,
                startLineBefore: startLineBefore,
                startLineAfter: startLineAfter,
                hunkHeader: hunkHeader,
                hunkText: hunkText
            });
        }
    }

    console.log(`Total hunks parsed: ${hunks.length}`);
    return hunks;
}

// parse git diff format (original logic)
function parseGitDiff(diffText) {
    const hunks = [];
    const fileBlocks = diffText.split(/^diff --git /gm);

    for (const block of fileBlocks) {
        const fileMatch = block.match(/^a\/(.+?) b\/(.+?)$/m);
        if (!fileMatch) continue;
        const file = fileMatch[2];

        const hunkRegex = /@@ -(\d+)(?:,\d+)? \+(\d+)(?:,(\d+))? @@/g;
        let hunkMatch;
        const hunkHeaders = [];

        while ((hunkMatch = hunkRegex.exec(block)) !== null) {
            hunkHeaders.push({
                startLineBefore: parseInt(hunkMatch[1]),
                startLineAfter: parseInt(hunkMatch[2]),
                headerStart: hunkMatch.index,
                headerEnd: hunkMatch.index + hunkMatch[0].length
            });
        }

        for (let i = 0; i < hunkHeaders.length; i++) {
            const { startLineBefore, startLineAfter, headerEnd } = hunkHeaders[i];
            const hunkEnd = i + 1 < hunkHeaders.length ? hunkHeaders[i + 1].headerStart : block.length;

            const hunkContent = block.slice(headerEnd, hunkEnd);
            const hunkFirstLineBreak = Math.max(0, hunkContent.search('\n'));
            const hunkHeader = hunkContent.slice(0, hunkFirstLineBreak);
            const hunkText = hunkContent.slice(hunkFirstLineBreak + 1);

            hunks.push({
                file: file,
                startLineBefore: startLineBefore,
                startLineAfter: startLineAfter,
                hunkHeader: hunkHeader,
                hunkText: hunkText
            });
        }
    }

    return hunks;
}


// calculate the line number to be centered
function getFirstChangedLine(hunk) {
    const hunkLines = hunk.hunkText.split('\n');
    for (let i = 0; i < hunkLines.length; i++) {
        if (hunkLines[i].startsWith('-') || hunkLines[i].startsWith('+')) {
            return hunk.startLineAfter + i;
        }
    }
    // fallback
    return hunk.startLineAfter;
}

// after diff view is opened, center display the target line
async function revealHunkInEditors(hunk, tempUri, originalUri) {
    const targetLine = getFirstChangedLine(hunk);
    // wait for editor to render
    await new Promise(resolve => setTimeout(resolve, 200));
    for (const editor of vscode.window.visibleTextEditors) {
        if (
            editor.document.uri.toString() === tempUri.toString() ||
            editor.document.uri.toString() === originalUri.toString()
        ) {
            const range = new vscode.Range(targetLine, 0, targetLine, 0);
            editor.revealRange(range, vscode.TextEditorRevealType.InCenter);
        }
    }
}

async function showHunkDiff(hunk) {
    if (currentTempFile) {
        try {
            fs.unlinkSync(currentTempFile);
        } catch (e) {
            console.log('Failed to delete temp file:', e.message);
        }
        currentTempFile = null;
    }

    const files = await vscode.workspace.findFiles(hunk.file);
    if (!hunk.hunkText || typeof hunk.hunkText !== 'string') {
        console.error('hunk.hunkText is not a string', hunk);
        return;
    }

    if (files.length > 0) {
        const doc = await vscode.workspace.openTextDocument(files[0]);
        const originalContent = doc.getText();
        const originalLines = originalContent.split('\n');
        const newLines = applyHunkToContent(originalLines, hunk);
        const newContent = newLines.join('\n');

        // create temp file, for displaying diff page
        const tempFileName = `hunk0-${Date.now()}-${path.basename(hunk.file)}`;
        const tempFilePath = path.join(os.tmpdir(), tempFileName);
        fs.writeFileSync(tempFilePath, newContent, 'utf8');
        const tempUri = vscode.Uri.file(tempFilePath);

        // record current temp file
        currentTempFile = tempFilePath;

        // record mapping
        tempToOriginalMap.set(tempUri.toString(), doc.uri);

        // open diff view
        await vscode.commands.executeCommand(
            'vscode.diff',
            doc.uri,
            tempUri,
            `${path.basename(hunk.file)} (Hunk Preview)`
        );
        // center display
        await revealHunkInEditors(hunk, tempUri, doc.uri);
    } else {
        vscode.window.showErrorMessage('The corresponding file was not found: ' + hunk.file);
    }
}


function applyHunkToContent(originalLines, hunk) {
    const hunkLines = hunk.hunkText.split('\n');
    const hasDeletions = hunkLines.some(line => 
        line.startsWith('-') && !line.startsWith('---')
    );
    let origLine
    origLine = hunk.startLineAfter ;
    let result = originalLines.slice(0, origLine);
    for (const line of hunkLines) {
        if (line.startsWith('+') && !line.startsWith('+++')) {
            result.push(line.substring(1));
        } else if (line.startsWith('-') && !line.startsWith('---')) {
            // check if the deleted line and the original file content are consistent
            const expected = line.substring(1);
            const actual = originalLines[origLine];
            origLine++;
        } else if (line.startsWith(' ')) {
            result.push(originalLines[origLine]);
            origLine++;
        }
    }
    // concatenate remaining content
    result = result.concat(originalLines.slice(origLine));
    return result;
}

// process pred_snapshots data, extract modification information and convert to hunks format
function processInitPredSnapshots(pred_snapshots) {
    const allKeys = Object.keys(pred_snapshots);
    for (const filePath of allKeys) {
        const fileData = pred_snapshots[filePath];
        
        if (Array.isArray(fileData) && fileData.length > 1) {
            for (let i = 1; i < fileData.length; i++) {
                const item = fileData[i];
                if (item && typeof item === 'object' && 
                    item.parent_version_range && 
                    item.parent_version_range.start !== undefined &&
                    item.before && 
                    item.after) {
                    
                    const parentStartLine = item.parent_version_range.start;
                    const childStartLine = item.child_version_range ? item.child_version_range.start : parentStartLine;
                    
                    const removedLines = item.before.map(line => `-${line}`);
                    const addedLines = item.after.map(line => `+${line}`);
                    
                    // merge to hunkText
                    const textRemoveAddLines = [...removedLines, ...addedLines];
                    const displayHunk = {
                        file: filePath,
                        startLineBefore: parentStartLine,
                        startLineAfter: childStartLine,
                        hunkHeader: "",                   //not needed
                        hunkText: textRemoveAddLines.join('\n'),
                        flowKeeping: true,
                        modelMake: true,
                        idx: item.idx !== undefined ? item.idx : 0,
                    };

                    return [displayHunk];
                }
            }
        }
    }
    console.warn('No valid evaluation data found in pred_snapshots');
    return [];
}

function processNextPredSnapshots(pred_snapshots) {
    const hunks = [];
    const allKeys = Object.keys(pred_snapshots);
    for (const filePath of allKeys) {
        const arr = pred_snapshots[filePath];
        let parentLine = 0;
        let childLine = 0;
        for (const item of arr) {
            if (Array.isArray(item)) {
                parentLine += item.length;
                childLine += item.length;
            } else if (
                item &&
                typeof item === 'object' &&
                Array.isArray(item.before) &&
                Array.isArray(item.after)
            ) {
                const { before, after, flowKeeping, idx, confidence } = item;
                const removedLines = before.map(line => `-${line}`);
                const addedLines = after.map(line => `+${line}`);
                const textRemoveAddLines = [...removedLines, ...addedLines];
                const displayHunk = {
                    file: filePath,
                    startLineBefore: parentLine,
                    startLineAfter: parentLine,
                    hunkHeader: '',
                    hunkText: textRemoveAddLines.join('\n'),
                    flowKeeping: flowKeeping === true,
                    modelMake: true,
                    idx: idx !== undefined ? idx : hunks.length,
                    confidence: confidence !== undefined ? confidence : 0
                };
                hunks.push(displayHunk);
                parentLine += before.length;
                childLine += after.length;
            }
        }
    }
    return hunks;
}

function processNextEditSnapshots(next_edit_snapshots) {
    const allKeys = Object.keys(next_edit_snapshots);
    for (const filePath of allKeys) {
        const arr = next_edit_snapshots[filePath];
        for (const item of arr) {
            if (item && typeof item === 'object' && Array.isArray(item.before) && Array.isArray(item.after)) {
                // find target structure
                const parentStartLine = item.parent_version_range ? item.parent_version_range.start : 0;
                const childStartLine = item.child_version_range ? item.child_version_range.start : 0;
                const removedLines = item.before.map(line => `-${line}`);
                const addedLines = item.after.map(line => `+${line}`);
                const textRemoveAddLines = [...removedLines, ...addedLines];
                const displayHunk = {
                    file: filePath,
                    startLineBefore: parentStartLine,
                    startLineAfter: childStartLine,
                    hunkHeader: "",
                    hunkText: textRemoveAddLines.join('\n'),
                    flowKeeping: true,
                    modelMake: false
                };
                return displayHunk;
            }
        }
    }
    console.log('No more hunks');
    vscode.window.showInformationMessage('No more hunks, simulation completed!');
    return null;
}
// test function - for validating diff parsing
function testDiffParsing() {
    const testDiff = `Index: keras/layers/core.py
===================================================================
--- keras/layers/core.py
+++ keras/layers/core.py
@@ -78,6 +78,8 @@
-    def __init__(self, p, **kwargs):
+    def __init__(self, p, noise_shape=None, seed=None, **kwargs):
         self.p = p
+        self.noise_shape = noise_shape
+        self.seed = seed
         if 0. < self.p < 1.:
             self.uses_learning_phase = True
         self.supports_masking = True
         super(Dropout, self).__init__(**kwargs)
`;

    console.log('Testing diff parsing with example diff...');
    const hunks = parseDiff(testDiff);
    console.log('Test result - hunks found:', hunks.length);
    hunks.forEach((hunk, index) => {
        console.log(`Hunk ${index}:`, hunk);
    });

    return hunks;
}

module.exports = {
    Simulate,
    initializeSimulationView,
    processNextPredSnapshots,
    testDiffParsing, 
    allHunks, 
    revealHunkInEditors,
    applyHunkToContent,
    validateSimulationServerConnection,
    isSimulationCompleted,
    resetSimulation: () => { isSimulationCompleted = false; }
};