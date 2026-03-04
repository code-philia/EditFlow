import os
import time
import json
import common_utils.ask_llm as ask_llm
import random
import argparse
import itertools
import concurrent.futures

from tqdm import tqdm
from typing import List, Dict
from collections import defaultdict

def get_args():
    """Get command line arguments."""
    parser = argparse.ArgumentParser()
    
    # Dataset arguments 
    parser.add_argument("--train_file", type=str, default="dataset/train.json")
    parser.add_argument("--test_file", type=str, default="dataset/test.json")
    parser.add_argument("--prompt_dir", type=str, default="tuning_prompts", help="Directory containing prompt templates")
    parser.add_argument("--output_dir", type=str, default="output", help="Directory to save output files")

    # Training arguments
    parser.add_argument("--train_data_size", type=int, default=2030, help="Size of training data")
    parser.add_argument("--init_batch_size", type=int, default=128, help="Batch size for initial prompt generation")
    parser.add_argument("--batch_size", type=int, default=32)
    parser.add_argument("--init_epoch", type=int, default=0)
    parser.add_argument("--epoch_num", type=int, default=2)
    parser.add_argument("--max_optimize_retry", type=int, default=3)
    parser.add_argument("--false_sample_feedback_only", type=bool, default=True)
    parser.add_argument("--resume_from_prompt", type=str, default=None, help="Whether to resume from the last prompt")
    parser.add_argument("--resume_from_prompt_performance", type=str, default=None, help="Path to the prompt performance file to resume from")

    # Execution arguments
    parser.add_argument("--thread_size", type=int, default=8, help="Number of threads to use for parallel processing")

    args, _ = parser.parse_known_args()
    return args

