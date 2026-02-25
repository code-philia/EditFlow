import os
import nltk
from pathlib import Path
from rank_bm25 import BM25Okapi
from typing import List, Optional
from nltk.tokenize import word_tokenize

# Download required NLTK data (run once)
nltk.download('punkt')
nltk.download('stopwords')

def select_files(folder_path: str, prior_edits: List[dict], k: int = 5, 
                    file_extensions: Optional[List[str]] = None) -> dict:
    """
    Use BM25 algorithm to find top k most similar files to a query string
    
    Args:
        folder_path: Path to the folder to search
        query_str: Query string to search for
        k: Number of top results to return
        file_extensions: List of file extensions to include (e.g., ['.txt', '.py', '.md'])
                        If None, all text files will be included
    
    Returns:
        Dict where key is relative path to folder_path, value is file content as List[str] (lines)
    """
    
    # Default file extensions for text files
    if file_extensions is None:
        file_extensions = ['.txt', '.py', '.js', '.java', '.cpp', '.c', '.h', 
                          '.md', '.rst', '.html', '.css', '.json', '.xml', '.yml', '.yaml']
    
    # Convert folder_path to absolute path for consistent relative path calculation
    folder_path = os.path.abspath(folder_path)
    
    # Collect all eligible files
    files_content = {}
    files_lines = {}
    
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            file_path = os.path.join(root, file)
            file_ext = Path(file_path).suffix.lower()
            
            if file_ext in file_extensions:
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        lines = f.readlines()
                        content = "".join(lines)
                        
                        # Calculate relative path
                        relative_path = os.path.relpath(file_path, folder_path)
                        
                        files_content[relative_path] = content
                        files_lines[relative_path] = lines
                except Exception as e:
                    continue
    
    if not files_content:
        return {}
    
    # Calculate BM25 scores using library
    file_paths = list(files_content.keys())
    tokenized_docs = [word_tokenize(content) for content in files_content.values()]
    
    # Create BM25 model
    bm25 = BM25Okapi(tokenized_docs)
    
    # Get query tokens and calculate scores
    query = "".join(prior_edits[-1]["before"]) + "".join(prior_edits[-1]["after"])
    query_tokens = word_tokenize(query)
    scores = bm25.get_scores(query_tokens)
    
    # Create scores dictionary
    bm25_scores = dict(zip(file_paths, scores))
    
    # Sort by score and get top k relative paths
    sorted_results = sorted(bm25_scores.items(), key=lambda x: x[1], reverse=True)
    top_k_paths = [rel_path for rel_path, score in sorted_results[:k]]
    
    # Return dict with relative paths as keys and file lines as values
    result_dict = {rel_path: files_lines[rel_path] for rel_path in top_k_paths}
    return result_dict
