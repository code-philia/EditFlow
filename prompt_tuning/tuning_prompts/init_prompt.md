# Task

In a code editing session, a developer has just completed edit e0, and the system now recommends edit e1 (or the opposite). The task is to determine whether the developer would immediately and naturally recognize the necessity of performing the suggested e1 as the next step, without shifting intent, consulting external knowledge, or changing cognitive context. 

Edits can be classified into four types: 0 before 1, 1 before 0, bi-directional, and no relation. 

Importantly, a uni-directional label like 0 before 1 does not depend on whether performing e1 before e0 causes a temporary compiler or lint error. Temporary errors are acceptable and even expected during editing. Similarly, dependency direction is not a valid reason for assigning a directional label. A uni-directional relation simply means that a programmer would never perform the edits in reverse order—for example, a developer would not paste code before cutting it. A bi-directional relation means that either edit, when performed first, would immediately suggest the other as the natural next step. A no relation label applies when the two edits are mentally disconnected and should not occur consecutively in a natural editing flow.

# Examples

{{examples}}

# Response

- Comprehend why example edit pairs are given such partial order label, rewrite the # Task section to clearly define the criteria for neighbouring code edits in mental flow. 
- Exclude the response schema. 
- Ensure that the definition is concise and captures the essence of the examples provided. 
- You may summarize common patterns or characteristics observed in the examples to enhance clarity.
- Wrap the rewritten section between <START> and <END> tags.

