const vscode = require('vscode');
const path = require('path');
const os = require('os');
const crypto = require('crypto');
const http = require('http');
const https = require('https');
const fs = require('fs');
const { processMultiFileVersions } = require('./alg.js');
const { SimpleTreeDataProvider} = require('./simulatorViewProvider.js');
const{ revealHunkInEditors }= require('./simulate.js');
const { applyHunkToContent } = require('./simulate.js');
const tempToOriginalMap = new Map();

const tempToHunkMap = new Map();
let currentHunks = [];
let SuggestionLocationsProvider = null;
let selectedSystemUnderTest = null; 
let viewInitialized = false;
let decorationType = null;
let decorationType1 = null;
let currentTempFile = null;
let highlightMapGreen = new Map();
let highlightMapRed = new Map();
let projectName = null;
let userId = null;
let fileTracker = {
    snapshotsByFile: {},
    timestamp: 0,
    timer: null,
    isInitialized: false,
    lastSuccessfulSnapshot: null
};
let activeEditorListener = null;

function getOrCreateUserId() {
    if (userId) return userId;
    try {
        const username = os.userInfo().username || 'unknown_user';
        const hostname = os.hostname() || 'unknown_host';
        const seed = `${username}@${hostname}`;
        userId = crypto.createHash('sha256').update(seed).digest('hex');
    } catch (e) {
        userId = crypto.randomBytes(16).toString('hex');
    }
    return userId;
}

// get snapshot of a file
async function getFileSnapshot(fileUri) {
    try {
        const bytes = await vscode.workspace.fs.readFile(fileUri);
        try {
            const content = Buffer.from(bytes).toString('utf8');
            const lines = content.split('\n').map(line => line + '\n');
            return [lines];
        } catch (textError) {
            return bytes;
        }
    } catch (error) {
        console.warn(`Failed to read file: ${fileUri.fsPath}`, error);
        return [];
    }
}
 
// Only record files in the workspace
function isPathInside(baseDir, targetPath) {
	const rel = path.relative(baseDir, targetPath);
	return rel && !rel.startsWith('..') && !path.isAbsolute(rel);
}

// record file snapshot
/**
 * fileTracker.snapshotsByFile:
 * {
 *   "file_path": {                
 *     versions: [                 
 *       ["line1\n", "line2\n", ...],
 *       ["line1\n", "line3\n", ...]
 *     ],
 *     timestamps: [0, 1, 2, ...]
 *   },
 *
 * }
 */
async function recordFileSnapshot(fileUri) {
	if (!fileTracker.isInitialized) return;
	const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
	if (!workspaceFolder) return;
	const rootPath = workspaceFolder.uri.fsPath;
	if (!isPathInside(rootPath, fileUri.fsPath)) {
		console.log(`skip non-workspace file: ${fileUri.fsPath}`);
		return;
	}

	const filePath = path.relative(rootPath, fileUri.fsPath).replace(/\\/g, '/');
	const beforesnapshot = await getFileSnapshot(fileUri);
	const snapshot = Array.isArray(beforesnapshot) && beforesnapshot.length === 1 && Array.isArray(beforesnapshot[0])
		? beforesnapshot[0]
		: beforesnapshot;
	if (snapshot.length > 0) {
		if (!fileTracker.snapshotsByFile[filePath]) {
			fileTracker.snapshotsByFile[filePath] = {
				versions: [],
				timestamps: []
			};
		}
		fileTracker.snapshotsByFile[filePath].versions.push(snapshot);
		fileTracker.snapshotsByFile[filePath].timestamps.push(fileTracker.timestamp);
		fileTracker.timestamp++;
	}
	return;
}

// record all open files versions
async function recordAllOpenFilesVersions() {
	if (!fileTracker.isInitialized) return;
	
	try {
		const openEditors = vscode.workspace.textDocuments;
		const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
		const rootPath = workspaceFolder?.uri.fsPath;

		for (const editor of openEditors) {
			if (editor.uri.scheme === 'file' && rootPath && isPathInside(rootPath, editor.uri.fsPath)) {
				await recordFileSnapshot(editor.uri);
			}
		}
		
	} catch (error) {
		console.warn('Failed to record all open files versions:', error);
	}
}
function startFileTracking() {
    // supervise file changes
    activeEditorListener = vscode.window.onDidChangeActiveTextEditor(async (editor) => {
        if (editor && editor.document.uri.scheme === 'file') {
            await recordFileSnapshot(editor.document.uri);
        }
    });
    
    // Add listener for file save events
    const saveListener = vscode.workspace.onDidSaveTextDocument(async (document) => {
        if (document.uri.scheme === 'file') {
            // Record version when a file is saved
            await recordFileSnapshot(document.uri);
        }
    });
    // set up a timer to periodically record all open files versions
    fileTracker.timer = setInterval(async () => {
        await recordAllOpenFilesVersions();
    }, 30000);
}