def batchify_data(data, args, best_prompt_performance=None):
    if best_prompt_performance is None:
        # Create a copy and shuffle the data
        data_copy = data.copy()
        batch_size = args.init_batch_size
        batches = []
        for i in range(0, len(data_copy) - batch_size + 1, batch_size):
            batches.append(data_copy[i:i + batch_size])
        # Drop the last batch if it's smaller than batch_size

        assert all(isinstance(batch, list) for batch in batches), "batches must be a list of lists"
        assert all(isinstance(sample, dict) for batch in batches for sample in batch), "each batch item must be a dict"
        assert all(all(key in sample for key in ['sample_idx', 'text', 'label', 'commit_url', 'edit_hunk_pair']) 
              for batch in batches for sample in batch), "each dict must contain required keys"
        return batches
    elif not args.false_sample_feedback_only:
        # Create balanced batches with same percentage of positive and negative samples
        batch_size = args.batch_size
        batches = []

        pos_samples = [sample for sample in best_prompt_performance if sample["yi"] == sample["pred"]]
        neg_samples = [sample for sample in best_prompt_performance if sample["yi"] != sample["pred"]]

        pos_percentage = len(pos_samples) / len(best_prompt_performance)

        pos_per_batch = int(batch_size * pos_percentage)
        neg_per_batch = batch_size - pos_per_batch
        if neg_per_batch < 1:
            neg_per_batch = 1
            pos_per_batch = batch_size - neg_per_batch
        elif pos_per_batch < 1:
            pos_per_batch = 1
            neg_per_batch = batch_size - pos_per_batch

        print(f"Batch size: {batch_size} (+ {pos_per_batch} / - {neg_per_batch})")

        batch_num = min(len(pos_samples) // pos_per_batch, len(neg_samples) // neg_per_batch)
        for i in range(batch_num):
            pos_batch = pos_samples[i * pos_per_batch:(i + 1) * pos_per_batch] # [sample_idx, yi, pred]
            neg_batch = neg_samples[i * neg_per_batch:(i + 1) * neg_per_batch] # [sample_idx, yi, pred]
            
            batch = []
            for mix_sample in pos_batch + neg_batch:
                sample_idx = mix_sample["sample_idx"]
                sample = data[sample_idx]
                assert sample["sample_idx"] == sample_idx, "Sample ID mismatch"
                sample["pred"] = mix_sample["pred"]
                sample["pred_reason"] = mix_sample["pred_reason"]
                batch.append(sample)
            batches.append(batch)

        # put the rest of samples into a batch
        if len(pos_samples) > batch_num * pos_per_batch:
            rest_pos_samples = pos_samples[batch_num * pos_per_batch:]
        else:
            rest_pos_samples = []
        if len(neg_samples) > batch_num * neg_per_batch:
            rest_neg_samples = neg_samples[batch_num * neg_per_batch:]
        else:
            rest_neg_samples = []
        rest_samples = rest_pos_samples + rest_neg_samples
        if rest_samples:
            batch = []
            for rest_sample in rest_samples:
                sample_idx = rest_sample["sample_idx"]
                sample = data[sample_idx]
                assert sample["sample_idx"] == sample_idx, "Sample ID mismatch"
                sample["pred"] = rest_sample["pred"]
                sample["pred_reason"] = rest_sample["pred_reason"]
                batch.append(sample)
                if len(batch) == batch_size:
                    batches.append(batch)
                    batch = []
            if batch:  # If there are remaining samples in the last batch
                batches.append(batch)

        assert all(isinstance(batch, list) for batch in batches), "batches must be a list of lists"
        assert all(isinstance(sample, dict) for batch in batches for sample in batch), "each batch item must be a dict"
        assert all(all(key in sample for key in ['sample_idx', 'text', 'label', 'pred', 'commit_url', 'edit_hunk_pair', 'pred_reason']) 
              for batch in batches for sample in batch), "each dict must contain required keys"

        return batches
    
    elif args.false_sample_feedback_only:
        batch_size = args.batch_size
        batches = []

        neg_samples = [sample for sample in best_prompt_performance if sample["yi"] != sample["pred"]]

        print(f"False samples: {len(neg_samples)}")

        batch = []
        for neg_sample in neg_samples:
            sample_idx = neg_sample["sample_idx"]
            sample = data[sample_idx]
            assert sample["sample_idx"] == sample_idx, "Sample ID mismatch"
            sample["pred"] = neg_sample["pred"]
            sample["pred_reason"] = neg_sample["pred_reason"]
            batch.append(sample)
            if len(batch) == batch_size:
                batches.append(batch)
                batch = []
        if batch:  # If there are remaining samples in the last batch
            batches.append(batch)

        assert all(isinstance(batch, list) for batch in batches), "batches must be a list of lists"
        assert all(isinstance(sample, dict) for batch in batches for sample in batch), "each batch item must be a dict"
        assert all(all(key in sample for key in ['sample_idx', 'text', 'label', 'pred', 'commit_url', 'edit_hunk_pair', 'pred_reason']) 
              for batch in batches for sample in batch), "each dict must contain required keys"

        return batches

def parse_tagged_text(text, start_tag, end_tag):
    """ Parse text that is tagged with start and end tags."""
    texts = []
    while True:
        start_index = text.find(start_tag)
        if start_index == -1:
            break
        end_index = text.find(end_tag, start_index)
        if end_index == -1:
            break
        start_index += len(start_tag)
        texts.append(text[start_index:end_index].strip())
        text = text[end_index+len(end_tag):]
    return texts

def _generate_initial_prompts(batch, prompt_dir):
    """Process a single batch of examples and generate LLM prompt."""
    with open(os.path.join(prompt_dir, "init_prompt.md"), "r") as f:
        prompt_template = f.read()

    examples = ""
    for sample in batch:
        id = sample["sample_idx"]
        text = sample["text"]
        label = sample["label"]
        examples += f"<Example {id}>\n{text}\nPartial order label of Example {id}: {label}\n</Example {id}>\n"
    prompt = prompt_template.replace("{{examples}}", examples)
    while True:
        response = ask_llm.chatgpt(prompt)[0]
        response = parse_tagged_text(response, "<START>", "<END>")

        if response and len(response) > 0:
            return response[0]
        else:
            # print(f"Failed to generate initial prompt for batch.\nRetrying...")
            time.sleep(1)

def generate_initial_prompts(batches, args):
    """
    Given a list of batches, construct a prompt for each, call utils.chatgpt in parallel,
    and return the responses.

    Args:
        batches (List[Any]): A list of batch inputs.
        args: Arguments containing prompt_dir and thread_size.

    Returns:
        List[str]: A list of ChatGPT responses, one per batch.
    """
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.thread_size) as executor:
        futures = [
            executor.submit(_generate_initial_prompts, batch, args.prompt_dir) 
            for batch in batches
        ]
        responses = [future.result() for future in concurrent.futures.as_completed(futures)]

    return responses

