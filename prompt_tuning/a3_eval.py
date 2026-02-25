from a2_main import *
from sklearn.metrics import precision_score, recall_score, f1_score

if __name__ == "__main__":
    random.seed(42)  # For reproducibility
    args = get_args()

    args.resume_from_prompt = "baseline_prompts/ours.md"
    args.resume_from_prompt = "baseline_prompts/zeroshot.md"
    args.resume_from_prompt = "baseline_prompts/fewshot.md"
    args.resume_from_prompt = "baseline_prompts/handcraft.md"
    with open(args.resume_from_prompt, "r") as f:
        best_prompt = f.read()
    
    os.makedirs(args.output_dir, exist_ok=True)
    current_time = time.strftime("%Y-%m-%d-%H-%M-%S")
    args.output_dir = os.path.join(args.output_dir, f"{current_time}")
    os.makedirs(args.output_dir, exist_ok=True)

    dataset = load_dataset(args.test_file)

    best_prompt, best_prompt_performance, best_accuracy, results_map = evaluate_prompts([best_prompt], dataset, args)

    golds = [p["yi"] for p in best_prompt_performance]
    preds = [p["pred"] for p in best_prompt_performance]
    # get precision, recall, f1
    precision = precision_score(golds, preds, average="weighted")
    recall = recall_score(golds, preds, average="weighted")
    f1 = f1_score(golds, preds, average="weighted")

    # save best prompt and corresponding performance
    print(f"Accuracy: {best_accuracy*100:.2f}%")
    print(f"Precision: {precision*100:.2f}%")
    print(f"Recall: {recall*100:.2f}%")
    print(f"F1: {f1*100:.2f}%")
    with open(os.path.join(args.output_dir, f"best_prompt_candidates_performance.json"), "w") as f:
        json.dump(results_map, f, indent=4)