function stopFileTracking() {
    if (activeEditorListener) {
        activeEditorListener.dispose();
        activeEditorListener = null;
    }
    if (fileTracker.timer) {
        clearInterval(fileTracker.timer);
        fileTracker.timer = null;
    }
    fileTracker.isInitialized = false;
}

//restart file tracking
function restartFileTracking() {
    fileTracker.isInitialized = true;
    fileTracker.timestamp = 0;
    fileTracker.snapshotsByFile = {};
    fileTracker.lastSuccessfulSnapshot = null;
    recordAllOpenFilesVersions();
    
    startFileTracking();
    console.log('File tracking started');
}


async function snapshotWorkspaceFolder() {
    const root = vscode.workspace.workspaceFolders?.[0];
    if (!root) throw new Error('No workspace is open');
    projectName = path.basename(root.uri.fsPath);
    return await vscode.window.withProgress({
        location: vscode.ProgressLocation.Notification,
        title: 'Creating workspace snapshot...',
        cancellable: false
    }, async (progress) => {
        // get all files
        const uris = await vscode.workspace.findFiles('**/*', '**/.git/**');
        const totalFiles = uris.length;
        const projectSnapshot = {};

        // simple concurrency pool
        const concurrency = 20; // adjust as needed
        const queue = [...uris];

        async function worker() {
            while (queue.length > 0) {
                const uri = queue.pop();
                if (!uri) continue;
                try {
                    const rel = path.relative(root.uri.fsPath, uri.fsPath).replace(/\\/g, '/');
                    projectSnapshot[rel] = await getFileSnapshot(uri);
                } catch (e) {
                    console.warn(`Failed to read file: ${uri.fsPath}`, e);
                }
                progress.report({
                    increment: (100 / totalFiles)
                });
            }
        }

        // run workers in parallel
        await Promise.all(Array.from({ length: concurrency }, () => worker()));

        return projectSnapshot;
    });
}

//step 1: initialize Flow-keeper
async function initializeFlowKeeper(systemUnderTest) {
    if (!systemUnderTest || (systemUnderTest !== 'CoEdPilot' && systemUnderTest !== 'Claude')) {
        throw new Error('Invalid system under test');
    }
    selectedSystemUnderTest = systemUnderTest;
    const projectSnapshot = await snapshotWorkspaceFolder();
    getOrCreateUserId();
    // initialize simulation view
    restartFileTracking();
    const inputdata = buildOptimizationInput('init', projectName, projectSnapshot, null);
    // show progress bar
    await vscode.window.withProgress({
        location: vscode.ProgressLocation.Notification,
        title: 'Initializing Flow-keeper...',
        cancellable: false
    }, async () => {
        try {
            return await sendOptimizationRequest(inputdata);
        } catch (error) {
            vscode.window.showErrorMessage(`Failed to initialize Flow-keeper: ${error.message}`);
            throw error;
        }
    });
    vscode.window.showInformationMessage(`Flow-keeper initialized for ${systemUnderTest}.`);
}

