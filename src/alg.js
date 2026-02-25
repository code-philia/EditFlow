const fs = require('fs');
const { execSync } = require('child_process');
const path = require('path');
const { DateTime } = require('luxon');

class LineRecord {
    constructor(line_of_code, last_modified_time) {
        this.line_of_code = line_of_code;
        this.last_modified_time = last_modified_time;
        this.alive = true;
    }

    toString() {
        const status = this.alive ? "alive" : "dead";
        const print_line_of_code = this.line_of_code.replace('\n', '');
        return `@ ${this.last_modified_time} (${status}) ${print_line_of_code}`;
    }
}

function initTrackTimestamp(base_version, timestamp) {
    const base_status = [];
    const head_status = [];
    for (const loc of base_version) {
        base_status.push(new LineRecord(loc, timestamp));
        head_status.push(new LineRecord(loc, timestamp));
    }
    return [base_status, head_status];
}

function convertStatusToFile(status) {
    return status.map(record => record.line_of_code);
}

function convertDiffSectionToSnapshot(file_w_diff) {
    const diff_content = file_w_diff.split(/\r?\n/);
    const snapshot = [];
    let consecutive_code = [];
    let under_edit = false;
    let edits = [];
    let currentEdit = null;

    for (const line of diff_content) {
        if (line.startsWith(" ") && !under_edit) {
            consecutive_code.push(line.substring(1) + '\n');
        } else if (line.startsWith(" ") && under_edit) {
            under_edit = false;
            if (currentEdit.type === "replace" && currentEdit.after.length === 0) {
                currentEdit.type = "delete";
            }
            snapshot.push({...currentEdit});
            consecutive_code.push(line.substring(1) + '\n');
        } else if (line.startsWith("-") && !under_edit) {
            under_edit = true;
            if (consecutive_code.length > 0) {
                snapshot.push([...consecutive_code]);
            }
            consecutive_code = [];
            currentEdit = {
                type: "replace",
                before: [],
                after: []
            };
            currentEdit.before.push(line.substring(1) + '\n');
        } else if (line.startsWith("+") && !under_edit) {
            under_edit = true;
            if (consecutive_code.length > 0) {
                snapshot.push([...consecutive_code]);
            }
            consecutive_code = [];
            currentEdit = {
                type: "insert",
                before: [],
                after: []
            };
            currentEdit.after.push(line.substring(1) + '\n');
        } else if (line.startsWith("+") && under_edit) {
            currentEdit.after.push(line.substring(1) + '\n');
        } else if (line.startsWith("-") && under_edit) {
            currentEdit.before.push(line.substring(1) + '\n');
        }
    }

    if (under_edit) {
        if (currentEdit.type === "replace" && currentEdit.after.length === 0) {
            currentEdit.type = "delete";
        }
        snapshot.push({...currentEdit});
    }
    if (!under_edit && consecutive_code.length > 0) {
        snapshot.push([...consecutive_code]);
    }

    edits = snapshot.filter(window => typeof window === 'object');
    return [snapshot, edits];
}

function getGitDiffStr(str1, str2) {
    const tempDir = path.join(__dirname, 'temp');
    if (!fs.existsSync(tempDir)) {
        fs.mkdirSync(tempDir);
    }

    const f1Path = path.join(tempDir, 'file1.txt');
    const f2Path = path.join(tempDir, 'file2.txt');

    fs.writeFileSync(f1Path, str1);
    fs.writeFileSync(f2Path, str2);

    try {
        const diff = execSync(`git diff -U10000000 --no-index ${f1Path} ${f2Path}`).toString();
        fs.unlinkSync(f1Path);
        fs.unlinkSync(f2Path);
        return diff;
    } catch (error) {
        fs.unlinkSync(f1Path);
        fs.unlinkSync(f2Path);
        return error.stdout.toString();
    }
}

