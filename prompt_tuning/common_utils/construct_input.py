"""
Construct model input for both partial order model and mental flow model.
"""

def deduplicate_edits(edit_list):
    seen = set()
    deduped = []

    for item in edit_list:
        detail = item["detail"]
        key = (
            detail["abs_file_path"],
            item["version"],
            tuple(sorted(detail["position"].items()))  # (start, end)
        )
        # position dict → tuple of tuples
        key = (
            detail["abs_file_path"],
            item["version"],
            (
                detail["position"]["start"]["line"],
                detail["position"]["start"]["column"],
                detail["position"]["end"]["line"],
                detail["position"]["end"]["column"],
            )
        )
        if key not in seen:
            seen.add(key)
            deduped.append(item)

    return deduped

def formalize_input(edit1, edit2):
    edit1_str = f"<file_path>{edit1['file_path']}</file_path>\n<structural_path>\n"
    edit2_str = f"<file_path>{edit2['file_path']}</file_path>\n<structural_path>\n"

    def construct_structual_and_control_flow(s, edit):
        for idx, structural_path in enumerate(edit['structural_path']):
            indent = "\t"* idx
            s += f"{indent}{structural_path['signature']}\n"
        s += "</structural_path>\n"
        # s += "<control_flow>\n"
        # if edit["control_flow"] is None:
        #     edit["control_flow"] = []
        # for idx, control_flow in enumerate(edit['control_flow'], start=len(edit['structural_path'])):
        #     indent = "\t"* idx
        #     s += f"{indent}{control_flow['statement']}\n"
        # s += "</control_flow>\n"
        s += "<code>\n"
        return s

    edit1_str = construct_structual_and_control_flow(edit1_str, edit1)
    edit2_str = construct_structual_and_control_flow(edit2_str, edit2)
    
    edit1_dep_info = []
    edit2_dep_info = []
    if edit1['commit_url'] == edit2['commit_url']:
        for dep_info in edit1["base_dependency_caller"] + edit1["base_dependency_callee"]:
            if dep_info["to_hunk_idx"] == edit2['idx']:
                dep_info["version"] = "base"
                edit1_dep_info.append(dep_info)
        for dep_info in edit1["head_dependency_callee"] + edit1["head_dependency_caller"]:
            if dep_info["to_hunk_idx"] == edit2['idx']:
                dep_info["version"] = "head"
                edit1_dep_info.append(dep_info)
        
        for dep_info in edit2["base_dependency_caller"] + edit2["base_dependency_callee"]:
            if dep_info["to_hunk_idx"] == edit1['idx']:
                dep_info["version"] = "base"
                edit2_dep_info.append(dep_info)
        for dep_info in edit2["head_dependency_callee"] + edit2["head_dependency_caller"]:
            if dep_info["to_hunk_idx"] == edit1['idx']:
                dep_info["version"] = "head"
                edit2_dep_info.append(dep_info)

    def construct_code(s, edit, dep_infos):
        dep_infos = deduplicate_edits(dep_infos)
        codes = []
        # for idx, code in enumerate(edit["prefix"], start=-len(edit["prefix"])):
        for idx, code in enumerate(edit["prefix"][-1:], start=-1):
            codes.append({
                "before_idx": edit["parent_version_range"]["start"] + idx,
                "after_idx": edit["child_version_range"]["start"] + idx,
                "code": code
            })

        for idx, code in enumerate(edit["before"], start = 0):
            codes.append({
                "before_idx": edit["parent_version_range"]["start"] + idx,
                "after_idx": None,
                "code": code
            })
        
        for idx, code in enumerate(edit["after"], start = 0):
            codes.append({
                "before_idx": None,
                "after_idx": edit["child_version_range"]["start"] + idx,
                "code": code
            })

        for idx, code in enumerate(edit["suffix"][:1], start = 0):
            codes.append({
                "before_idx": edit["parent_version_range"]["end"] + idx,
                "after_idx": edit["child_version_range"]["end"] + idx,
                "code": code
            })

        idxs = [len(str(code["before_idx"])) for code in codes if code["before_idx"] is not None]
        idxs.extend([len(str(code["after_idx"])) for code in codes if code["after_idx"] is not None])
        max_len = max(idxs) if idxs else 0

        for code in codes:
            if code["before_idx"] is None:
                code["before_idx"] = " " * max_len
                special_token = "+"
            elif code["after_idx"] is None:
                code["after_idx"] = " " * max_len
                special_token = "-"
            else:
                special_token = " "

            deps_at_this_line = []
            for dep in dep_infos:
                if dep["version"] == "base" and special_token == "-" and dep["detail"]["position"]["start"]["line"] == code["before_idx"]:
                    deps_at_this_line.append([dep["detail"]["position"]["start"]["column"], dep["detail"]["position"]["end"]["column"]])
                elif dep["version"] == "head" and special_token == "+" and dep["detail"]["position"]["start"]["line"] == code["after_idx"]:
                    deps_at_this_line.append([dep["detail"]["position"]["start"]["column"], dep["detail"]["position"]["end"]["column"]])
            # sort by start column
            deps_at_this_line.sort(key=lambda x: x[0])
            for idx, dep in enumerate(deps_at_this_line):
                # add offset to column
                dep[0] += 11 * idx
                dep[1] += 11 * idx
                # insert </dep> at dep[1] for code["code"]
                code["code"] = code["code"][:dep[1]] + "</dep>" + code["code"][dep[1]:]
                # insert <dep> at dep[0] for code["code"]
                code["code"] = code["code"][:dep[0]] + "<dep>" + code["code"][dep[0]:]

            if code["code"].strip() == "":
                to_print_code = "\\n \n"
            else:
                to_print_code = code["code"]
            s += f"{code['before_idx']:>{max_len}} {code['after_idx']:>{max_len}} {special_token}   {to_print_code}"

        s += "</code>\n"
        return s
        
    edit1_str = construct_code(edit1_str, edit1, edit1_dep_info)
    edit2_str = construct_code(edit2_str, edit2, edit2_dep_info)

    return edit1_str, edit2_str 