function initializeSimulationView(context){
    if (!viewInitialized) {
        SuggestionLocationsProvider = new SimpleTreeDataProvider();
        
        context.subscriptions.push(
            vscode.window.createTreeView('flowKeeper.Tracking', {
                treeDataProvider: SuggestionLocationsProvider,
                showCollapseAll: true
            })
        );

        decorationType = vscode.window.createTextEditorDecorationType({
            backgroundColor: 'rgba(0,255,0,0.3)',
            isWholeLine: true
        });

        decorationType1 = vscode.window.createTextEditorDecorationType({
            backgroundColor: 'rgba(255,0,0,0.3)',
            isWholeLine: true
        });

        context.subscriptions.push(
            vscode.window.onDidChangeActiveTextEditor(editor => {
                if (!editor) return;
                const fileUri = editor.document.uri.toString();
                if (highlightMapGreen.has(fileUri)) {
                    editor.setDecorations(decorationType, highlightMapGreen.get(fileUri));
                } else {
                    editor.setDecorations(decorationType, []);
                }
                if (highlightMapRed.has(fileUri)) {
                    editor.setDecorations(decorationType1, highlightMapRed.get(fileUri));
                } else {
                    editor.setDecorations(decorationType1, []);
                }
            })
        );
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
        context.subscriptions.push(
            vscode.commands.registerCommand('flow-keeper.showHunkDiff', async (hunk) => {
                if (hunk) {
                    await showHunkDiff(hunk);
                }
            })
        );
        viewInitialized = true;
    }
}

async function generateEditSnapshot() {
    const editSnapshot = processMultiFileVersions(fileTracker.snapshotsByFile);
    return editSnapshot;
}

async function runOptimization(context, editDescription) {
    await vscode.workspace.saveAll();
    
    initializeSimulationView(context);
    clearAllDecorations();
    tempToHunkMap.clear();
    // save all open files versions before generating edit snapshot
    await recordAllOpenFilesVersions();
    const editSnapshot = await generateEditSnapshot();
    const inputPayload = buildOptimizationInput('suggestion', projectName, editSnapshot, editDescription);

    let result;
    try {
        result = await vscode.window.withProgress({
            location: vscode.ProgressLocation.Notification,
            title: 'Requesting next edit suggestion...',
            cancellable: false
        }, async () => {
            try {
                return await sendOptimizationRequest(inputPayload);
            } catch (innerError) {
                console.error(`The request processing failed.: ${innerError.message}`);
                vscode.window.showErrorMessage(`The request processing failed.: ${innerError.message}`);
                throw innerError; 
            }
        });
    } catch (error) {
        console.error('optimization failed:', error);
        result = null;
        return; 
    }
    if (result["data"] && Object.keys(result["data"]).length === 0) {
        vscode.window.showInformationMessage('Backend detected no changes. Revise prompt to make model think again.');
        return;
    }
    currentHunks = await processResult(result["data"]);

    await showHunksLocation(currentHunks);
    SuggestionLocationsProvider.updateItems(currentHunks);
    
    // Auto switch to sidebar view
    try {
        await vscode.commands.executeCommand('workbench.view.extension.Flow-keeper');
    } catch (error) {
        console.log('Failed to switch to Flow-keeper sidebar:', error.message);
    }

}

function buildOptimizationInput(status, projectName, editSnapshot, editDescription) {
    if (!selectedSystemUnderTest) throw new Error('Flow-keeper is not initialized. Please run Flow-keeper: Suggest Next Edit first.');
    if (!editSnapshot) throw new Error('Edit snapshot is missing. Please re-initialize Flow-keeper.');
  
    const id = getOrCreateUserId();
  
    return {
        id,
        system_under_test: selectedSystemUnderTest,
        status,
        project_name: projectName,
        project: editSnapshot,
        edit_description: editDescription || null
    };
}
  
async function sendOptimizationRequest(inputPayload) {
    const serverURL = getOptimizationServerURL();
    const url = new URL(serverURL);

    const backendConfig = {
        hostname: url.hostname,
        port: parseInt(url.port),
        path: '/api/optimization',
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        }
    };
  
    const client = backendConfig.port === 443 ? https : http;
  
    return new Promise((resolve, reject) => {
        const req = client.request(backendConfig, (res) => {
            let data = '';
            res.on('data', chunk => (data += chunk));
            res.on('end', () => {
                try {
                    const parsed = JSON.parse(data || '{}');
                    if (res.statusCode >= 400) {
                        reject(new Error(`HTTP ${res.statusCode}: ${parsed.error || 'Server error'}`));
                    } else if (parsed.success === false) {
                        reject(new Error(parsed.error || 'Backend processing failed'));
                    } else {
                        resolve(parsed);
                    }
                } catch (e) {
                    reject(new Error('Failed to parse backend response: ' + e.message));
                }
            });
        });
        req.on('error', (err) => reject(new Error('Failed to send request to backend: ' + err.message)));
        req.setTimeout(300000, () => {
            req.destroy();
            reject(new Error('Request timed out'));
        });
        req.write(JSON.stringify(inputPayload));
        req.end();
    });
}