function convertDiffToSnapshot(git_diff_str) {
    const diff_sections = git_diff_str.split(/diff --git/).slice(1);
    const commit_snapshots = {};

    if (diff_sections.length === 0) {
        return null;
    }

    for (const section of diff_sections) {
        const match = section.match(/@@[^\n]*\n([\s\S]*)/);
        if (!match) {
            throw new Error("Error: Edit fail to match @@ -xx,xx +xx,xx @@");
        }

        const after_at_symbol_content = match[1];
        const [snapshot] = convertDiffSectionToSnapshot(after_at_symbol_content);

        let parent_version_line_index = 0;
        let child_version_line_index = 0;

        for (const window of snapshot) {
            if (Array.isArray(window)) {
                parent_version_line_index += window.length;
                child_version_line_index += window.length;
            } else {
                /** @type {any} */ (window).parent_version_range = {
                    start: parent_version_line_index,
                    end: parent_version_line_index + window.before.length
                };
                /** @type {any} */ (window).child_version_range = {
                    start: child_version_line_index,
                    end: child_version_line_index + window.after.length
                };

                if (window.before.length > 0) {
                    parent_version_line_index += window.before.length;
                }
                if (window.after.length > 0) {
                    child_version_line_index += window.after.length;
                }
            }
        }

        return snapshot;
    }
}

function getDiffAtLines(snapshot_i, snapshot_j) {
    if (snapshot_i === snapshot_j) {
        return [[], []];
    }

    const git_diff_str = getGitDiffStr(snapshot_i, snapshot_j);
    const diff_snapshot = convertDiffToSnapshot(git_diff_str);

    if (!diff_snapshot) {
        return [[], []];
    }

    const deleted_lines = [];
    const added_lines = [];
    let curr_base_idx = 0;
    let curr_head_idx = 0;

    for (const window of diff_snapshot) {
        if (Array.isArray(window)) {
            curr_base_idx += window.length;
            curr_head_idx += window.length;
        } else {
            for (let i = 0; i < window.before.length; i++) {
                const base_line_idx = curr_base_idx + i;
                deleted_lines.push([base_line_idx, window.before[i]]);
            }

            for (let i = 0; i < window.after.length; i++) {
                const head_line_idx = curr_head_idx + i;
                added_lines.push([head_line_idx, window.after[i]]);
            }

            curr_base_idx += window.before.length;
            curr_head_idx += window.after.length;
        }
    }

    return [deleted_lines, added_lines];
}

function trackTimestamp(base_status, base_timestamp, head_status, new_version, new_timestamp, debug = false) {
    const head_version = convertStatusToFile(head_status);
    
    const [deleted_lines_ij, added_lines_ij] = getDiffAtLines(head_version.join(''), new_version.join(''));

    if (head_status.length - deleted_lines_ij.length + added_lines_ij.length !== new_version.length) {
        throw new Error(`${head_status.length} - ${deleted_lines_ij.length} + ${added_lines_ij.length} != ${new_version.length}`);
    }

    if (debug) {
        console.log("V head <--> V new:\n");
        console.log(`DEL: ${JSON.stringify(deleted_lines_ij)}\n`);
        console.log(`ADD: ${JSON.stringify(added_lines_ij)}\n`);
    }

    const base_version = convertStatusToFile(base_status);
    const [deleted_lines_0j, added_lines_0j] = getDiffAtLines(base_version.join(''), new_version.join(''));

    if (debug) {
        console.log("V0 <--> V new:\n");
        console.log(`DEL: ${JSON.stringify(deleted_lines_0j)}\n`);
        console.log(`ADD: ${JSON.stringify(added_lines_0j)}\n`);
    }

    // Update base version status
    for (const [line_idx, line_content] of deleted_lines_0j) {
        if (base_status[line_idx].alive) {
            base_status[line_idx].last_modified_time = new_timestamp;
            base_status[line_idx].alive = false;
        }
    }

    // Check already dead lines in base_status
    for (let line_idx = 0; line_idx < base_status.length; line_idx++) {
        const line = base_status[line_idx];
        if (line.alive) continue;
        
        const lineExists = deleted_lines_0j.some(([idx, content]) => 
            idx === line_idx && content === line.line_of_code
        );
        
        if (!lineExists) {
            line.alive = true;
            line.last_modified_time = base_timestamp;
        }
    }

    // Update head version status from vi to vj
    const sorted_deleted_lines_ij = [...deleted_lines_ij].sort((a, b) => b[0] - a[0]);
    for (const [line_idx] of sorted_deleted_lines_ij) {
        head_status.splice(line_idx, 1);
    }

    for (const [line_idx, line_content] of added_lines_ij) {
        const lineExistsInV0 = added_lines_0j.some(([idx, content]) => 
            idx === line_idx && content === line_content
        );
        
        if (!lineExistsInV0) {
            head_status.splice(line_idx, 0, new LineRecord(line_content, base_timestamp));
        } else {
            head_status.splice(line_idx, 0, new LineRecord(line_content, new_timestamp));
        }
    }


    for (let idx = 0; idx < head_status.length; idx++) {
        if (head_status[idx].line_of_code.trim() !== new_version[idx].trim()) {
            throw new Error(`Head line ${idx} status: ${head_status[idx].line_of_code}, Head line: ${new_version[idx]}`);
        }
    }

    return [base_status, head_status];
}

