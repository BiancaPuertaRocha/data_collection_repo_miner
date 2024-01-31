from typing import List
from repominer.mining.base import BaseMiner, FixingCommitClassifier
from repominer import filters

from pydriller.repository import Repository, Commit
from pydriller.domain.commit import Commit, ModificationType
class PythonMiner(BaseMiner):
    def __init__(self, url_to_repo, clone_repo_to, branch = None):
        self.branch = branch
        super().__init__(url_to_repo, clone_repo_to, branch)
        self.FixingCommitClassifier = PythonFixingCommitClassifier
    
    def discard_undesired_fixing_commits(self, commits: List[str]) -> None:
        self.sort_commits(commits)
        print(self.path_to_repo)
        print(commits[0])
        print(commits[-1])
        for commit in Repository(self.path_to_repo, from_commit=commits[0], to_commit=commits[-1]).traverse_commits():
            i = 0
            while i < len(commit.modified_files) and commit.modified_files[i].change_type == ModificationType.MODIFY and commit.modified_files[i].new_path.endswith('.py'):
                i += 1
            if i >= len(commit.modified_files):
                try:
                    commits.remove(commit.hash)
                except:
                    pass
        #pass

    def ignore_file(self, path_to_file: str, content: str = None):
        return not path_to_file.endswith('.py')
    
class PythonFixingCommitClassifier(FixingCommitClassifier):
    def __init__(self, commit: Commit):
        super().__init__(commit)