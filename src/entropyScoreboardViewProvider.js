const vscode = require('vscode');

class EntropyScoreboardViewProvider {
    constructor(context) {
        this.context = context;
        this._view = null;
        this._entries = [];
    }

    resolveWebviewView(webviewView) {
        this._view = webviewView;
        webviewView.webview.options = { enableScripts: true };
        webviewView.webview.html = this.getHtml();
    }

    addEntryFromResponse(response_message) {
        if (!response_message || !response_message.evaluation_entropy || !response_message.evaluation_entropy.entropy) {
            console.log('Invalid response_message or missing entropy data:', response_message);
            return;
        }
        const entropy = response_message.evaluation_entropy.entropy;
        const coedit = typeof entropy.coedit === 'number' ? entropy.coedit : parseFloat(entropy.coedit);
        const solo = typeof entropy.solo === 'number' ? entropy.solo : parseFloat(entropy.solo);
        
        console.log('Adding entry:', { coedit, solo });
        this._entries.push({ coedit, solo });
        console.log('Total entries:', this._entries.length);
        
        if (this._view) {
            this._view.webview.html = this.getHtml();
        }
    }

    getHtml() {
        // calculate total coedit and solo scores
        let coeditSum = 0, soloSum = 0;
        this._entries.forEach(entry => {
            coeditSum += entry.coedit;
            soloSum += entry.solo;
        });
        // color logic for scores
        const coeditIsGreen = coeditSum <= soloSum;
        const soloIsGreen = soloSum < coeditSum;
        return `
            <style>
                body, html { margin: 0; padding: 0; box-sizing: border-box; }
                .scoreboard-container { font-family: sans-serif; width: 100vw; max-width: 100vw; min-width: 0; }
                .row { display: flex; width: 100%; }
                .cell { flex: 1; text-align: center; border-right: 1px solid #e0e0e0; border-bottom: 2px solid #e0e0e0; padding: 0; }
                .cell:last-child { border-right: none; }
                .score-row { height: 64px; font-size: 1em; font-weight: 500; }
                .score-label { margin-top: 6px; font-size: 1.08em; }
                .score-value { font-size: 2.5em; font-weight: 700; margin: 0; line-height: 1.1; display: inline-flex; align-items: flex-end; }
                .score-value.green { color: #1db446; }
                .score-value.black { color: #444; }
                .score-bit { font-size: 0.45em; color: #444; margin-left: 2px; font-weight: 400; vertical-align: baseline; }
                .breakdown-title { font-size: 1em; text-align: left; padding: 5px 0 5px 12px; border-bottom: 2px solid #e0e0e0; }
                .edit-row { display: flex; align-items: center; border-bottom: 1px solid #e0e0e0; font-size: 1.08em; height: 24px; }
                .edit-cell { flex: 1; text-align: center; padding: 0; font-weight: 500; max-width: 80px; }
                .edit-index { width: 18px; height: 18px; line-height: 18px; margin: 0 auto; border: 2px solid #bbb; border-radius: 6px; background: #fff; font-weight: bold; font-size: 0.8em; display: flex; align-items: center; justify-content: center; }
                .edit-bit { font-size: 0.8em; color: #888; margin-left: 2px; }
                .edit-cell.coedit.green strong { color: #1db446; }
                .edit-cell.coedit.black strong { color: #444; }
                .edit-cell.solo.green strong { color: #1db446; }
                .edit-cell.solo.black strong { color: #444; }
                .edit-cell strong { font-size: 1.05em; }
            </style>
            <div class="scoreboard-container">
                <div class="row score-row">
                    <div class="cell">
                        <div class="score-label">Co-edit</div>
                        <div class="score-value ${coeditIsGreen ? 'green' : 'black'}">${coeditSum.toFixed(2)}<span class="score-bit">bit</span></div>
                    </div>
                    <div class="cell">
                        <div class="score-label">Solo</div>
                        <div class="score-value ${soloIsGreen ? 'green' : 'black'}">${soloSum.toFixed(2)}<span class="score-bit">bit</span></div>
                    </div>
                </div>
                <div class="breakdown-title">Per edit breakdown</div>
                ${this._entries.map((entry, i) => {
                    const coeditGreen = entry.coedit <= entry.solo;
                    const soloGreen = entry.solo < entry.coedit;
                    return `<div class="edit-row">
                        <div class="edit-cell coedit ${coeditGreen ? 'green' : 'black'}"><strong>${entry.coedit.toFixed(2)}</strong> <span class="edit-bit">bit</span></div>
                        <div class="edit-cell"><div class="edit-index">${i+1}</div></div>
                        <div class="edit-cell solo ${soloGreen ? 'green' : 'black'}"><strong>${entry.solo.toFixed(2)}</strong> <span class="edit-bit">bit</span></div>
                    </div>`;
                }).join('')}
            </div>
        `;
    }
}

module.exports = { EntropyScoreboardViewProvider };