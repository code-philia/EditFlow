import os
import json
from sklearn.metrics import precision_score, recall_score, f1_score, accuracy_score

for result in os.listdir("experiment_result"):
    with open(os.path.join("experiment_result", result), "r") as file:
        data = json.load(file)

    best_prompt_performance = data["0"]
    golds = [p["yi"] for p in best_prompt_performance]
    preds = [p["pred"] for p in best_prompt_performance]
    
    # get precision, recall, f1
    accuracy = accuracy_score(golds, preds)
    precision = precision_score(golds, preds, average="weighted")
    recall = recall_score(golds, preds, average="weighted")
    f1 = f1_score(golds, preds, average="weighted")

    # save best prompt and corresponding performance
    print(result)
    print(f"Accuracy: {accuracy*100:.2f}%")
    print(f"Precision: {precision*100:.2f}%")
    print(f"Recall: {recall*100:.2f}%")
    print(f"F1: {f1*100:.2f}%")
    print("="*30)