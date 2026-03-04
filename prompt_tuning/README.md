# Prompt Tuning

This module implements the prompt auto-tuning pipeline described in the EditFlow paper. It trains an LLM-based classifier to predict the natural ordering of code edits in a developer's workflow — determining whether one edit should precede another, both orders are valid, or the edits are unrelated.

## Pipeline Overview

The pipeline consists of 5 sequential scripts:

| Script | Description |
|---|---|
| `a0_collect_sample.py` | Collect and label commits from GitHub |
| `a1_construct_tuning_dataset.py` | Build train/test datasets from labeled data |
| `a2_main.py` | Run iterative prompt tuning (main script) |
| `a3_eval.py` | Evaluate baseline and tuned prompts |
| `a4_print_all_results.py` | Summarize results across multiple runs |

## Setup

Create a `.config` file in this directory:

```
OPENAI_TOKEN=<your Azure OpenAI API key>
OPENAI_BASE_URL=<your Azure endpoint URL>
DEEPSEEK_TOKEN=<your DeepSeek API key (optional)>
MAX_RETRIES=3
REPOS_PATH=<local path to store cloned repositories>
```

Install dependencies:

```bash
pip install -r ../requirements.txt
```

## Usage

### Step 1: Collect and label commits

`a0_collect_sample.py` is a template for manually collecting commits. For each commit, it clones the repository, extracts edit hunks, and analyzes static relationships (dependencies, copy-paste patterns). You then manually annotate the partial order labels.

Labeled commits are stored as JSON files in `database/`:

```
database/{project_name}-{commit_sha}.json
```

### Step 2: Build the dataset

```bash
python a1_construct_tuning_dataset.py
```

Reads all files in `database/`, constructs edit pairs, and splits into train (70%) / test (30%):

```
dataset/train.json
dataset/test.json
```

### Step 3: Run prompt tuning

```bash
python a2_main.py
```

Key arguments:

| Argument | Default | Description |
|---|---|---|
| `--train_file` | `dataset/train.json` | Training data path |
| `--test_file` | `dataset/test.json` | Test data path |
| `--epoch_num` | `2` | Number of tuning epochs |
| `--train_data_size` | `2030` | Number of training samples |
| `--init_batch_size` | `128` | Batch size for epoch 0 |
| `--batch_size` | `32` | Batch size for optimization epochs |
| `--thread_size` | `8` | Parallel threads for LLM calls |
| `--resume_from_prompt` | — | Path to an existing prompt to resume from |

Outputs are saved to `output/{timestamp}/`:

- `epoch_N_best_prompt.md` — best prompt after each epoch
- `epoch_N_feedbacks.json` — LLM feedback on incorrect predictions
- `epoch_N_optimized_prompts.json` — optimized prompt candidates
- `args.json` — full argument record

**How it works:**

- **Epoch 0**: Generates multiple candidate prompts (one per batch of examples), evaluates each on the full training set, and keeps the best.
- **Epoch N**: Identifies incorrectly predicted samples, collects targeted LLM feedback, optimizes the current best prompt, and verifies the improvement before accepting.

### Step 4: Evaluate baselines

```bash
python a3_eval.py
```

Evaluates all prompts in `baseline_prompts/` on the test set and reports accuracy, precision, recall, and F1-score. Included baselines:

- `zeroshot.md` — zero-shot prompt
- `fewshot.md` — few-shot prompt
- `handcraft.md` — manually designed prompt
- `ours.md` — our tuned prompt

### Step 5: Summarize multiple runs

```bash
python a4_print_all_results.py
```

Aggregates and prints metrics from all result files in `experiment_result/`.

## Edit Ordering Labels

Each edit pair in the dataset is labeled as one of:

| Label | Meaning |
|---|---|
| `0 before 1` | Edit 0 must logically precede Edit 1 |
| `1 before 0` | Edit 1 must logically precede Edit 0 |
| `bi-directional` | Either order is natural |
| `no relation` | Edits are unrelated |

## Directory Structure

```
prompt_tuning/
├── a0_collect_sample.py          # Commit data collection template
├── a1_construct_tuning_dataset.py # Dataset builder
├── a2_main.py                    # Prompt tuning engine
├── a3_eval.py                    # Baseline evaluator
├── a4_print_all_results.py       # Result aggregator
├── baseline_prompts/             # Reference prompts for comparison
├── tuning_prompts/               # Meta-prompts used by the tuner
├── common_utils/                 # Shared utilities
│   ├── ask_llm.py                # LLM API interface (GPT-4.1, DeepSeek)
│   ├── construct_input.py        # Edit pair formatter
│   ├── utils.py                  # Commit parsing, AST analysis, heuristics
│   ├── dependency.py             # Static dependency analysis
│   └── heuristic_relation.py     # Copy/cut-paste detection
├── database/                     # Manually labeled commit data
├── dataset/                      # Generated train/test splits
├── experiment_result/            # Evaluation outputs
└── lib/                          # Tree-sitter parsers and other libraries
```