async function processResult(pred_snapshots) {
    const hunks = [];
    const allKeys = Object.keys(pred_snapshots);
    for (const filePath of allKeys) {
        const arr = pred_snapshots[filePath];
        let parentLine = 0;
        let childLine = 0;
        for (const item of arr) {
            // Skip hunks when both before and after are empty
            if (item && typeof item === 'object' && Array.isArray(item.before) && Array.isArray(item.after)) {
                const beforeVal = item.before;
                const afterVal = item.after;
                const isBeforeEmptyArray = Array.isArray(beforeVal) && beforeVal.length === 0;
                const isAfterEmptyArray = Array.isArray(afterVal) && afterVal.length === 0;
                const isBeforeEmptyObject = beforeVal && typeof beforeVal === 'object' && !Array.isArray(beforeVal) && Object.keys(beforeVal).length === 0;
                const isAfterEmptyObject = afterVal && typeof afterVal === 'object' && !Array.isArray(afterVal) && Object.keys(afterVal).length === 0;
                if ((isBeforeEmptyArray || isBeforeEmptyObject) && (isAfterEmptyArray || isAfterEmptyObject)) {
                    console.log(`Skip empty hunk: file=${filePath}, idx=${item.idx !== undefined ? item.idx : 'unknown'}`);
                    continue;
                }
            }
            if (Array.isArray(item)) {
                parentLine += item.length;
                childLine += item.length;
            } else if (
                item &&
                typeof item === 'object' &&
                Array.isArray(item.before) &&
                Array.isArray(item.after)
            ) {
                const { before, after, idx, long_reason, short_reason, corresponding_prev_edit } = item;
                const removedLines = before.map(line => `-${line}`);
                const addedLines = after.map(line => `+${line}`);
                const textRemoveAddLines = [...removedLines, ...addedLines];
                const displayHunk = {
                    file: filePath,
                    startLineBefore: parentLine,
                    startLineAfter: parentLine,
                    lineAfter: childLine,
                    hunkHeader: '',
                    hunkText: textRemoveAddLines.join('\n'),
                    idx: idx !== undefined ? idx : hunks.length,
                    long_reason: long_reason || '',
                    short_reason: short_reason || '',
                    corresponding_prev_edit: corresponding_prev_edit || ''
                };
                hunks.push(displayHunk);
                parentLine += before.length;
                childLine += after.length;
            }
        }
    }
    return hunks;
}

