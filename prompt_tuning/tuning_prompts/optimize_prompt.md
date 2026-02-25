I'm trying to write a zero-shot classifier prompt. My current prompt is:

<begin_of_prompt>
{{prompt}}
<end_of_prompt>

Based on this prompt, the LLM made predictions on several examples. Below are the ground-truth labels, predicted labels, prediction reasons, and corresponding feedback for each example.
<begin_of_examples>
{{examples}}
<end_of_examples>

Based on the above information, please optimize the prompt to improve its performance. Note that your prompt should be informative, and free of contradiction. The optimized version should strike a balance between appropriate abstraction and necessary specificity.
Wrapped the optimized prompt with <START> and <END> tags.