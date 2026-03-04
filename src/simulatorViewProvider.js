const vscode = require('vscode');
const path = require('path');

class FileItem extends vscode.TreeItem {
    constructor(filePath) {
        super(path.basename(filePath), vscode.TreeItemCollapsibleState.Expanded);
        this.filePath = filePath;
        this.iconPath = {
            light: vscode.Uri.file(path.join(__dirname, '..', 'media', 'file.svg')),
            dark: vscode.Uri.file(path.join(__dirname, '..', 'media', 'file.svg'))
        };
        this.contextValue = 'file';
    }
}

class LineItem extends vscode.TreeItem {
    constructor(lineNumber, hunk, isHighlight = false) {
        const shortReason = hunk.short_reason || '';
        const label = `Line: ${lineNumber + 2}`;
        
        super(label);
        if (shortReason) {
            this.description = shortReason;
        }
        this.lineNumber = lineNumber;
        this.hunk = hunk;
        // select icon based on flowKeeping
        if (hunk.flowKeeping === true) {
            this.iconPath = {
                light: vscode.Uri.file(path.join(__dirname, '..', 'media', 'correct.svg')),
                dark: vscode.Uri.file(path.join(__dirname, '..', 'media', 'correct.svg'))
            };
        } else {
            // check hunkText content
            const lines = hunk.hunkText.split('\n');
            const hasAdd = lines.some(line => line.startsWith('+'));
            const hasRemove = lines.some(line => line.startsWith('-'));
            if (hasAdd && !hasRemove) {
                // pure addition
                this.iconPath = {
                    light: vscode.Uri.file(path.join(__dirname, '..', 'media', 'add-green.svg')),
                    dark: vscode.Uri.file(path.join(__dirname, '..', 'media', 'add-green.svg'))
                };
            } else if (!hasAdd && hasRemove) {
                // pure deletion
                this.iconPath = {
                    light: vscode.Uri.file(path.join(__dirname, '..', 'media', 'remove.svg')),
                    dark: vscode.Uri.file(path.join(__dirname, '..', 'media', 'remove.svg'))
                };
            } else {
                // other cases
                this.iconPath = {
                    light: vscode.Uri.file(path.join(__dirname, '..', 'media', 'edit-red.svg')),
                    dark: vscode.Uri.file(path.join(__dirname, '..', 'media', 'edit-red.svg'))
                };
            }
        }
        this.command = {
            command: 'flow-keeper.showHunkDiff',
            title: 'Show Hunk Diff',
            arguments: [hunk]
        };
        this.contextValue = 'line';
    }
    generateTooltip() {
        const tooltipParts = [];
        if (this.hunk && this.hunk.corresponding_prev_edit) {
            const filePathMatch = this.hunk.corresponding_prev_edit.match(/<file_path>([\s\S]*?)<\/file_path>/);
            if (filePathMatch && filePathMatch[1]) {
                const fileName = filePathMatch[1];
                tooltipParts.push(`The last edit is in the file **${fileName}**`);
                tooltipParts.push('');
            }
        }
        if (this.hunk && this.hunk.corresponding_prev_edit) {
            const codeLines = this.extractAndFormatCode(this.hunk.corresponding_prev_edit);
            if (codeLines && codeLines.length > 0) {
                tooltipParts.push('```diff');
                codeLines.forEach(line => {
                    tooltipParts.push(line);
                });
                tooltipParts.push('```');
            }
        }
        
        if (this.hunk && this.hunk.long_reason) {
            if (tooltipParts.length > 0) {
                tooltipParts.push(''); 
            }
            tooltipParts.push(this.hunk.long_reason);
        }
        
        return tooltipParts.join('  \n');
    }
    
    extractAndFormatCode(correspondingPrevEdit) {
        const codeMatch = correspondingPrevEdit.match(/<code>([\s\S]*?)<\/code>/);
        if (!codeMatch) {
            return null;
        }
        
        const codeContent = codeMatch[1];
        const lines = codeContent.split('\n');
        
        return lines.map(line => {
            const match = line.match(/^(\s*\d+\s+)(\d+\s+)?([+-])(\s*)(.*)$/);
            if (match) {
                const [, firstNumberPart, secondNumberPart, changeType, spacesAfterSymbol, content] = match;
                
                if (changeType === '+') {
                    return `+${spacesAfterSymbol}${content}`;
                } else if (changeType === '-') {
                    return `-${spacesAfterSymbol}${content}`;
                }
            }
            return null;
        }).filter(line => line !== null); 
    }
}