function statusToSnapshotsWithHunkOrder(snapshot_by_file) {
    const commit_snapshots = {};
    const edits = [];
    let edit_idx = 0;

    for (const [edit_file, edit_file_detail] of Object.entries(snapshot_by_file)) {
        const diff = getGitDiffStr(
            convertStatusToFile(edit_file_detail.base_status).join(''),
            convertStatusToFile(edit_file_detail.head_status).join('')
        );
        const commit_file_snapshot = convertDiffToSnapshot(diff);
        if (!commit_file_snapshot) continue;

        for (const window of commit_file_snapshot) {
            if (typeof window === 'object' && !Array.isArray(window)) {
                /** @type {any} */ (window).base_timestamps = [];
                /** @type {any} */ (window).head_timestamps = [];
                /** @type {any} */ (window).base_datetimes = [];
                /** @type {any} */ (window).head_datetimes = [];

                for (const line of edit_file_detail.base_status.slice(
                    /** @type {any} */ (window).parent_version_range.start,
                    /** @type {any} */ (window).parent_version_range.end
                )) {
                    /** @type {any} */ (window).base_timestamps.push(line.last_modified_time);
                    /** @type {any} */ (window).base_datetimes.push(
                        DateTime.fromMillis(line.last_modified_time / 1000).toFormat('yyyy-MM-dd HH:mm:ss')
                    );
                }

                for (const line of edit_file_detail.head_status.slice(
                    /** @type {any} */ (window).child_version_range.start,
                    /** @type {any} */ (window).child_version_range.end
                )) {
                    /** @type {any} */ (window).head_timestamps.push(line.last_modified_time);
                    /** @type {any} */ (window).head_datetimes.push(
                        DateTime.fromMillis(line.last_modified_time / 1000).toFormat('yyyy-MM-dd HH:mm:ss')
                    );
                }

                /** @type {any} */ (window).idx = edit_idx;
                /** @type {any} */ (window).file_path = edit_file;
                edits.push(window);
                edit_idx++;
            }
        }
        commit_snapshots[edit_file] = commit_file_snapshot;
    }

    return commit_snapshots;
}