def _evaluate_prompts(task, prompt_dir):
    with open(os.path.join(prompt_dir, "task_prompt.md"), "r") as f:
        input_template = f.read()

    input_template = input_template.replace("{{prompt}}", task["prompt"])
    input_template = input_template.replace("{{text}}", task["xi"])
    
    query_input = input_template

    retry = 0
    while True:
        try: 
            response = ask_llm.chatgpt(query_input)[0]
            if "```json" in response:
                response = response[7:-3]
            response = json.loads(response)
            pred = response['order']
            pred_reason = response['pred_reason']
            break
        except Exception as e:
            print(f"Encounter error {e}, retrying...")
            retry += 1
            if retry >= ask_llm.MAX_RETRIES:
                raise e
            time.sleep(1)
            continue

    return {
        "prompt_idx": task["prompt_idx"],
        "sample_idx": task["sample_idx"],
        "yi": task["yi"],
        "pred": pred,
        "pred_reason": pred_reason
    }

def evaluate_prompts(prompts, data, args, return_best=True):
    """
    Evaluate each prompt on the full training dataset.
    For every prompt and every training example, call utils.chatgpt and record predictions.
    Uses parallel processing to speed up evaluation.

    Args:
        prompts (List[str]): List of prompts to evaluate.
        data (List[dict]): Training data containing keys: text, label, and other metadata.
        args: Argument object with thread_size and other options.
        return_best (bool, optional): Whether to return only the best prompt and its performance.
            If False, returns all results. Defaults to True.

    Returns:
        If return_best=True:
            Tuple[str, List[dict], float, dict]: The best-performing prompt, its performance
            metrics, accuracy, and all evaluation results.
        If return_best=False:
            dict: All evaluation results mapped by prompt index.
    """
    all_tasks = [
        {
            "prompt": prompt,
            "xi": sample["text"],
            "yi": sample["label"],
            "prompt_idx": k,
            "sample_idx": sample["sample_idx"]
        }
        for k, prompt in enumerate(prompts)
        for sample in data
    ]
    print(f"Total queries for evaluation: {len(prompts)} prompts * {len(data)} training samples = {len(all_tasks)}")
    results_map = defaultdict(list)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.thread_size) as executor:
        # Create a list of futures for each task
        futures = [
            executor.submit(_evaluate_prompts, task, args.prompt_dir) 
            for task in all_tasks
        ]

        # Use tqdm wrap as_completed iterator to show progress
        for future in tqdm(
            concurrent.futures.as_completed(futures),
            total=len(futures),
            desc="Evaluating prompts"
        ):
            try:
                result = future.result()
                results_map[result["prompt_idx"]].append({
                    "sample_idx": result["sample_idx"],
                    "yi": result["yi"],
                    "pred": result["pred"],
                    "pred_reason": result["pred_reason"]
                })
            except Exception:
                raise ValueError("Error in evaluating a prompt:", future.exception())
    print("")

    best_accuracy = 0
    best_prompt_idx = 0
    for prompt_idx, performance in results_map.items():
        golds = [p["yi"] for p in performance]
        preds = [p["pred"] for p in performance]
        accuracy = sum(1 for g, p in zip(golds, preds) if g == p) / len(golds)
        if accuracy > best_accuracy:
            best_accuracy = accuracy
            best_prompt_idx = prompt_idx

    best_prompt = prompts[best_prompt_idx]
    best_prompt_performance = results_map[best_prompt_idx]

    if return_best:
        return best_prompt, best_prompt_performance, best_accuracy, results_map
    else:
        return results_map

def reoptimization(prompt, target_batch, target_feedbacks, args):
    optimize_task = {
        "prompt": prompt,
        "feedbacks": target_feedbacks,
        "batch_idx": 0,
        "batch": target_batch
    }
    reoptimized_prompt = _feedback_integration(optimize_task, args.prompt_dir)["optimized_prompt"]
    return reoptimized_prompt