class SimpleTreeDataProvider {
    constructor() {
        this.files = new Map(); // Map<filePath, Set<lineNumber>>
        this.hunkMap = new Map(); // Map<filePath:lineNumber, hunk>
        this._onDidChangeTreeData = new vscode.EventEmitter();
        this.onDidChangeTreeData = this._onDidChangeTreeData.event;
        this.highlightIndex = -1; // highlighted hunk index
    }

    getTreeItem(element) {
        return element;
    }

    getChildren(element) {
        if (!element) {
            // return all files
            return Array.from(this.files.keys()).map(filePath => new FileItem(filePath));
        } else if (element instanceof FileItem) {
            // return all line numbers under the file
            const lineNumbers = Array.from(this.files.get(element.filePath));
            // find all hunks under the file
            const hunks = lineNumbers.map(lineNumber => this.getHunkForLine(element.filePath, lineNumber));
            return hunks.map((hunk, idx) => {
                // only add add_green.svg to the hunk with highlightIndex
                const lineNumber = lineNumbers[idx];
                const isHighlight = (this.highlightIndex === idx);
                const lineItem = new LineItem(lineNumber, hunk, isHighlight);
                
                // 设置tooltip
                const tooltipMarkdown = lineItem.generateTooltip();
                if (tooltipMarkdown) {
                    lineItem.tooltip = new vscode.MarkdownString(tooltipMarkdown);
                }
                
                return lineItem;
            });
        }
        return [];
    }

    getHunkForLine(filePath, lineNumber) {
        // return stored hunk object
        return this.hunkMap.get(`${filePath}:${lineNumber}`) || null;
    }

    updateItems(items, highlightIndex = -1) {
        // clear existing data
        this.files.clear();
        this.hunkMap.clear();
        this.highlightIndex = highlightIndex;

        // add new hunk information
        items.forEach(hunk => {
            if (!hunk || typeof hunk.hunkText !== 'string') return;
            const hunkLines = hunk.hunkText.split('\n');
            let firstDeletionLine = -1;
            let firstAdditionLine = -1;

            // find the first deletion and addition line
            for (let i = 0; i < hunkLines.length; i++) {
                const line = hunkLines[i];
                if (line.startsWith('-') && firstDeletionLine === -1) {
                    firstDeletionLine = hunk.startLineAfter + i; // use hunk's startLine
                } else if (line.startsWith('+') && firstAdditionLine === -1) {
                    firstAdditionLine = hunk.startLineAfter + i; // use hunk's startLine
                }
            }
            if (firstDeletionLine == -1){
                firstAdditionLine = firstAdditionLine - 1;
            }
            else{
                firstDeletionLine = firstDeletionLine -1 ;
            }
            // use firstDeletionLine, if not use firstAdditionLine
            const lineToAdd = firstDeletionLine !== -1 ? firstDeletionLine : firstAdditionLine;
            
            if (lineToAdd < 0) {
                console.warn(`Invalid line number calculated: ${lineToAdd} for hunk in file ${hunk.file}`);
                return; 
            }
            if (!this.files.has(hunk.file)) {
                this.files.set(hunk.file, new Set());
            }
            this.files.get(hunk.file).add(lineToAdd); // use calculated line number
            // store hunk object, for opening the correct hunk when clicked
            this.hunkMap.set(`${hunk.file}:${lineToAdd}`, hunk);
        });

        // notify view update
        this._onDidChangeTreeData.fire();
    }
}

// predicted edit item
class PredictedEditItem extends vscode.TreeItem {
    constructor(hunk, editType = 'edit') {
        const fileName = path.basename(hunk.file);
        const label = `${fileName} (Line ${hunk.startLineBefore})`;
        super(label, vscode.TreeItemCollapsibleState.None);

        this.hunk = hunk;
        this.editType = editType;
        this.tooltip = `${hunk.file} - Line ${hunk.startLineBefore}`;
        this.description = this.getEditDescription(hunk);

        // set icon - use VS Code builtin theme icon
        this.iconPath = new vscode.ThemeIcon('edit');

        this.command = {
            command: 'simulator.openHunk',
            title: 'Open Edit Preview',
            arguments: [hunk]
        };

        this.contextValue = 'predictedEdit';
    }