def formalize_single_input(edit1):
    edit1_str = f"<file_path>{edit1['file_path']}</file_path>\n<structural_path>\n"

    def construct_structual_and_control_flow(s, edit):
        for idx, structural_path in enumerate(edit['structural_path']):
            indent = "\t"* idx
            s += f"{indent}{structural_path['signature']}\n"
        s += "</structural_path>\n"
        # s += "<control_flow>\n"
        # if edit["control_flow"] is None:
        #     edit["control_flow"] = []
        # for idx, control_flow in enumerate(edit['control_flow'], start=len(edit['structural_path'])):
        #     indent = "\t"* idx
        #     s += f"{indent}{control_flow['statement']}\n"
        # s += "</control_flow>\n"
        s += "<code>\n"
        return s

    edit1_str = construct_structual_and_control_flow(edit1_str, edit1)

    def construct_code(s, edit, dep_infos):
        dep_infos = deduplicate_edits(dep_infos)
        codes = []
        for idx, code in enumerate(edit["prefix"][-1:], start=-len(edit["prefix"][-1:])):
            codes.append({
                "before_idx": edit["parent_version_range"]["start"] + idx,
                "after_idx": edit["child_version_range"]["start"] + idx,
                "code": code
            })

        for idx, code in enumerate(edit["before"], start = 0):
            codes.append({
                "before_idx": edit["parent_version_range"]["start"] + idx,
                "after_idx": None,
                "code": code
            })
        
        for idx, code in enumerate(edit["after"], start = 0):
            codes.append({
                "before_idx": None,
                "after_idx": edit["child_version_range"]["start"] + idx,
                "code": code
            })

        for idx, code in enumerate(edit["suffix"][:1], start = 0):
            codes.append({
                "before_idx": edit["parent_version_range"]["end"] + idx,
                "after_idx": edit["child_version_range"]["end"] + idx,
                "code": code
            })

        idxs = [len(str(code["before_idx"])) for code in codes if code["before_idx"] is not None]
        idxs.extend([len(str(code["after_idx"])) for code in codes if code["after_idx"] is not None])
        max_len = max(idxs) if idxs else 0

        for code in codes:
            if code["before_idx"] is None:
                code["before_idx"] = " " * max_len
                special_token = "+"
            elif code["after_idx"] is None:
                code["after_idx"] = " " * max_len
                special_token = "-"
            else:
                special_token = " "

            deps_at_this_line = []
            for dep in dep_infos:
                if dep["version"] == "base" and special_token == "-" and dep["detail"]["position"]["start"]["line"] == code["before_idx"]:
                    deps_at_this_line.append([dep["detail"]["position"]["start"]["column"], dep["detail"]["position"]["end"]["column"]])
                elif dep["version"] == "head" and special_token == "+" and dep["detail"]["position"]["start"]["line"] == code["after_idx"]:
                    deps_at_this_line.append([dep["detail"]["position"]["start"]["column"], dep["detail"]["position"]["end"]["column"]])
            # sort by start column
            deps_at_this_line.sort(key=lambda x: x[0])
            for idx, dep in enumerate(deps_at_this_line):
                # add offset to column
                dep[0] += 11 * idx
                dep[1] += 11 * idx
                # insert </dep> at dep[1] for code["code"]
                code["code"] = code["code"][:dep[1]] + "</dep>" + code["code"][dep[1]:]
                # insert <dep> at dep[0] for code["code"]
                code["code"] = code["code"][:dep[0]] + "<dep>" + code["code"][dep[0]:]

            s += f"{code['before_idx']:>{max_len}} {code['after_idx']:>{max_len}} {special_token}   {code['code']}"

        s += "</code>\n"
        return s
        
    edit1_str = construct_code(edit1_str, edit1, [])

    return edit1_str 