async function showHunksLocation(hunks) {
    if (!Array.isArray(hunks)) {
        hunks = [hunks];
    }
    // store decorations in maps
    const decorationsGreen = new Map(); 
    const decorationsRed = new Map();
    for (const hunk of hunks) {
        const files = await vscode.workspace.findFiles(hunk.file);
        if (files.length > 0) {
            const fileUri = files[0];
            const doc = await vscode.workspace.openTextDocument(fileUri);
            const hunkLines = hunk.hunkText.split('\n');
            const originalContent = doc.getText();
            const originalLines = originalContent.split('\n');
            let firstDeletionContent = null;
            for (const line of hunkLines) {
                if (line.startsWith('-') && !line.startsWith('---')) {
                    firstDeletionContent = line.substring(1);
                    break;
                }
            }
            let startLine = hunk.startLineAfter; 
            let contentMatchFound = false;
            
            if (firstDeletionContent) {
                const removeNewlines = (str) => str.replace(/[\r\n]/g, '');
                const targetContent = removeNewlines(firstDeletionContent);
                const parentLine = hunk.startLineBefore;
                const childLine = hunk.lineAfter;
                const minLine = Math.min(parentLine, childLine);
                const maxLine = Math.max(parentLine, childLine);
                const exactMatches = [];
                const fuzzyMatches = [];

                for (let i = 0; i < originalLines.length; i++) {
                    const originalLineProcessed = removeNewlines(originalLines[i]);
                    if (originalLineProcessed === targetContent) {
                        if (i >= minLine && i <= maxLine) {
                            startLine = i; 
                            contentMatchFound = true;
                            hunk.startLineAfter = i;
                            break;
                        } else {
                            exactMatches.push(i);
                        }
                    }
                }
                if (!contentMatchFound) {
                    const trimmedContent = firstDeletionContent.trim();
                    for (let i = 0; i < originalLines.length; i++) {
                        if (originalLines[i].trim() === trimmedContent) {
                            if (i >= minLine && i <= maxLine) {
                                startLine = i; 
                                contentMatchFound = true;
                                hunk.startLineAfter = i;
                                break;
                            } else {
                                fuzzyMatches.push(i);
                            }
                        }
                    }
                }
                if (!contentMatchFound) {
                    let bestMatch = null;
                    let minDistance = Infinity;
                    if (exactMatches.length > 0) {
                        for (const lineNum of exactMatches) {
                            const distance = Math.min(Math.abs(lineNum - minLine), Math.abs(lineNum - maxLine));
                            if (distance < minDistance) {
                                minDistance = distance;
                                bestMatch = lineNum;
                            }
                        }
                    } else if (fuzzyMatches.length > 0) {
                        for (const lineNum of fuzzyMatches) {
                            const distance = Math.min(Math.abs(lineNum - minLine), Math.abs(lineNum - maxLine));
                            if (distance < minDistance) {
                                minDistance = distance;
                                bestMatch = lineNum;
                            }
                        }
                    }
                    
                    if (bestMatch !== null) {
                        startLine = bestMatch;
                        contentMatchFound = true;
                        hunk.startLineAfter = bestMatch;
                    } else {
                        console.log(`Match failed for hunk:`, {
                            file: hunk.file,
                            startLineBefore: hunk.startLineBefore,
                            startLineAfter: hunk.startLineAfter,
                            idx: hunk.idx,
                        });
                    }
                }
            }
            
            let firstDeletionLine = -1;
            let firstAdditionLine = -1;
            let hasDeletion = false;
            let hunkLineOffset = 0; 
            for (let i = 0; i < hunkLines.length; i++) {
                const line = hunkLines[i];
                if (line.startsWith('-')) {
                    hasDeletion = true;
                    if (firstDeletionLine === -1) {
                        firstDeletionLine = startLine + hunkLineOffset;
                    }
                    hunkLineOffset++; 
                } else if (line.startsWith('+')) {
                    if (firstAdditionLine === -1) {
                        firstAdditionLine = startLine + hunkLineOffset;
                    }
                } else if (!line.startsWith('@@') && !line.startsWith('---') && !line.startsWith('+++')) {
                    hunkLineOffset++;
                }
            }
            let range;
            if (hasDeletion) {
                const deletions = hunkLines.filter(line => line.startsWith('-')).length;
                const endLine = firstDeletionLine + deletions - 1;
                if (firstDeletionLine >= 0 && endLine >= 0) {
                    range = new vscode.Range(firstDeletionLine, 0, endLine, 0);
                } else {
                    console.warn(`Invalid deletion line numbers: firstDeletionLine=${firstDeletionLine}, endLine=${endLine}`);
                    continue;
                }
            } else {
                if (firstAdditionLine >= 0) {
                    range = new vscode.Range(firstAdditionLine, 0, firstAdditionLine, 0);
                } else {
                    console.warn(`Invalid addition line number: firstAdditionLine=${firstAdditionLine}`);
                    continue; 
                }
            }
            const allLinesAreAdditions = hunkLines.every(line => 
                line.startsWith('+') || line.trim() === '' 
            );
            const targetMap = allLinesAreAdditions ? decorationsGreen : decorationsRed;
            
            if (!targetMap.has(fileUri.toString())) {
                targetMap.set(fileUri.toString(), []);
            }
            targetMap.get(fileUri.toString()).push(range);
        }
    }
    // apply decorations to editors
    for (const [fileUriString, ranges] of decorationsGreen) {
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
        highlightMapGreen.set(fileUriString, ranges);
    }
    for (const [fileUriString, ranges] of decorationsRed) {
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
        highlightMapRed.set(fileUriString, ranges);
    }
}

