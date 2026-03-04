"""
https://oai.azure.com/portal/be5567c3dd4d49eb93f58914cccf3f02/deployment
clausa gpt4
"""
import os
import time
import requests
import string
from dotenv import load_dotenv

curr_file_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(curr_file_dir, "../.config"))
OPENAI_KEY = os.getenv("OPENAI_TOKEN")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
DEEPSEEK_TOKEN = os.getenv("DEEPSEEK_TOKEN")
MAX_RETRIES = int(os.getenv("MAX_RETRIES"))

def parse_sectioned_prompt(s):
    """
    Parses a string containing sections marked by headers into a dictionary.

    Each section is expected to start with a line like '# Header Name'.
    The header name will be the first word of the line, lowercased, and with punctuation removed.
    The content of the section will be all subsequent lines until the next header or end of string.

    Args:
        s: The input string to parse.

    Returns:
        A dictionary where keys are header names and values are the content of the sections.
    """
    result = {}
    current_header = None

    for line in s.split('\n'):
        line = line.strip()

        if line.startswith('# '):
            # first word without punctuation
            current_header = line[2:].strip().lower().split()[0]
            current_header = current_header.translate(str.maketrans('', '', string.punctuation))
            result[current_header] = ''
        elif current_header is not None:
            result[current_header] += line + '\n'

    return result

def chatgpt(prompt, model="gpt-4.1", temperature=0.7, n=1, top_p=1, stop=None, max_tokens=4096, 
                  presence_penalty=0, frequency_penalty=0, logit_bias={}, timeout=90):
    """
    Query chatgpt for response
    """
    messages = [{"role": "user", "content": prompt}]
    payload = {
        "messages": messages,
        "model": model,
        "temperature": temperature,
        "n": n, # the number of different completions
        "top_p": top_p,
        "stop": stop,
        "max_tokens": max_tokens,
        "presence_penalty": presence_penalty,
        "frequency_penalty": frequency_penalty,
        "logit_bias": logit_bias
    }
    retries = 0
    while True:
        try:
            r = requests.post(f'{OPENAI_BASE_URL}/chat/completions',
                headers = {
                    "Authorization": f"Bearer {OPENAI_KEY}",
                    "Content-Type": "application/json"
                },
                json = payload,
                timeout=timeout
            )
            if r.status_code != 200:
                print(f"Status code: {r.status_code}, retry")
                retries += 1
                time.sleep(1)
            else:
                break
        except requests.exceptions.ReadTimeout:
            print("ReadTimeout, retry")
            time.sleep(1)
            retries += 1
        except requests.exceptions.ConnectionError:
            print("ConnectionError, retry")
            time.sleep(1)
            retries += 1
    r = r.json()
    # NOTE: this return type should not be changed, as this func is used for multiple purposes.
    return [choice['message']['content'] for choice in r['choices']]

def deepseek(prompt, model="deepseek-chat", temperature=0.7, n=1, top_p=1, stop=None, max_tokens=4096,
             presence_penalty=0, frequency_penalty=0, timeout=60):
    """
    Query DeepSeek for response
    """
    messages = [{"role": "user", "content": prompt}]
    payload = {
        "messages": messages,
        "model": model,
        "temperature": temperature,
        "n": n,  # the number of different completions
        "top_p": top_p,
        "stop": stop,
        "max_tokens": max_tokens,
        "presence_penalty": presence_penalty,
        "frequency_penalty": frequency_penalty
    }
    retries = 0
    while True:
        try:
            r = requests.post(f'https://api.deepseek.com/chat/completions',
                              headers={
                                  "Authorization": f"Bearer {DEEPSEEK_TOKEN}",
                                  "Content-Type": "application/json"
                              },
                              json=payload,
                              timeout=timeout
                              )
            if r.status_code != 200:
                print(f"Status code: {r.status_code}, retry")
                retries += 1
                time.sleep(1)
            else:
                break
        except requests.exceptions.ReadTimeout:
            print("ReadTimeout, retry")
            time.sleep(1)
            retries += 1
        except requests.exceptions.ConnectionError:
            print("ConnectionError, retry")
            time.sleep(1)
            retries += 1
    r = r.json()
    # NOTE: this return type should not be changed, as this func is used for multiple purposes.
    return [choice['message']['content'] for choice in r['choices']]

if __name__ == "__main__":
    prompt = "hello, who are you?"
    print(prompt)

    responses = deepseek(prompt)
    print(responses)

    responses = chatgpt(prompt)
    print(responses)