    getEditDescription(hunk) {
        const lines = hunk.hunkText.split('\n');
        const additions = lines.filter(line => line.startsWith('+')).length;
        const deletions = lines.filter(line => line.startsWith('-')).length;

        if (additions > 0 && deletions > 0) {
            return `+${additions} -${deletions}`;
        } else if (additions > 0) {
            return `+${additions}`;
        } else if (deletions > 0) {
            return `-${deletions}`;
        }
        return 'Modified';
    }
}

// edit detail item
class EditDetailItem extends vscode.TreeItem {
    constructor(line, lineNumber, type) {
        super(line.substring(1), vscode.TreeItemCollapsibleState.None); // remove +/- prefix

        this.line = line;
        this.lineNumber = lineNumber;
        this.type = type; // 'addition', 'deletion', 'context'
        this.tooltip = `${type}: ${line}`;

        // set different icons and colors based on type
        if (type === 'addition') {
            this.iconPath = new vscode.ThemeIcon('add', new vscode.ThemeColor('gitDecoration.addedResourceForeground'));
            this.description = 'Added';
        } else if (type === 'deletion') {
            this.iconPath = new vscode.ThemeIcon('remove', new vscode.ThemeColor('gitDecoration.deletedResourceForeground'));
            this.description = 'Deleted';
        } else {
            this.iconPath = new vscode.ThemeIcon('circle-outline');
            this.description = 'Context';
        }

        this.contextValue = 'editDetail';
    }
}

// predicted edit tree data provider
class PredictedEditsTreeDataProvider {
    constructor() {
        this.hunks = [];
        this._onDidChangeTreeData = new vscode.EventEmitter();
        this.onDidChangeTreeData = this._onDidChangeTreeData.event;
    }

    getTreeItem(element) {
        return element;
    }

    getChildren(element) {
        if (!element) {
            // return all predicted edits, no sub items
            return this.hunks.map(hunk => new PredictedEditItem(hunk));
        }
        // no sub items, keep flat structure
        return [];
    }

    getEditDetails(hunk) {
        const details = [];
        const lines = hunk.hunkText.split('\n');
        let lineNumber = hunk.startLineBefore;

        for (const line of lines) {
            if (line.startsWith('+')) {
                details.push(new EditDetailItem(line, lineNumber, 'addition'));
                lineNumber++;
            } else if (line.startsWith('-')) {
                details.push(new EditDetailItem(line, lineNumber, 'deletion'));
            } else if (line.startsWith(' ')) {
                details.push(new EditDetailItem(line, lineNumber, 'context'));
                lineNumber++;
            }
        }

        return details;
    }

    updateHunks(hunks) {
        this.hunks = hunks || [];
        this._onDidChangeTreeData.fire();
    }
}

// prior edit tree data provider
class PriorEditsTreeDataProvider {
    constructor() {
        this.priorEdits = [];
        this._onDidChangeTreeData = new vscode.EventEmitter();
        this.onDidChangeTreeData = this._onDidChangeTreeData.event;
    }

    getTreeItem(element) {
        return element;
    }

    getChildren(element) {
        if (!element) {
            // return all prior edits
            return this.priorEdits.map((edit, index) => {
                const item = new vscode.TreeItem(
                    `Edit ${index + 1}: ${path.basename(edit.fileName)}`,
                    vscode.TreeItemCollapsibleState.Collapsed
                );
                item.tooltip = `${edit.fileName} - Line ${edit.startLineBefore}`;
                item.description = `Line ${edit.startLineBefore}`;
                item.iconPath = new vscode.ThemeIcon('history');
                item.contextValue = 'priorEdit';
                // item.edit = edit;
                return item;
            });
        } else if (element.edit) {
            // return detailed content of the edit
            const details = [];
            if (element.edit.add && element.edit.add.length > 0) {
                element.edit.add.forEach((line, index) => {
                    const item = new vscode.TreeItem(`+ ${line}`, vscode.TreeItemCollapsibleState.None);
                    item.iconPath = new vscode.ThemeIcon('add', new vscode.ThemeColor('gitDecoration.addedResourceForeground'));
                    item.contextValue = 'priorEditDetail';
                    details.push(item);
                });
            }
            if (element.edit.remove && element.edit.remove.length > 0) {
                const removeLines = Array.isArray(element.edit.remove) ? element.edit.remove : [element.edit.remove];
                removeLines.forEach((line, index) => {
                    const item = new vscode.TreeItem(`- ${line}`, vscode.TreeItemCollapsibleState.None);
                    item.iconPath = new vscode.ThemeIcon('remove', new vscode.ThemeColor('gitDecoration.deletedResourceForeground'));
                    item.contextValue = 'priorEditDetail';
                    details.push(item);
                });
            }
            return details;
        }
        return [];
    }

