I'm trying to write a zero-shot classifier prompt. My current prompt is:

<begin_of_prompt>
{{prompt}}
<end_of_prompt>

This prompt gets the following example correct:
{{text}}
The correct label is: {{correct_label}}
The predicted label is: {{predicted_label}}

Analyse why the prompt correctly classified the example, and summarize into a single sentence feedback. The feedback must:
1. Not use any generalized adjectives; your description should avoid vague expressions and instead be precise and specific.

2. Help clarify the decision boundary of the prompt, explicitly state the conditions under which the feedback applies and when it does not.

3. Wrap the feedback with <START> and <END> tags.