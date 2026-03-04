import os
import json
import time
import shutil
from .language_server import LanguageServer

class JavaLanguageServer(LanguageServer):
    def __init__(self, log: bool = False):
        language_id = "java"
        current_path = os.path.dirname(os.path.abspath(__file__))
        jdt_lsp_jar = os.path.join(current_path, "jdt-language-server/plugins/org.eclipse.equinox.launcher_1.6.900.v20240613-2009.jar")
        jdt_lsp_config = os.path.join(current_path, "jdt-language-server/config_linux")
        
        # data saved at a temp folder
        self.temp_data_path = os.path.join(current_path, "temp_data")
        COMMAND = [
            "java",
            "-Declipse.application=org.eclipse.jdt.ls.core.id1",
            "-Dosgi.bundles.defaultStartLevel=4",
            "-Declipse.product=org.eclipse.jdt.ls.core.product",
            "-Dlog.level=ALL",
            "-Xmx1G",
            "--add-modules=ALL-SYSTEM",
            "--add-opens", "java.base/java.util=ALL-UNNAMED",
            "--add-opens", "java.base/java.lang=ALL-UNNAMED",
            "-jar", jdt_lsp_jar,
            "-configuration", jdt_lsp_config,
            "-data", self.temp_data_path
        ]
        super().__init__(language_id, COMMAND, log)
    
    def initialize(self, workspace_folders: list[str] | str, wait_time: float = 5):
        return super().initialize(workspace_folders, wait_time)
    
    def _parse_rename_response(self, response, edits, old_name, new_name):
        """
        Parse the response of rename request and update the edits
        
        Args:
            response: the response of rename request
            edits: the locations identified by lsp
            old_name: the old name of the identifier
            new_name: the new name of the identifier
        """
        for uri, changes in response[0]["result"]["changes"].items():
            file_path = uri[7:]
            if file_path not in edits:
                edits[file_path] = []
            for edit in changes:
                # inside 1 edit range, there may have multiple edits
                if edit["range"]["start"]["line"] == edit["range"]["end"]["line"]:
                    # if the edit range is a single line, then it is a single edit
                    edits[file_path].append(edit)
                else:
                    start_line = edit["range"]["start"]["line"]
                    end_line = edit["range"]["end"]["line"]
                    new_code = edit["newText"].splitlines(keepends=True)
                    for line_idx, code in zip(range(start_line, end_line + 1), new_code):
                        if new_name in code:
                            start_character = code.find(new_name)
                            end_character = start_character + len(new_name)
                            edits[file_path].append({
                                "range": {
                                    "start": {"line": line_idx, "character": start_character},
                                    "end": {"line": line_idx, "character": end_character}
                                },
                                "newText": new_name
                            })
        return edits
    
    def _filter_diagnostics(self, diagnostics, last_edit_at_range, init_diagnose_msg):
        """
        * Filter out non-serious diagnostics.
        * All diagnostics please refer to: https://www.javadoc.io/doc/org.aspectj/aspectjtools/1.8.4/constant-values.html, at table org.aspectj.org.eclipse.jdt.core.compiler.IProblem.
        * For example, comments like //TODO, //FIXME, have diagnose "Task", with code 16777216, and severity 3.
        """
        with open("LSPs/jdt-language-server/jdtls_diagnose_code.json", "r") as f:
            jdtls_diagnostics = json.load(f)

        filtered_diagnostics = []
        for diagnostic in diagnostics:
            if not diagnostic["file_path"].endswith(".java"):
                continue
            if diagnostic["message"] in init_diagnose_msg:
                # If this diagnose already exists when the project is initialized, then this diagnose is not caused by user editing, no need to address
                continue
            if str(diagnostic["code"]) not in jdtls_diagnostics:
                # well, we can't guarantee we have collected all errors ...
                continue
            if jdtls_diagnostics[diagnostic["code"]]["whitelisted"]:
                if diagnostic["severity"] > 2: # severity 1: error, 2: warning, 3: info
                    continue
                if diagnostic["range"]["start"]["line"] in last_edit_at_range:
                    continue
                filtered_diagnostics.append(diagnostic)
            
        return filtered_diagnostics
        
    def rename(self, file_path: str, position: dict[str, int], new_name: str, wait_time: float = 3):
        # Extend wait time
        return super().rename(file_path, position, new_name, wait_time)
    
    def references(self, file_path, position, wait_time: float = 3):
        # Extend wait time
        return super().references(file_path, position, wait_time)
       
    def diagnostics(self, file_path, wait_time: float = 3):
        # Extend wait time
        return super().diagnostics(file_path, wait_time)
    
    def close(self):
        # delete the temp data
        time.sleep(3)
        shutil.rmtree(self.temp_data_path)
        return super().close()
        
if __name__ == "__main__":
    current_path = os.path.dirname(os.path.abspath(__file__))
    workspace = os.path.join(current_path, "projects/java_project")
    file_path = os.path.join(workspace, "src/main/java/com/example/App.java")
    
    server = JavaLanguageServer(log=True)
    
    print(f">>>>>>>> Check initialize:")
    server.initialize(workspace)
    
    # Get the list of all file paths in the workspace
    file_paths = server.get_all_file_paths(workspace)
    server.open_in_batch(file_paths)
    
    print(f">>>>>>>> Check rename:")
    server.rename(file_path, {"line": 8, "character": 13}, "sum_func")
    
    print(f">>>>>>>> Check references:")
    server.references(file_path, {"line": 8, "character": 30})
    
    print(f">>>>>>>> Check diagnostics:")
    server.diagnostics(file_path)
    
    print(f">>>>>>>> Check close:")
    server.close()
