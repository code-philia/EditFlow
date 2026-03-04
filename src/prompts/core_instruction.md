# Zero-Shot Code Edit Neighbour Classification Criteria (Optimized)

A pair of code edits are "neighbours in mental flow" if, and only if, making one edit creates an **immediate, mechanically obvious, code-driven prompt for the other as the next contiguous action, within a single uninterrupted micro-task**. This linkage exists only when there is a direct, explicit code dependency or a mirrored, structurally identical substitution between the changed lines themselves—not merely due to shared conceptual, feature, or thematic context.

---

## 1. Core Criteria

### **A. Explicit, Immediate Code Linkage**
- The changed line(s) in one edit must create a concrete, visible, and direct syntactic or structural prompt for the other—such as a newly undefined symbol, changed signature, altered import, or mirrored/duplicated pattern—making the companion edit the next mechanically required step.
- The relationship must be at the **locus of change**: that is, the specific symbol, parameter, import, or structural element referenced, assigned, or called in the changed lines must be the same in both edits.
- **Critical distinction**: The changed lines must reference, assign, call, or import the **exact same symbol** (function name, variable name, class name, etc.), not merely symbols with the same name in different scopes.

### **B. Unbroken Micro-task Flow**
- Both edits would naturally occur in one contiguous, uninterrupted micro-task, with no context switch, pause for deliberation, or shift in editing intent.

### **C. Structural or Syntactic Dependency**
- The code linkage must be evident in the changed lines themselves—via explicit reference, assignment, call, or uniform substitution—not merely by affecting the same symbol elsewhere or sharing the same feature.

### **D. Not Neighbours: No Conceptual, Thematic, or Feature-Based Linking**
- **Do NOT** label edits as neighbours if their only relationship is conceptual or thematic (e.g., both relate to the same feature, add a similarly named variable, or are part of the same logical change) without a direct code dependency or mirrored substitution in the changed lines.

---

## 2. Neighbouring Patterns (with Language-Specific Guidance)

### **A. Definition–Usage / Import–Usage / Signature–Caller**
- **Bi-directional**:  
    - If each edit's changed lines reference the **exact same fully qualified symbol** (e.g., function, parameter, import, class), where after making either edit, the other edit becomes the next immediate, code-driven step.
    - Applies to:  
        - Function/class signature change ↔ call-site update for the **same function/class**
        - Import ↔ usage **within the same file**
        - Parameter rename ↔ in-body reference update **within the same function**
        - Method definition change ↔ test assertion update **for the exact same method**

- **Cross-file definition-usage**: Only label as bi-directional if:
    - One edit defines a function/class and another edit calls that **exact same function/class**, AND
    - Both edits appear to be part of the same development session where the symbol is being introduced and immediately used

- **Ordered ("X before Y")**:  
    - Use **only if** the second edit cannot be parsed, saved, or staged *at all* until the first is present—e.g., syntax error, parser error, or language-level blockage.
    - **Do NOT** use ordered if the only consequence is a runtime or import-time error (e.g., NameError, AttributeError, TypeError)—if both edits can be written and parsed in either order, the relation is bi-directional.

- **Language-specific (Python)**:  
    - In Python, referencing an undefined variable, attribute, or symbol (including in function bodies, attribute access, or type annotations) is allowed at parse time and only fails at runtime or upon execution/import.  
    - Therefore, definition–usage, import–usage, or signature–caller edits are **bi-directional** unless the second edit would produce a parser-level syntax error if staged before the first.
    - Adding a symbol to `__all__` is bi-directional with defining that symbol (not ordered) since `__all__` is processed during import resolution, not execution.

### **B. Bulk-Edit & Pattern Synchronization**
- **Bi-directional**:  
    - If both edits perform an **identical textual or structural substitution** (same before→after pattern) AND target the **same type of syntactic construct** (e.g., both import lines, both function signatures, both parameter lists).
    - Must be clearly part of a single, contiguous refactor or search-and-replace sweep.
    - **Examples**: Changing "datetime.datetime" to "datetime" in multiple locations, adding the same parameter to multiple function signatures of the same class.

### **C. Mirrored/Synchronized Additions Within Same Context**
- **Bi-directional**:  
    - Simultaneous addition of parameters/attributes with the same name and structure in the **same function, class, or closely related context** (e.g., adding a parameter to both a constructor and its corresponding mock assertion **within the same test method**).
    - Parameter threading: Adding a parameter to an outer function signature and adding the same parameter to an inner function signature **when both changed lines explicitly reference the parameter**.

### **D. Test-Production Code Synchronization**
- **Bi-directional** when:
    - One edit changes a method signature/behavior and another edit updates test assertions **for that exact same method**
    - One edit changes implementation return values and another edit updates test expectations **for that exact implementation**
    - Adding parameters to both constructor calls and their corresponding mock assertions **within the same test function**

### **E. Configuration-Implementation Synchronization**
- **Bi-directional** when:
    - Adding identical parameters to both a configuration class and its corresponding implementation class **where both classes form a direct config-implementation pair**
    - Parameter additions that create synchronized API contracts between classes that directly depend on each other

---

## 3. Not Neighbours ("no relation")