function getDemoData() {
    return {
        "f1": {
    versions: [[
            "0\n",
            "1\n",
            "2\n",
            "3\n",
            "4\n",
            "5\n",
            "6\n",
            "7\n",
            "8\n",
            "9\n"
        ],
    [
            "0\n",
            "1\n",
            "3\n",
            "4\n",
            "5\n",
            "6\n",
            "7\n",
            "8\n",
            "9\n"
        ],
    [
            "0\n",
            "1\n",
            "3\n",
            "4\n",
            "5.1\n",
            "6.1\n",
            "7\n",
            "8\n",
            "9\n"
        ],
        [
            "0\n",
            "1\n",
            "3\n",
            "4\n",
            "5.1\n",
            "6.2\n",
            "8\n",
            "9\n"
        ],
        [
            "0\n",
            "0.1\n",
            "1\n",
            "3\n",
            "4\n",
            "5.1\n",
            "6.2\n",
            "8\n",
            "9\n"
        ],
        [
            "0\n",
            "0.1\n",
            "1\n",
            "2\n",
            "3\n",
            "4\n",
            "5.1\n",
            "6.2\n",
            "8\n",
            "9\n"
        ],
    ],
    timestamps: [0, 1 , 2, 3, 4, 5]
        },
    "f2": {
    versions: [[
            "0\n",
            "1\n",
            "2\n",
            "3\n",
            "4\n",
            "5\n",
            "6\n",
            "7\n",
            "8\n",
            "9\n"
        ],
    [
            "0\n",
            "1\n",
            "3\n",
            "4\n",
            "5\n",
            "6\n",
            "7\n",
            "8\n",
            "9\n"
        ],
    [
            "0\n",
            "1\n",
            "3\n",
            "4\n",
            "5.1\n",
            "6.1\n",
            "7\n",
            "8\n",
            "9\n"
        ],
        [
            "0\n",
            "1\n",
            "3\n",
            "4\n",
            "5.1\n",
            "6.2\n",
            "8\n",
            "9\n"
        ],
        [
            "0\n",
            "0.1\n",
            "1\n",
            "3\n",
            "4\n",
            "5.1\n",
            "6.2\n",
            "8\n",
            "9\n"
        ],
        [
            "0\n",
            "0.1\n",
            "1\n",
            "2\n",
            "3\n",
            "4\n",
            "5.1\n",
            "6.2\n",
            "8\n",
            "9\n"
        ],
    ],
    timestamps: [0, 1 , 2, 3, 4, 5]
        }
    };
}

function main() {
    const snapshotsByFile = getDemoData();
    const processedSnapshots = {};
    
    for (const [filePath, fileData] of Object.entries(snapshotsByFile)) {
        if (!fileData.versions || fileData.versions.length === 0) continue;
        
        const versions = fileData.versions;
        const timestamps = fileData.timestamps;
        const [base_status, head_status] = initTrackTimestamp(versions[0], timestamps[0]);
        processedSnapshots[filePath] = {
            base_status: base_status,
            head_status: head_status,
            base_timestamp: timestamps[0]
        };
        for (let i = 1; i < versions.length; i++) {
            const new_version = versions[i];
            const new_timestamp = timestamps[i];
            
            const [updated_base_status, updated_head_status] = trackTimestamp(
                processedSnapshots[filePath].base_status,
                processedSnapshots[filePath].base_timestamp,
                processedSnapshots[filePath].head_status,
                new_version,
                new_timestamp
            );
            
            processedSnapshots[filePath] = {
                base_status: updated_base_status,
                head_status: updated_head_status,
                base_timestamp: timestamps[0] 
            };
        }
    }
    
    const commit_snapshots = statusToSnapshotsWithHunkOrder(processedSnapshots);
    fs.writeFileSync("demo.json", JSON.stringify(commit_snapshots, null, 4));
    return commit_snapshots;
}

function processMultiFileVersions(snapshotsByFile) {
    const processedSnapshots = {};
    
    for (const [filePath, fileData] of Object.entries(snapshotsByFile)) {
        if (!fileData.versions || fileData.versions.length === 0) continue;
        
        const versions = fileData.versions;
        const timestamps = fileData.timestamps;
        const [base_status, head_status] = initTrackTimestamp(versions[0], timestamps[0]);
        processedSnapshots[filePath] = {
            base_status: base_status,
            head_status: head_status,
            base_timestamp: timestamps[0]
        };
        
        for (let i = 1; i < versions.length; i++) {
            const new_version = versions[i];
            const new_timestamp = timestamps[i];
            
            const [updated_base_status, updated_head_status] = trackTimestamp(
                processedSnapshots[filePath].base_status,
                processedSnapshots[filePath].base_timestamp,
                processedSnapshots[filePath].head_status,
                new_version,
                new_timestamp
            );
            
            processedSnapshots[filePath] = {
                base_status: updated_base_status,
                head_status: updated_head_status,
                base_timestamp: timestamps[0]
            };
        }
    }
    
    const commit_snapshots = statusToSnapshotsWithHunkOrder(processedSnapshots);
    return commit_snapshots;
}

if (require.main === module) {
    main();
}

module.exports = {
    processMultiFileVersions
};