def verify_optimized_prompt(prompt, batch, batch_idx, retry_cnt):
    evaluate_tasks = [
        {
            "prompt": prompt,
            "xi": sample["text"],
            "yi": sample["label"],
            "prompt_idx": 0,
            "sample_idx": i
        }
        for i, sample in enumerate(batch)
    ]
    print(f"Total queries for evaluation reoptimized prompt at retry {retry_cnt}: 1 prompts * {len(batch)} training samples = {len(evaluate_tasks)}")

    results_map = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.thread_size) as executor:
        futures = [executor.submit(_evaluate_prompts, task, args.prompt_dir) for task in evaluate_tasks]
        for future in tqdm(concurrent.futures.as_completed(futures), total=len(futures), desc="Verifying Optimized Prompts"):
            try:
                result = future.result()
                results_map.append({
                    "sample_idx": result["sample_idx"],
                    "yi": result["yi"],
                    "pred": result["pred"],
                    "pred_reason": result["pred_reason"]
                })
            except Exception:
                raise ValueError("Error in verifying a prompt:", future.exception())
    print("")
            
    pre_optimize_accuracy = sum(1 for sample in batch if sample["label"] == sample["pred"]) / len(batch)
    post_reoptimize_accuracy = sum(1 for sample in results_map if sample["yi"] == sample["pred"]) / len(results_map)

    if post_reoptimize_accuracy <= pre_optimize_accuracy:
        print(f"Batch {batch_idx} encounter performance drop at retry {retry_cnt}: {pre_optimize_accuracy*100:.4f}% --> {post_reoptimize_accuracy*100:.4f}%")
        return False
    else:
        print(f"Batch {batch_idx} encounter performance improvement at retry {retry_cnt}: {pre_optimize_accuracy*100:.4f}% --> {post_reoptimize_accuracy*100:.4f}%")
        return True

def verify_optimized_prompts(prompts, batches, args, epoch_num):
    evaluate_tasks = []
    for batch_idx, batch in enumerate(batches):
        for sample in batch:
            for optimized_prompt in prompts:
                if optimized_prompt["batch_idx"] == batch_idx:
                    correspond_prompt = optimized_prompt["optimized_prompt"]
            evaluate_tasks.append({
                "prompt": correspond_prompt,
                "xi": sample["text"],
                "yi": sample["label"],
                "pred": sample["pred"],
                "sample_idx": sample["sample_idx"],
                "prompt_idx": batch_idx # here prompt_idx is the batch_idx, same thing
            })

    print(f"Total verification queries: {len(prompts)} prompts * {len(batches[0])} batch_size = {len(evaluate_tasks)} (a batch may not be full size)")
    results_map = defaultdict(list)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.thread_size) as executor:
        futures = [executor.submit(_evaluate_prompts, task, args.prompt_dir) for task in evaluate_tasks]
        for future in tqdm(concurrent.futures.as_completed(futures), total=len(futures), desc="Verifying Optimized Prompts"):
            try:
                result = future.result()
                results_map[result["prompt_idx"]].append({
                    "sample_idx": result["sample_idx"],
                    "yi": result["yi"],
                    "pred": result["pred"],
                    "pred_reason": result["pred_reason"]
                })
            except Exception:
                raise ValueError("Error in verifying a prompt:", future.exception())
    print("")

    with open(os.path.join(args.output_dir, f"epoch_{epoch_num}_optimized_prompts_verification_results.json"), "w") as f:
        json.dump(results_map, f, indent=4)

    # check the results by batch
    for batch_idx, batch in enumerate(batches):
        pre_optimize_accuracy = sum(1 for sample in batch if sample["label"] == sample["pred"]) / len(batch)
        post_optimize_accuracy = sum(1 for sample in results_map[batch_idx] if sample["yi"] == sample["pred"]) / len(results_map[batch_idx])
        if post_optimize_accuracy <= pre_optimize_accuracy:
            print(f"Batch {batch_idx} encounter performance drop: {pre_optimize_accuracy*100:.4f}% --> {post_optimize_accuracy*100:.4f}%")
            for optimized_prompt in prompts:
                if optimized_prompt["batch_idx"] == batch_idx:
                    optimized_prompt["verification"] = "fail"
        else:
            print(f"Batch {batch_idx} encounter performance improvement: {pre_optimize_accuracy*100:.4f}% --> {post_optimize_accuracy*100:.4f}%")
            for optimized_prompt in prompts:
                if optimized_prompt["batch_idx"] == batch_idx:
                    optimized_prompt["verification"] = "success"

    for prompt in prompts:
        assert "verification" in prompt, "Each optimized prompt must have a verification status"
    
    return prompts, results_map

