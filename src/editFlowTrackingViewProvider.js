const vscode = require('vscode');

class EditFlowTrackingViewProvider {
    constructor(context) {
        this.context = context;
        this._view = null;
        // Cumulative counters for flow patterns
        this.cumulativeFlowCounts = {
            flow_keeping: 0,
            flow_jumping: 0,
            flow_breaking: 0,
            flow_reverting: 0
        };
        // Cumulative counters for metrics
        this.cumulativeMetrics = {
            tp: 0,
            fp: 0,
            fn: 0
        };
    }

    resolveWebviewView(webviewView) {
        this._view = webviewView;
        webviewView.webview.options = { enableScripts: true };
        webviewView.webview.html = this.getHtml();
    }

    updateFlowData(flowPattern, hunks, evaluations) {
        // Update cumulative flow pattern counts
        if (flowPattern) {
            this.cumulativeFlowCounts.flow_keeping += (flowPattern.flow_keeping || []).length;
            this.cumulativeFlowCounts.flow_jumping += (flowPattern.flow_jumping || []).length;
            this.cumulativeFlowCounts.flow_breaking += (flowPattern.flow_breaking || []).length;
            this.cumulativeFlowCounts.flow_reverting += (flowPattern.flow_reverting || []).length;
        }
        
        // Update cumulative metrics
        if (evaluations) {
            this.cumulativeMetrics.tp += evaluations.tp || 0;
            this.cumulativeMetrics.fp += evaluations.fp || 0;
            this.cumulativeMetrics.fn += evaluations.fn || 0;
        }
        
        // Refresh the view
        if (this._view) {
            this._view.webview.html = this.getHtml();
        }
    }

    calculatePrecision() {
        const { tp, fp } = this.cumulativeMetrics;
        return tp + fp > 0 ? ((tp / (tp + fp)) * 100).toFixed(1) + '%' : '-%';
    }
    
    calculateRecall() {
        const { tp, fn } = this.cumulativeMetrics;
        return tp + fn > 0 ? ((tp / (tp + fn)) * 100).toFixed(1) + '%' : '-%';
    }
    
    calculateF1Score() {
        const { tp, fp, fn } = this.cumulativeMetrics;
        const precision = tp + fp > 0 ? tp / (tp + fp) : 0;
        const recall = tp + fn > 0 ? tp / (tp + fn) : 0;
        return precision + recall > 0 ? ((2 * precision * recall / (precision + recall)) * 100).toFixed(1) + '%' : '-%';
    }

    getHtml() {
        return `
            <style>
                body, html { 
                    margin: 0; 
                    padding: 0; 
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    font-size: 13px;
                }
                .metrics-container {
                    padding: 8px;
                }
                .metrics-row {
                    display: flex;
                    align-items: center;
                    height: 24px;
                    position: relative;
                }
                .metrics-row::after {
                    content: '';
                    position: absolute;
                    left: 50%;
                    top: 0;
                    bottom: 0;
                    width: 1px;
                    background-color: #ccc;
                    transform: translateX(-50%);
                }
                .metrics-row.header {
                    height: 32px;
                    font-weight: bold;
                    font-size: 15px;
                    border-bottom: 1px solid #ccc;
                    margin-bottom: 4px;
                }
                .metrics-left {
                    flex: 1;
                    text-align: center;
                    padding-right: 10px;
                }
                .metrics-right {
                    flex: 1;
                    font-weight: bold;
                    color: #007acc;
                    text-align: center;
                    padding-left: 10px;
                }
                .metrics-right.header {
                    color: #000;
                    font-size: 15px;
                }
            </style>
            <div class="metrics-container">
                <div class="metrics-row header">
                    <div class="metrics-left">Metric</div>
                    <div class="metrics-right header">Avg</div>
                </div>
                <div class="metrics-row">
                    <div class="metrics-left">Flow-keeping</div>
                    <div class="metrics-right">${this.cumulativeFlowCounts.flow_keeping}</div>
                </div>
                <div class="metrics-row">
                    <div class="metrics-left">Flow-jumping</div>
                    <div class="metrics-right">${this.cumulativeFlowCounts.flow_jumping}</div>
                </div>
                <div class="metrics-row">
                    <div class="metrics-left">Flow-breaking</div>
                    <div class="metrics-right">${this.cumulativeFlowCounts.flow_breaking}</div>
                </div>
                <div class="metrics-row">
                    <div class="metrics-left">Flow-reverting</div>
                    <div class="metrics-right">${this.cumulativeFlowCounts.flow_reverting}</div>
                </div>
                <div class="metrics-row">
                    <div class="metrics-left">Precision</div>
                    <div class="metrics-right">${this.calculatePrecision()}</div>
                </div>
                <div class="metrics-row">
                    <div class="metrics-left">Recall</div>
                    <div class="metrics-right">${this.calculateRecall()}</div>
                </div>
                <div class="metrics-row">
                    <div class="metrics-left">F1-score</div>
                    <div class="metrics-right">${this.calculateF1Score()}</div>
                </div>
            </div>
        `;
    }
}

module.exports = { EditFlowTrackingViewProvider };