Label as "no relation" if:

- The only connection is conceptual, thematic, or feature-based.
- Both edits affect code with the same identifier name, but the changed lines reference **different symbols** (same name, different scopes/contexts).
- Edits add, remove, or alter code with the same name in different scopes, functions, classes, or files, without the **exact same symbol** being referenced in both changed lines.
- One hunk changes a usage or call, and the other changes a definition or import **for a different symbol** (even if names match).
- Cross-file edits where one file defines something and another file uses something with the same name, unless both are part of a uniform, synchronized multi-file substitution or the same development session.
- Parameter additions to unrelated functions/classes that happen to use the same parameter name.
- Documentation changes and code changes that merely reference the same concept without direct symbol linkage.
- Removing identical helper functions from separate files (cleanup operations).
- Adding the same parameter name to different functions without direct call relationships.

---

## 4. Label Assignment

- **Bi-directional:**  
    - Either edit can be staged first, and after making either, the other is the immediate, code-driven next step due to explicit code linkage or synchronized pattern.  
    - The **exact same symbol** is referenced, assigned, called, or imported in both changed lines.
    - Use for definition–usage of the same symbol, import–usage in same file, signature–caller for same function, parameter threading with explicit references, test-production synchronization for same methods.

- **Ordered ("X before Y"):**  
    - Use **only** when the second edit cannot be written, parsed, or staged at all until the first is present (i.e., parser-level syntax break, missing required definition at parse time, language-level blockage).
    - **Do NOT** use for runtime-only errors or cases where both hunks can be staged regardless of order.
    - Cut-and-paste moves (remove symbol from one location, add to another location).

- **No Relation:**  
    - Use when the linkage is only conceptual or thematic, or when the changed lines reference **different symbols** (even if they have the same name), or when there is no direct, explicit code dependency or synchronized substitution at the locus of change.

---

## 5. Disambiguation & Special Cases

- **Same Name, Different Symbols:**  
    - If edits involve identifiers with the same name but in different scopes (different functions, classes, files), they reference **different symbols** and should be labeled "no relation" unless there is explicit cross-reference in the changed lines.

- **Parameter/Attribute Usage vs. Definition:**  
    - Only label as neighbours when the **exact same parameter/attribute symbol** is being defined in one edit and referenced in another edit's changed lines.
    - Adding a parameter to a function signature and using a different variable with the same name = "no relation".

- **Cross-file Relationships:**  
    - Generally "no relation" unless: (1) part of uniform multi-file substitution, (2) same development session with immediate definition-usage, or (3) direct symbol reference between changed lines.

- **Test Helper and Production Code:**  
    - Only bi-directional when test code directly asserts on or calls the **exact same symbol** being modified in production code.

- **Bulk Substitutions:**  
    - Must involve **identical before→after patterns** on the **same type of syntactic construct**. Different construct types (e.g., docstring vs. validation dict) = "no relation".

- **Documentation vs. Code:**  
    - Generally "no relation" unless both edits reference the **exact same symbol** and the documentation change directly corresponds to the code change for that symbol.

---

> **KEY PRINCIPLE: The changed lines must reference, assign, call, or import the EXACT SAME SYMBOL. Symbols with identical names in different scopes are DIFFERENT SYMBOLS.**
>
> **When in doubt, ask:** Do the changed lines reference the exact same symbol? If not, label as "no relation".

---

## 6. Summary Table

| Scenario                                            | Label           | Notes                                                                                   |
|-----------------------------------------------------|-----------------|-----------------------------------------------------------------------------------------|
| Function signature change ↔ call-site update (same function) | Bi-directional  | Unless call-site update causes a parse error (rare in Python; then ordered)             |
| Import ↔ usage (same file, Python)                  | Bi-directional  | Usage before import is allowed (runtime NameError only)                                 |
| Parameter addition ↔ body reference (same function) | Bi-directional  | No parser error in either order                                                         |
| Cross-file definition ↔ usage (same symbol, same session) | Bi-directional | Only when both edits reference the exact same symbol                                    |
| Bulk uniform substitution (same construct type)     | Bi-directional  | Only if before→after pattern and construct type are identical                           |
| Cut-and-paste move (delete here, insert there)      | Ordered         | Removal must occur before relocation                                                    |
| Same name, different scopes                         | No relation     | Different symbols despite identical names                                               |
| Cross-file usage ↔ import (no synchronization)      | No relation     | Unless part of uniform, mirrored multi-file substitution                               |
| Conceptual or feature-based link only               | No relation     | No explicit, code-driven linkage between exact same symbols                            |
| Parameter additions to unrelated functions          | No relation     | Even with identical parameter names                                                     |
| Documentation ↔ code (different symbols)            | No relation     | Unless both reference the exact same symbol                                             |

---

**Remember:**  
- The label is determined by whether the changed lines reference, assign, call, or import the **exact same symbol**.
- "Ordered" is rare in Python and applies **only** when the second edit cannot be written, parsed, or staged before the first.
- "Bi-directional" applies when both edits reference the same symbol and either naturally prompts the other as the next mechanical step.
- "No relation" applies when edits reference different symbols or lack direct code linkage, regardless of conceptual similarity.