def formalize_negative_dependency_pair_input(edit1, edit2, shared_identifiers):
    edit1_str = f"<file_path>{edit1['file_path']}</file_path>\n<structural_path>\n"
    edit2_str = f"<file_path>{edit2['file_path']}</file_path>\n<structural_path>\n"

    def construct_structual_and_control_flow(s, edit):
        for idx, structural_path in enumerate(edit['structural_path']):
            indent = "\t"* idx
            s += f"{indent}{structural_path['signature']}\n"
        s += "</structural_path>\n"
        # s += "<control_flow>\n"
        # if edit["control_flow"] is None:
        #     edit["control_flow"] = []
        # for idx, control_flow in enumerate(edit['control_flow'], start=len(edit['structural_path'])):
        #     indent = "\t"* idx
        #     s += f"{indent}{control_flow['statement']}\n"
        # s += "</control_flow>\n"
        s += "<code>\n"
        return s

    edit1_str = construct_structual_and_control_flow(edit1_str, edit1)
    edit2_str = construct_structual_and_control_flow(edit2_str, edit2)
    
    edit1_dep_info = []
    edit2_dep_info = []
    for dep_info in edit1["base_dependency_caller"] + edit1["base_dependency_callee"]:
        if dep_info["detail"]["identifier"] in shared_identifiers:
            dep_info["version"] = "base"
            edit1_dep_info.append(dep_info)
    for dep_info in edit1["head_dependency_callee"] + edit1["head_dependency_caller"]:
        if dep_info["detail"]["identifier"] in shared_identifiers:
            dep_info["version"] = "head"
            edit1_dep_info.append(dep_info)
    
    for dep_info in edit2["base_dependency_caller"] + edit2["base_dependency_callee"]:
        if dep_info["detail"]["identifier"] in shared_identifiers:
            dep_info["version"] = "base"
            edit2_dep_info.append(dep_info)
    for dep_info in edit2["head_dependency_callee"] + edit2["head_dependency_caller"]:
        if dep_info["detail"]["identifier"] in shared_identifiers:
            dep_info["version"] = "head"
            edit2_dep_info.append(dep_info)

    def construct_code(s, edit, dep_infos):
        dep_infos = deduplicate_edits(dep_infos)
        codes = []
        for idx, code in enumerate(edit["prefix"], start=-len(edit["prefix"])):
            codes.append({
                "before_idx": edit["parent_version_range"]["start"] + idx,
                "after_idx": edit["child_version_range"]["start"] + idx,
                "code": code
            })

        for idx, code in enumerate(edit["before"], start = 0):
            codes.append({
                "before_idx": edit["parent_version_range"]["start"] + idx,
                "after_idx": None,
                "code": code
            })
        
        for idx, code in enumerate(edit["after"], start = 0):
            codes.append({
                "before_idx": None,
                "after_idx": edit["child_version_range"]["start"] + idx,
                "code": code
            })

        for idx, code in enumerate(edit["suffix"], start = 0):
            codes.append({
                "before_idx": edit["parent_version_range"]["end"] + idx,
                "after_idx": edit["child_version_range"]["end"] + idx,
                "code": code
            })

        idxs = [len(str(code["before_idx"])) for code in codes if code["before_idx"] is not None]
        idxs.extend([len(str(code["after_idx"])) for code in codes if code["after_idx"] is not None])
        max_len = max(idxs) if idxs else 0

        for code in codes:
            if code["before_idx"] is None:
                code["before_idx"] = " " * max_len
                special_token = "+"
            elif code["after_idx"] is None:
                code["after_idx"] = " " * max_len
                special_token = "-"
            else:
                special_token = " "

            deps_at_this_line = []
            for dep in dep_infos:
                if dep["version"] == "base" and special_token == "-" and dep["detail"]["position"]["start"]["line"] == code["before_idx"]:
                    deps_at_this_line.append([dep["detail"]["position"]["start"]["column"], dep["detail"]["position"]["end"]["column"]])
                elif dep["version"] == "head" and special_token == "+" and dep["detail"]["position"]["start"]["line"] == code["after_idx"]:
                    deps_at_this_line.append([dep["detail"]["position"]["start"]["column"], dep["detail"]["position"]["end"]["column"]])
            # sort by start column
            deps_at_this_line.sort(key=lambda x: x[0])
            for idx, dep in enumerate(deps_at_this_line):
                # add offset to column
                dep[0] += 11 * idx
                dep[1] += 11 * idx
                # insert </dep> at dep[1] for code["code"]
                code["code"] = code["code"][:dep[1]] + "</dep>" + code["code"][dep[1]:]
                # insert <dep> at dep[0] for code["code"]
                code["code"] = code["code"][:dep[0]] + "<dep>" + code["code"][dep[0]:]

            s += f"{code['before_idx']:>{max_len}} {code['after_idx']:>{max_len}} {special_token}   {code['code']}"

        s += "</code>\n"
        return s
        
    edit1_str = construct_code(edit1_str, edit1, edit1_dep_info)
    edit2_str = construct_code(edit2_str, edit2, edit2_dep_info)

    return edit1_str, edit2_str 

