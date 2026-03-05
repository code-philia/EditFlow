#!/usr/bin/env bash
set -e

echo "Initializing submodule configuration..."
git submodule init

echo "Updating submodules..."
git submodule update

echo "Updating all nested submodules recursively..."
git submodule update --init --recursive

echo "✅ All submodules have been initialized and updated."

TARGET_TAG="v0.21.0"

# 两个 tree-sitter 目录
BASE_DIRS=(
  "src/libs/tree-sitter"
  "prompt_tuning/lib/tree-sitter"
)

# 定义所有子模块路径
MODULES=(
  "tree-sitter-go"
  "tree-sitter-javascript"
  "tree-sitter-python"
  "tree-sitter-typescript"
  "tree-sitter-java"
)

echo "🌲 Switching all Tree-sitter grammars to tag: ${TARGET_TAG}"

for base_dir in "${BASE_DIRS[@]}"; do
  echo "📁 Processing base directory: ${base_dir}"
  for module in "${MODULES[@]}"; do
    MODULE_PATH="${base_dir}/${module}"
    if [ -d "$MODULE_PATH" ]; then
      echo "➡️  Processing $MODULE_PATH ..."
      (
        cd "$MODULE_PATH"
        git fetch --tags --quiet
        if git rev-parse "$TARGET_TAG" >/dev/null 2>&1; then
          git checkout "$TARGET_TAG" --quiet
          echo "✅ Checked out $MODULE_PATH to $TARGET_TAG"
        else
          echo "⚠️  Tag $TARGET_TAG not found in $MODULE_PATH, skipping."
        fi
      )
    else
      echo "❌ Directory $MODULE_PATH not found, skipping."
    fi
  done
done

echo "✨ Done. All submodules processed."