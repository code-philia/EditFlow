# README

## How to use
0. install dependency 
    ```
    pip install gevent
    ```
1. 登陆 [Github token 设置](https://github.com/settings/tokens)，创建个人 token 

2. 修改 main.py 参数：

* lang: 目标语言
* num_of_repo: 爬取库的数量
* download_files_when_generate_datasamples: 生成数据样本的同时下载对应代码文件
* only_download_changed_files: 只下载对应文件而非整个 repo

3. 将个人 token 复制到 get_changes.py 第 12 行：
    ```
    GITHUB_TOKEN = ‘’ 
    ```
4. 运行程序

    ```
        python main.py
    ```

## 实现细节

1. get_changes(lang, num_of_repo):  从目标语言下 star 数最多的库开始爬取，获得每个库的 commit sha，再获得每个 commit 下每条修改。修改会被记录在 ./changes/{lang} 下的jsonl文件中，文件名为：{user_name}\_{proj_name}\_{sha}\_{parent_sha}.jsonl，每条数据结构如下：

```python
{
    "func_name": the name of function that this change belongs to,
    "del_line_idx": the index of lines of code that deleted in the old version,
    "add_line_idx": the index of lines of code that are newly added in the new version,
    "del_line": the lines of code that deleted,
    "add_line": the lines of code that added,
    "file_path": the file path of this change belongs to
}
```

1. get_datasample(lang): 读取修改文件，根据sha下载对应历史版本代码库，并形成数据样本，结构如下：

```python
{
    'old_file_path': f'./repos/{user_name}_{proj_name}_{parent_sha}/{file_path_within_proj}',
    'new_file_path': f'./repos/{user_name}_{proj_name}_{sha}/{file_path_within_proj}',
    'changes': [
        {
            "func_name": the name of function that this change belongs to,
            "del_line_idx": the index of lines of code that deleted in the old version,
            "add_line_idx": the index of lines of code that are newly added in the new version,
            "del_line": the lines of code that deleted,
            "add_line": the lines of code that added
        }
        ...
    ]
    'commit_msg': commit message,
    'pull_msg': pull message,
    'html_url': html url from commit information
}
```

3. 数据保存在 ./dataset 中
4. 当超出 GitHub 允许的一小时请求次数时，r.status_code == 403，此时程序 sleep 一小时 