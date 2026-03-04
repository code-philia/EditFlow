import os
import json

from typing import Dict
from .language_server import LanguageServer

class TsLanguageServer(LanguageServer):
    def __init__(self, language_id: str, log: bool = False):
        server_command = ["typescript-language-server", "--stdio"]
        super().__init__(language_id, server_command, log)
    
    def initialize(self, workspace_folders: list[str] | str, wait_time: float = 0.5):
        # NOTE: TsLanguageServer initialization does not response any message
        return super().initialize(workspace_folders, wait_time)
    
    def _get_capabilities(self) -> Dict:
        """
        Override the default capabilities to support code diagnostics
        """
        return {
            "textDocument": {
                "references": {"dynamicRegistration": True},
                "codeAction": {
                    "codeActionLiteralSupport": {
                        "codeActionKind": {
                            "valueSet": ["", "quickfix", "refactor", "refactor.extract", "refactor.inline",
                                       "refactor.rewrite", "source", "source.organizeImports"]
                        }
                    }
                },
                "synchronization": {
                    "dynamicRegistration": True,
                    "didSave": True
                },
                "publishDiagnostics": {
                    "relatedInformation": True,
                    "versionSupport": True
                }
            },
            "diagnostics": {
                "dynamicRegistration": True
            }
        }

    def diagnostics(self, file_path, wait_time: float = 3):
        """
        Override the default diagnostics method, typescript-language-server send response for each opened file.
        """
        if self.workspace_file_version.get(file_path, 0) == 0:
            self.did_open(file_path)
        else:
            self.did_change(file_path)
        
        expected_response_num = len(self.workspace_file_version)
        messages = self._get_messages(expect_method="textDocument/publishDiagnostics", message_num=expected_response_num, wait_time=wait_time)
        return messages

    def _parse_rename_response(self, response, edits, old_name, new_name):
        """
        Parse the response of rename request and update the edits
        
        Args:
            response: the response of rename request
            edits: the locations identified by lsp
            old_name: the old name of the identifier, not used in ts lsp, preserved for compatibility
            new_name: the new name of the identifier, not used in ts lsp, preserved for compatibility
        """
        for file_path, changes in response[0]["result"]["changes"].items():
            file_path = file_path[7:]
            if file_path not in edits:
                edits[file_path] = []
            edits[file_path].extend(changes)
        return edits
    
    def _filter_diagnostics(self, diagnostics, last_edit_at_range, init_diagnose_msg):
        """
        Filter the diagnostics by the last edit at range, more diagnostics please refer to: https://typescript.tv/errors/
        """
        with open("LSPs/typescript-language-server/typescript_diagnose_code.json", "r") as f:
            diagnose_codes = json.load(f)
            
        filtered_diagnostics = []
        for diagnostic in diagnostics:
            if not diagnostic["file_path"].endswith(".js") and \
            not diagnostic["file_path"].endswith(".ts") and \
            not diagnostic["file_path"].endswith(".tsx") and \
            not diagnostic["file_path"].endswith(".jsx"):
                continue
            if diagnostic["message"] in init_diagnose_msg:
                # If this diagnose already exists when the project is initialized, then this diagnose is not caused by user editing, no need to address
                continue
            if str(diagnostic["code"]) not in diagnose_codes:
                # well, we can't guarantee we have collected all errors ...
                continue
            if diagnose_codes[str(diagnostic["code"])]["whitelisted"]:
                if diagnostic["range"]["start"]["line"] in last_edit_at_range:
                    continue
                filtered_diagnostics.append(diagnostic)
        
        return filtered_diagnostics
    
if __name__ == "__main__":
    current_path = os.path.dirname(os.path.abspath(__file__))
    workspace = os.path.join(current_path, "projects/js_project")
    file_path = os.path.join(workspace, "src/app.js")
    
    server = TsLanguageServer("javascript", log=True)
    
    print(f">>>>>>>> Check initialize:")
    server.initialize(workspace)
    
    # Get the list of all file paths in the workspace
    file_paths = server.get_all_file_paths(workspace)
    server.open_in_batch(file_paths)
    
    print(f">>>>>>>> Check rename:")
    server.rename(file_path, {"line": 7, "character": 20}, "UserName")
    
    print(f">>>>>>>> Check references:")
    server.references(file_path, {"line": 8, "character": 8})
    
    print(f">>>>>>>> Check diagnostics:")
    server.diagnostics(file_path, wait_time=2)
    
    print(f">>>>>>>> Check close:")
    server.close()
    
    """
    Test Js Language Server on ts_project
    """
    current_path = os.path.dirname(os.path.abspath(__file__))
    workspace = os.path.join(current_path, "projects/ts_project")
    file_path = os.path.join(workspace, "src/main.ts")
    
    server = TsLanguageServer("typescript", log=True)
    
    print(f">>>>>>>> Check initialize:")
    server.initialize(workspace)
    
    # Get the list of all file paths in the workspace
    file_paths = server.get_all_file_paths(workspace)
    server.open_in_batch(file_paths)
    
    print(f">>>>>>>> Check rename:")
    server.rename(file_path, {"line": 12, "character": 17}, "ReversedString")
    
    # print(f">>>>>>>> Check references:")
    # server.references(file_path, {"line": 12, "character": 24})
    
    # print(f">>>>>>>> Check diagnostics:")
    # server.diagnostics(file_path, wait_time=2)
    
    print(f">>>>>>>> Check close:")
    server.close()