def formalize_1_and_others(edits, target_edit_idx):
    def construct_structual_and_control_flow(s, edit):
        for idx, structural_path in enumerate(edit['structural_path']):
            indent = "\t"* idx
            s += f"{indent}{structural_path['signature']}\n"
        s += "</structural_path>\n<control_flow>\n"
        if edit["control_flow"] is None:
            edit["control_flow"] = []
        for idx, control_flow in enumerate(edit['control_flow'], start=len(edit['structural_path'])):
            indent = "\t"* idx
            s += f"{indent}{control_flow['statement']}\n"
        s += "</control_flow>\n<code>\n"
        return s

    def construct_code(s, edit, dep_infos):
        dep_infos = deduplicate_edits(dep_infos)
        codes = []
        for idx, code in enumerate(edit["prefix"], start=-len(edit["prefix"])):
            codes.append({
                "before_idx": edit["parent_version_range"]["start"] + idx,
                "after_idx": edit["child_version_range"]["start"] + idx,
                "code": code
            })

        for idx, code in enumerate(edit["before"], start = 0):
            codes.append({
                "before_idx": edit["parent_version_range"]["start"] + idx,
                "after_idx": None,
                "code": code
            })
        
        for idx, code in enumerate(edit["after"], start = 0):
            codes.append({
                "before_idx": None,
                "after_idx": edit["child_version_range"]["start"] + idx,
                "code": code
            })

        for idx, code in enumerate(edit["suffix"], start = 0):
            codes.append({
                "before_idx": edit["parent_version_range"]["end"] + idx,
                "after_idx": edit["child_version_range"]["end"] + idx,
                "code": code
            })

        idxs = [len(str(code["before_idx"])) for code in codes if code["before_idx"] is not None]
        idxs.extend([len(str(code["after_idx"])) for code in codes if code["after_idx"] is not None])
        max_len = max(idxs) if idxs else 0

        for code in codes:
            if code["before_idx"] is None:
                code["before_idx"] = " " * max_len
                special_token = "+"
            elif code["after_idx"] is None:
                code["after_idx"] = " " * max_len
                special_token = "-"
            else:
                special_token = " "

            deps_at_this_line = []
            for dep in dep_infos:
                if dep["version"] == "base" and special_token == "-" and dep["detail"]["position"]["start"]["line"] == code["before_idx"]:
                    deps_at_this_line.append([dep["detail"]["position"]["start"]["column"], dep["detail"]["position"]["end"]["column"]])
                elif dep["version"] == "head" and special_token == "+" and dep["detail"]["position"]["start"]["line"] == code["after_idx"]:
                    deps_at_this_line.append([dep["detail"]["position"]["start"]["column"], dep["detail"]["position"]["end"]["column"]])
            # sort by start column
            deps_at_this_line.sort(key=lambda x: x[0])
            for idx, dep in enumerate(deps_at_this_line):
                # add offset to column
                dep[0] += 11 * idx
                dep[1] += 11 * idx
                # insert </dep> at dep[1] for code["code"]
                code["code"] = code["code"][:dep[1]] + "</dep>" + code["code"][dep[1]:]
                # insert <dep> at dep[0] for code["code"]
                code["code"] = code["code"][:dep[0]] + "<dep>" + code["code"][dep[0]:]

            s += f"{code['before_idx']:>{max_len}} {code['after_idx']:>{max_len}} {special_token}   {code['code']}"

        s += "</code>\n"
        return s
    
    def get_dep_info(edit, target_edit_idx):
        dep_infos = []
        if edit["idx"] == target_edit_idx:
            for dep_info in edit["base_dependency_caller"] + edit["base_dependency_callee"]:
                dep_info["version"] = "base"
                dep_infos.append(dep_info)
            for dep_info in edit["head_dependency_callee"] + edit["head_dependency_caller"]:
                dep_info["version"] = "head"
                dep_infos.append(dep_info)
            return dep_infos
        
        for dep_info in edit["base_dependency_caller"] + edit["base_dependency_callee"]:
            if dep_info["to_hunk_idx"] == target_edit_idx:
                dep_info["version"] = "base"
                dep_infos.append(dep_info)
        for dep_info in edit["head_dependency_callee"] + edit["head_dependency_caller"]:
            if dep_info["to_hunk_idx"] == target_edit_idx:
                dep_info["version"] = "head"
                dep_infos.append(dep_info)
        return dep_infos
                
    edit_strs = []
    for idx, edit in enumerate(edits):
        dep_info = get_dep_info(edit, target_edit_idx)
        edit_str = f"<Edit {idx}>\n<file_path>{edit['file_path']}</file_path>\n<structural_path>\n"
        edit_str = construct_structual_and_control_flow(edit_str, edit)
        edit_str = construct_code(edit_str, edit, dep_info)
        edit_str += f"</Edit {idx}>\n"
        edit_strs.append(edit_str)
        
    return edit_strs