    updatePriorEdits(priorEdits) {
        this.priorEdits = priorEdits || [];
        this._onDidChangeTreeData.fire();
    }
}


class PredictedLocationsFlatProvider {
    constructor() {
        this.hunks = [];
        this.flowPattern = null;
        this._onDidChangeTreeData = new vscode.EventEmitter();
        this.onDidChangeTreeData = this._onDidChangeTreeData.event;
    }

    getTreeItem(element) {
        return element;
    }

    getChildren(element) {
        if (!element) {
            // Flat list, already ordered in this.hunks
            return this.hunks.map(item => {
                const { hunk, flowType } = item;
                const fileName = hunk.file.split('/').pop();
                const label = `${fileName}: Line ${hunk.startLineAfter + 1}`;
                const treeItem = new vscode.TreeItem(label, vscode.TreeItemCollapsibleState.None);
                // Set icon based on flowType
                let iconFile = null;
                if (flowType === 'flow_keeping') {
                    iconFile = 'flow-keeping.svg';
                } else if (flowType === 'flow_jumping') {
                    iconFile = 'flow-jumping.svg';
                } else if (flowType === 'flow_breaking') {
                    iconFile = 'flow-breaking.svg';
                } else if (flowType === 'flow_reverting') {
                    iconFile = 'flow-reverting.svg';
                }
                if (iconFile) {
                    treeItem.iconPath = {
                        light: vscode.Uri.file(path.join(__dirname, '..', 'media', iconFile)),
                        dark: vscode.Uri.file(path.join(__dirname, '..', 'media', iconFile)),
                    };
                }
                treeItem.command = {
                    command: 'simulator.showHunkDiff',
                    title: 'Show Hunk Diff',
                    arguments: [hunk],
                };
                treeItem.contextValue = 'flat-hunk';
                return treeItem;
            });
        }
        return [];
    }

    /**
     * Update the hunks and flowPattern, and re-order hunks for display
     * @param {Array} hunks 
     * @param {Object} flowPattern 
     */
    updateItems(hunks, flowPattern) {
        this.hunks = [];
        this.flowPattern = flowPattern;
        if (!hunks || !flowPattern) {
            this._onDidChangeTreeData.fire();
            return;
        }
        // Helper: get hunk by idx
        const hunkByIdx = {};
        hunks.forEach(h => {
            const idx = h.idx !== undefined ? h.idx : hunks.indexOf(h);
            hunkByIdx[idx] = h;
        });
        // Order: flow_keeping, flow_jumping, flow_breaking, flow_reverting
        const order = ['flow_keeping', 'flow_jumping', 'flow_breaking', 'flow_reverting'];
        for (const flowType of order) {
            const idxs = flowPattern[flowType] || [];
            // Get hunks for this flow type and sort by confidence (descending)
            const flowTypeHunks = idxs
                .map(idx => hunkByIdx[idx])
                .filter(hunk => hunk) // Filter out undefined hunks
                .sort((a, b) => {
                    // Sort by confidence in descending order (highest first)
                    const confidenceA = a.confidence || 0;
                    const confidenceB = b.confidence || 0;
                    return confidenceB - confidenceA;
                });
            
            // Add sorted hunks to the final list
            flowTypeHunks.forEach(hunk => {
                this.hunks.push({ hunk, flowType });
            });
        }
        this._onDidChangeTreeData.fire();
    }
}

module.exports = {
    PredictedLocationsFlatProvider,
    SimpleTreeDataProvider,
    PredictedEditsTreeDataProvider,
    PriorEditsTreeDataProvider
};