def _collect_feedback(task, prompt_dir):
    if task["yi"] == task["pred"]:
        with open(os.path.join(prompt_dir, "feedback_prompt_correct.md"), "r") as f:
            input_template = f.read()
    else:
        with open(os.path.join(prompt_dir, "feedback_prompt_wrong.md"), "r") as f:
            input_template = f.read()

    input_template = input_template.replace("{{prompt}}", task["prompt"])
    input_template = input_template.replace("{{text}}", task["xi"])
    input_template = input_template.replace("{{correct_label}}", task["yi"])
    input_template = input_template.replace("{{predicted_label}}", task["pred"])
    input_template = input_template.replace("{{predicted_reason}}", task["pred_reason"])

    input = input_template
    
    # Keep trying until we get a parseable response
    while True:
        response = ask_llm.chatgpt(input, model="o3")[0]
        parsed = parse_tagged_text(response, "<START>", "<END>")
        
        if parsed and len(parsed) > 0:
            return {
                "batch_idx": task["batch_idx"],
                "sample_idx": task["sample_idx"],
                "yi": task["yi"],
                "pred": task["pred"],
                "pred_reason": task["pred_reason"],
                "feedback": parsed[0]
            }
        else:
            # print(f"Failed to parse response for sample {task['sample_idx']}. Retrying...")
            time.sleep(1)

def collect_feedback(prompt, batches, epoch_num, args):
    feedback_tasks = []
    for batch_idx, batch in enumerate(batches):
        for sample in batch:
            feedback_tasks.append({
                    "prompt": prompt,
                    "xi": sample["text"],
                    "yi": sample["label"],
                    "pred": sample["pred"],
                    "pred_reason": sample["pred_reason"], # llm pred_reason to give such prediction
                    "sample_idx": sample["sample_idx"],
                    "batch_idx": batch_idx
                })
        
    print(f"Total feedback queries: {len(feedback_tasks)}")
    feedbacks_by_batch = defaultdict(list)
    feedbacks_by_sample = defaultdict(list)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.thread_size) as executor:
        futures = [executor.submit(_collect_feedback, task, args.prompt_dir) for task in feedback_tasks]
        for future in tqdm(concurrent.futures.as_completed(futures), total=len(futures), desc="Getting Feedback"):
            result = future.result()
            feedbacks_by_batch[result["batch_idx"]].append({
                "sample_idx": result["sample_idx"],
                "feedback": result["feedback"]
            })
            feedbacks_by_sample[result["sample_idx"]].append(result)
    print("")
        
    # save to output
    with open(os.path.join(args.output_dir, f"epoch_{epoch_num}_feedbacks.json"), "w") as f:
        json.dump(feedbacks_by_sample, f, indent=4)

    return feedbacks_by_batch

def _feedback_integration(task, prompt_dir):
    with open(os.path.join(prompt_dir, "optimize_prompt.md"), "r") as f:
        input_template = f.read()
    
    failed_cases_str = ""
    for sample in task["batch"]:
        for feedback in task["feedbacks"]:
            if feedback["sample_idx"] == sample["sample_idx"]:
                break
        failed_cases_str += f"<Example {sample['sample_idx']}>\n{sample['text']}\nLabel: {sample['label']}\nPrediction: {sample['pred']}\nPredict reason: {sample['pred_reason']}\nFeedback: {feedback['feedback']}\n</Example {sample['sample_idx']}>\n\n"

    input_template = input_template.replace("{{prompt}}", task["prompt"])
    input_template = input_template.replace("{{examples}}", failed_cases_str)

    input = input_template
    while True:
        response = ask_llm.chatgpt(input)[0]
        parsed_response = parse_tagged_text(response, "<START>", "<END>")

        if parsed_response and len(parsed_response) > 0:
            parsed_response = parsed_response[0]
            break
        else:
            print(f"Failed to parse response for batch {task['batch_idx']}. Haveing response:\n{response}\nRetrying...")
            print()
            time.sleep(1)

    return {
        "batch_idx": task["batch_idx"],
        "optimized_prompt": parsed_response
    }

