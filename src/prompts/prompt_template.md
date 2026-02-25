# Task
{{core_instruction}}

# Response schema
Answer in json format, with 2 keys: 
- "pred_reason": explain why the partial order the predicted direction
- "order": choose from: "0 before 1", "1 before 0", "bi-directional" and "no relation"
- "confidence": a float number from 0 ~ 1, indicating your confidence of the answer

Return only the JSON object, no extra text, do not enclose json in ```json ```

# Edit pair
{{text}}

# Response