async function cleanupTempFileAndEditors() {
    if (currentTempFile) {
        const tempUri = vscode.Uri.file(currentTempFile);
        const tempUriString = tempUri.toString();
        const editors = vscode.window.visibleTextEditors.filter(editor => 
            editor.document.uri.toString() === tempUriString
        );
        for (const editor of editors) {
            try {
                await vscode.commands.executeCommand('workbench.action.closeActiveEditor');
            } catch (e) {
                console.log('Failed to close editor:', e.message);
            }
        }
        try {
            fs.unlinkSync(currentTempFile);
        } catch (e) {
            console.log('Failed to delete temp file:', e.message);
        }
        currentTempFile = null;
    }
}
async function showHunkDiff(hunk) {
    // close previous diff first; the onDidCloseTextDocument listener will record previous view time
    await cleanupTempFileAndEditors();
    
    const files = await vscode.workspace.findFiles(hunk.file);
    if (!hunk.hunkText || typeof hunk.hunkText !== 'string') {
        console.error('hunk.hunkText is not string', hunk);
        return;
    }
    if (files.length > 0) {
        const doc = await vscode.workspace.openTextDocument(files[0]);
        const originalContent = doc.getText();
        const originalLines = originalContent.split('\n');
        const newLines = applyHunkToContent(originalLines, hunk);
        const newContent = newLines.join('\n');
        // create a temporary file
        const tempFileName = `hunk1-${Date.now()}-${path.basename(hunk.file)}`;
        const tempFilePath = path.join(os.tmpdir(), tempFileName);
        fs.writeFileSync(tempFilePath, newContent, 'utf8');
        const tempUri = vscode.Uri.file(tempFilePath);
        currentTempFile = tempFilePath;
        tempToOriginalMap.set(tempUri.toString(), doc.uri);
        tempToHunkMap.set(tempUri.toString(), hunk);
        // open diff view
        await vscode.commands.executeCommand(
            'vscode.diff',
            doc.uri,
            tempUri,
            `${path.basename(hunk.file)} (Hunk Preview)`,
            {
                preview: false,
                viewColumn: vscode.ViewColumn.Active
            }
        );
        // reveal the hunk in center
        await revealHunkInEditors(hunk, tempUri, doc.uri);
    } else {
        vscode.window.showErrorMessage('The corresponding file was not found: ' + hunk.file);
    }
}

// 
function clearAllDecorations() {
    for (const [fileUriString, ranges] of highlightMapGreen) {
        const editor = vscode.window.visibleTextEditors.find(e => e.document.uri.toString() === fileUriString);
        if (editor) {
            editor.setDecorations(decorationType, []);
        }
    }
    highlightMapGreen.clear();
    for (const [fileUriString, ranges] of highlightMapRed) {
        const editor = vscode.window.visibleTextEditors.find(e => e.document.uri.toString() === fileUriString);
        if (editor) {
            editor.setDecorations(decorationType1, []);
        }
    }
    highlightMapRed.clear();
}

// accept the diff and apply changes to original file
async function acceptDiff() {
    try {
        clearAllDecorations();
        if (currentTempFile) {
            try {
                fs.unlinkSync(currentTempFile);
            } catch (e) {
                console.log('Failed to delete temp flie:', e.message);
            }
            currentTempFile = null;
        }
        const activeEditor = vscode.window.activeTextEditor;
        if (activeEditor && activeEditor.document.uri.scheme === 'file') {
            const tempUriString = activeEditor.document.uri.toString();
            const originalUri = tempToOriginalMap.get(tempUriString);
            
            if (originalUri) {
                const tempContent = activeEditor.document.getText();
                const originalUriObj = vscode.Uri.parse(originalUri);
                await vscode.workspace.fs.writeFile(originalUriObj, Buffer.from(tempContent, 'utf8'));
                await vscode.commands.executeCommand('workbench.action.closeActiveEditor');
                const originalDoc = await vscode.workspace.openTextDocument(originalUriObj);
                await vscode.window.showTextDocument(originalDoc, {
                    preview: false,
                    viewColumn: vscode.ViewColumn.Active
                });
                tempToOriginalMap.delete(tempUriString);
                vscode.window.showInformationMessage('Edit suggestion accepted ✅');
                //update the current hunks
                const acceptedHunk = tempToHunkMap.get(tempUriString);
                if (acceptedHunk) {
                    tempToHunkMap.delete(tempUriString);
                    if (acceptedHunk.idx !== undefined) {
                        currentHunks = currentHunks.filter(h => h.idx !== acceptedHunk.idx);
                    } else {
                        currentHunks = currentHunks.filter(h => !(h.file === acceptedHunk.file && h.hunkText === acceptedHunk.hunkText && h.startLineAfter === acceptedHunk.startLineAfter));
                    }
                    if (currentHunks.length > 0) {
                        await showHunksLocation(currentHunks);
                        SuggestionLocationsProvider.updateItems(currentHunks);
                    } else {
                        SuggestionLocationsProvider.updateItems([]);
                    }
                }
            }
        }
    }catch (error) {
        console.error('Failed to accept diff:', error);
        vscode.window.showErrorMessage(`Failed to accept diff: ${error.message}`);
    }
}