def feedback_integration(prompt, batches, feedbacks_by_batch, epoch_num, args):
    optimize_tasks = []
    for batch_idx, feedbacks in feedbacks_by_batch.items():
        optimize_tasks.append({
            "prompt": prompt,
            "feedbacks": feedbacks,
            "batch_idx": batch_idx,
            "batch": batches[batch_idx]
        })
    
    optimize_prompts = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.thread_size) as executor:
        futures = [executor.submit(_feedback_integration, task, args.prompt_dir) for task in optimize_tasks]
        for future in tqdm(concurrent.futures.as_completed(futures), total=len(futures), desc="Optimizing Prompts"):
            try:
                result = future.result()
                optimize_prompts.append(result)
            except Exception:
                raise ValueError("Error in optimizing prompt for a task:", future.exception())
    print("")

    with open(os.path.join(args.output_dir, f"epoch_{epoch_num}_optimized_prompts.json"), "w") as f:
        json.dump(optimize_prompts, f, indent=4)

    assert optimize_prompts != [], "No prompts were generated during optimization. Check the feedback and optimization steps."
    return optimize_prompts

def new_optimize_prompt(prompt, batches, epoch_num, args):
    # Step 1: obtain feedbacks for each sample in the batch
    feedbacks_by_batch = collect_feedback(prompt, batches, epoch_num, args)
    # feedbacks_by_batch: {<batch_idx>: [feedback for sample 0 in batch of idx batch_idx, feedback for sample 1 in batch of idx batch_idx, ...]}

    # Step 2: aggregate feedbacks to optimize the prompt
    optimized_prompts_by_batch = feedback_integration(prompt, batches, feedbacks_by_batch, epoch_num, args)
    # optimized_prompts_by_batch: [{"batch_idx": <batch_idx>, "optimized_prompt": <optimized_prompt>}, ...]

    # Step 3: evaluate new prompt on the the batch
    verified_prompts_by_batch, verification_results_by_batch = verify_optimized_prompts(optimized_prompts_by_batch, batches, args, epoch_num)
    # optimized_prompts_by_batch: [{"batch_idx": <batch_idx>, "optimized_prompt": <optimized_prompt>, "verification": ["fail", "success"]}, ...]
    # verification_results_by_batch: {<batch_idx>: [{"sample_idx": int, "yi": str, "pred": str, "pred_reason": str}, ...]}

    # sort verified_prompts_by_batch by batch_idx in ascending order
    verified_prompts_by_batch.sort(key=lambda x: x['batch_idx'])
    # Step 4: re-optimize the failed optimized prompts
    for optimized_prompt in verified_prompts_by_batch:
        batch_idx = optimized_prompt['batch_idx']
        # Skip those that have been verified successfully
        if optimized_prompt["verification"] == "success":
            continue

        # If verification failed, we need to re-optimize the prompt
        retry_cnt = 1
        target_batch = batches[optimized_prompt['batch_idx']]
        target_feedbacks = feedbacks_by_batch[optimized_prompt['batch_idx']]
        target_verification_results = verification_results_by_batch[optimized_prompt['batch_idx']]
        while retry_cnt < args.max_optimize_retry:
            print(f"Retrying optimization for batch {optimized_prompt['batch_idx']} (retry {retry_cnt})")

            reoptimized_prompt = reoptimization(prompt, target_batch, target_feedbacks, args)

            pass_verification = verify_optimized_prompt(reoptimized_prompt, target_batch, batch_idx, retry_cnt)

            if pass_verification:
                print(f"Batch {optimized_prompt['batch_idx']} re-optimized successfully after {retry_cnt} retries.")
                optimized_prompt['verification'] = "success"
                optimized_prompt["optimized_prompt"] = reoptimized_prompt
                break
            else:
                retry_cnt += 1

    returnable_optimized_prompts = []
    for optimized_prompt in verified_prompts_by_batch:
        if optimized_prompt["verification"] == "success":
            returnable_optimized_prompts.append(optimized_prompt["optimized_prompt"])
        else:
            print(f"Batch {optimized_prompt['batch_idx']} failed to optimize after {args.max_optimize_retry} retries.")

    if returnable_optimized_prompts:
        return returnable_optimized_prompts
    else:
        raise ValueError("No optimized prompts were generated after retries. Check the feedback and optimization steps.")

def load_dataset(file_path, start_from=0):
    """
    Load dataset from a JSON file.
    
    Args:
        file_path (str): Path to the JSON file containing the dataset.
    
    Returns:
        List[dict]: List of data samples loaded from the file.
    """
    with open(file_path, "r") as f:
        data = json.load(f)

    for idx, sample in enumerate(data):
        if "sample_idx" not in sample:
            sample["sample_idx"] = idx + start_from

    return data

def find_best_prompt_performance(performances):
    # Find the best prompt performance
    best_performance = None
    best_accuracy = 0.0
    for idx, performance in performances.items():
        accuracy = sum([1 for s in performance if s["pred"] == s["yi"]]) / len(performance)
        if accuracy > best_accuracy:
            best_accuracy = accuracy
            best_performance = performance

    return best_performance

def main(args):
    # Load the datasets
    train_data = load_dataset(args.train_file)[:args.train_data_size]
    print(f"Loaded {len(train_data)} training samples")
    test_data = load_dataset(args.test_file)
    print(f"Loaded {len(test_data)} testing samples")

    # Start training
    for i in tqdm(range(args.init_epoch, args.epoch_num), desc="Epochs"):
        # if resume from existing prompt
        if i == args.init_epoch and args.resume_from_prompt is not None and args.resume_from_prompt_performance is not None:
            # Resume from the last prompt and its performance
            with open(args.resume_from_prompt, "r") as f:
                best_prompt = f.read()
            with open(args.resume_from_prompt_performance, "r") as f:
                prompt_performances = json.load(f)
            print(f"Resuming previous prompt and performances")
            
            best_accuracy = 0
            best_prompt_performance = []
            for prompt_idx, performance in prompt_performances.items():
                golds = [p["yi"] for p in performance]
                preds = [p["pred"] for p in performance]
                accuracy = sum(1 for g, p in zip(golds, preds) if g == p) / len(golds)
                if accuracy > best_accuracy:
                    best_accuracy = accuracy
                    best_prompt_performance = performance
            continue
        
        # If start from scratch
        elif i == args.init_epoch:
            batches = batchify_data(train_data, args)
            print(f"Created {len(batches)} batches of size {args.init_batch_size} from training dataset")

            # Obtain initial prompt candidates
            prompts = generate_initial_prompts(batches, args)
            with open(os.path.join(args.output_dir, "initial_prompts.json"), "w") as f:
                json.dump(prompts, f, indent=4)

            # select prompt with best performance
            best_prompt, best_prompt_performance, best_accuracy, results_map = evaluate_prompts(prompts, train_data, args)

            # save best prompt and corresponding performance
            print(f"Best accuracy: {best_accuracy}")
            with open(os.path.join(args.output_dir, f"epoch_{i}_best_prompt.md"), "w") as f:
                f.write(best_prompt)
            with open(os.path.join(args.output_dir, f"epoch_{i}_prompt_candidates_performance.json"), "w") as f:
                json.dump(results_map, f, indent=4)

            continue

        # Else if not epoch 0
        prompt = best_prompt
        batches = batchify_data(train_data, args, best_prompt_performance)
        # Optimize prompt
        prompts = new_optimize_prompt(prompt, batches, i, args)

        best_prompt, best_prompt_performance, best_accuracy, results_map = evaluate_prompts(prompts, train_data, args)
        print(f"Best accuracy: {best_accuracy}")
        with open(os.path.join(args.output_dir, f"epoch_{i}_best_prompt.md"), "w") as f:
            f.write(best_prompt)
        with open(os.path.join(args.output_dir, f"epoch_{i}_prompt_candidates_performance.json"), "w") as f:
            json.dump(results_map, f, indent=4)

    print("Prompt tuning completed.")


if __name__ == "__main__":
    random.seed(42)  # For reproducibility
    args = get_args()

    os.makedirs(args.output_dir, exist_ok=True)
    # get current time
    current_time = time.strftime("%Y-%m-%d-%H-%M-%S")
    args.output_dir = os.path.join(args.output_dir, f"{current_time}")
    
    os.makedirs(args.output_dir, exist_ok=True)

    # save current arguments to output directory
    with open(os.path.join(args.output_dir, "args.json"), "w") as f:
        json.dump(vars(args), f, indent=4)
    main(args) 