// reject the diff
async function rejectDiff() {
	try {
		clearAllDecorations();
		if (currentTempFile) {
			try {
				fs.unlinkSync(currentTempFile);
			} catch (e) {
				console.log('Failed to delete temp file:', e.message);
			}
			currentTempFile = null;
		}
		const activeEditor = vscode.window.activeTextEditor;
		if (activeEditor && activeEditor.document.uri.scheme === 'file') {
			const tempUri = activeEditor.document.uri;
			const tempUriString = tempUri.toString();
			const originalUri = tempToOriginalMap.get(tempUriString);
			if (originalUri) {
				try { await vscode.commands.executeCommand('workbench.action.closeActiveEditor'); } catch (e) {}
				const originalUriObj = vscode.Uri.parse(originalUri);
				const originalDoc = await vscode.workspace.openTextDocument(originalUriObj);
				await vscode.window.showTextDocument(originalDoc, { preview: false, viewColumn: vscode.ViewColumn.Active });
				try { await vscode.workspace.fs.delete(tempUri); } catch (e) { console.log('Failed to delete temp file:', e.message); }
				tempToOriginalMap.delete(tempUriString);
				vscode.window.showInformationMessage('Edit suggestion rejected ❌');
				
				// update the current hunks - remove rejected hunk from sidebar
				const rejectedHunk = tempToHunkMap.get(tempUriString);
				if (rejectedHunk) {
					tempToHunkMap.delete(tempUriString);
					if (rejectedHunk.idx !== undefined) {
						currentHunks = currentHunks.filter(h => h.idx !== rejectedHunk.idx);
					} else {
						currentHunks = currentHunks.filter(h => !(h.file === rejectedHunk.file && h.hunkText === rejectedHunk.hunkText && h.startLineAfter === rejectedHunk.startLineAfter));
					}
					if (currentHunks.length > 0) {
						await showHunksLocation(currentHunks);
						SuggestionLocationsProvider.updateItems(currentHunks);
					} else {
						SuggestionLocationsProvider.updateItems([]);
					}
				}
			}
		}
	} catch (error) {
		console.error('Failed to reject diff:', error);
		vscode.window.showErrorMessage(`Failed to reject diff: ${error.message}`);
	}
}

// --------------------
// Health Check Helpers
// --------------------
let firstOptimizationSuccess = true;

function getOptimizationServerURL() {
    const config = vscode.workspace.getConfiguration('editflow');
    return config.get('serverURL', 'http://localhost:5002');
}

async function makeHttpRequest(url, options) {
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

async function validateOptimizationServerConnection(showMessage = true, retryInterval = 3000) {
    try {
        const serverURL = getOptimizationServerURL();
        const response = await makeHttpRequest(`${serverURL}/health`, {
            method: 'GET',
            timeout: 5000
        });
        if (response.status === 200) {
            if (showMessage || firstOptimizationSuccess) {
                vscode.window.showInformationMessage('✅ Successfully connected to EditFlow optimization server! 🎉');
            }
            firstOptimizationSuccess = false;
            return true;
        } else {
            firstOptimizationSuccess = true;
            vscode.window.showErrorMessage('❌ EditFlow optimization server connection failed: invalid response');
            setTimeout(() => {
                validateOptimizationServerConnection(showMessage, retryInterval);
            }, retryInterval);
            return false;
        }
    } catch (error) {
        firstOptimizationSuccess = true;
        vscode.window.showErrorMessage(`❌ EditFlow optimization server connection failed: ${error.message}`);
        setTimeout(() => {
            validateOptimizationServerConnection(showMessage, retryInterval);
        }, retryInterval);
        return false;
    }
}

module.exports = {
	initializeFlowKeeper,
	runOptimization,
	acceptDiff,
    rejectDiff,
    validateOptimizationServerConnection
};