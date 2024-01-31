import os
import nltk
import re

from typing import Dict, Generator, List

from pydriller.domain.commit import Commit, ModificationType
from pydriller.repository import Git, Repository

from repominer import utils
from repominer.files import FixedFile, FailureProneFile
from repominer.mining import rules

# Important: downloading resources for NLTK
try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt')

try:
    nltk.data.find('corpora/stopwords')
except LookupError:
    nltk.download('stopwords')

# Constants
full_name_pattern = re.compile(r'(github|gitlab){1}\.com/([\w\W]+)$')


class BaseMiner:
    """
    This is the base class to mine a software repository for:

    * defect-fixing commits
    * files fixed by defect-fixing commits (i.e., fixed-files)
    * failure-prone files

    """

    def __init__(self,
                 url_to_repo: str,
                 clone_repo_to: str,
                 branch: str = None):
        """
        The class constructor.
        Initialize a new BaseMiner.

        Parameters
        ----------
        url_to_repo : str
            the url to a remote Github or Gitlab repository

        branch : str
            the branch to analyze. If None, the repos' default branch is used.

        clone_repo_to : str
            Path to clone the repository to. If None, PyDriller's autogenerated tmp folder is used


        Attributes
        ----------
        repository : str
            Repository full name (e.g., radon-h2020/radon-repository-miner).
            The value is automatically extracted from parameter ``url_to_repo``.

        branch : str
            Repository's branch to analyze.

        commit_hashes : List[str]
            List of commit hash on the repository's branch, ordered by creation date.

        fixing_commits : List[str]
            List of bug-fixing commit hashes.

            Bug-fixings commits are identified by the methods ``get_fixing_commits_from_closed_issues`` and
            ``get_fixing_commits_from_commit_messages``.

            Although, if you are certain that some commits fix bugs, e.g., because of a previous manual analysis,
            you can specify them in advance to speed up the mining as follows:

            Example
            -------
            .. highlight:: python
            .. code-block:: python

                from repominer.mining.base import BaseMiner

                miner = BaseMiner('https://github.com/radon-h2020/radon-repository-miner')
                miner.fixing_commits = ['f350e05696db1c5f78320483e0e44e7aea410449']

            This is useful when you have to run the miner again on future commits, and you already have results from the
            past runs.

        fixed_files : List[FixedFile]
            List of FixedFiles objects.
            Fixed files are files modified in bug-fixing commits.

            They are identified by the method ``get_fixed_files``.
            Unlike ``fixing_commits``, it cannot be used to inlude fixed file, as it resets at every ``get_fixed_files``
            call.
            This is due to the algorithm used to identify them.

        """

        full_name_match = full_name_pattern.search(url_to_repo.replace('.git', ''))

        if not full_name_match:
            raise ValueError(
                'Insert a valid Git URL. For example: https://github.com/radon-h2020/radon-repository-miner.git')

        if not os.path.isdir(clone_repo_to):
            raise FileNotFoundError(f'{clone_repo_to} does not exist.')

        self.path_to_repo = os.path.join(clone_repo_to, full_name_match.groups()[1].split('/')[1])
        self.branch = branch

        self.fixing_commits = list()
        self.fixed_files = list()

        # Get all the repository commits sorted by commit date
        self.commit_hashes = [c.hash for c in
                              Repository(
                                  path_to_repo=self.path_to_repo if os.path.isdir(self.path_to_repo) else url_to_repo,
                                  clone_repo_to=clone_repo_to,
                                  only_in_branch=self.branch,
                                  order='date-order',
                                  num_workers=1).traverse_commits()]

        self.FixingCommitClassifier = FixingCommitClassifier

    def discard_undesired_fixing_commits(self, commits: List[str]) -> None:
        """
        Discard undesired commits.

        Given a list of commit hash, this method discard those that are deemed undesired.
        Undesired commits depends on the problem being formulated. For example, if the user is mining fixing-commits for
        Ansible, an undesired commit might be one modifying not-Ansible files.

        Note, the update occurs in-place. That is, the original list is updated.

        Parameters
        ----------
        commits : List[str]
            List of commit hash

        """

        if not commits:
            return

        self.sort_commits(commits)

        for commit in Repository(self.path_to_repo,
                                 from_commit=commits[0],  # first commit in commits
                                 to_commit=commits[-1],  # last commit in commits
                                 only_in_branch=self.branch).traverse_commits():
            i = 0

            # if none of the modified files is a Ansible file then discard the commit
            while i < len(commit.modified_files):
                if commit.modified_files[i].change_type != ModificationType.MODIFY:
                    i += 1
                elif self.ignore_file(commit.modified_files[i].new_path, commit.modified_files[i].source_code):
                    i += 1
                else:
                    break

            if i == len(commit.modified_files) and commit.hash in commits:
                commits.remove(commit.hash)

    def get_fixing_commits(self, num_workers=8) -> Dict[str, List[str]]:
        """
        Return a list of bug-fixing commit hash, categorized as fixing "conditionals", "configuration data",
        "dependencies", "documentation", "idempotency", "security", "service", "syntax".

        This method returns the commits whose message indicates defective scripts.
        `Note:` Beside returning the list of bug-fixing commits, it also updates the attribute ``fixing_commits``.

        Parameters
        ----------
        num_workers : int
            Number of threads. Default 8.

        Returns
        -------
        List[str]
            A dictionary of bug-fixing commits hashes and boolean values for every fixing labels.
            {'hash1': ['SERVICE', 'SYNTAX', ...]}
        """

        commits_labels = {}
        commits = []

        for commit in Repository(self.path_to_repo, only_in_branch=self.branch, num_workers=num_workers).traverse_commits():

            if commit.hash in self.fixing_commits:
                continue

            fcc = self.FixingCommitClassifier(commit)

            if fcc.fixes_conditional():
                commits_labels.setdefault(commit.hash, []).append('CONDITIONAL')
            if fcc.fixes_configuration_data():
                commits_labels.setdefault(commit.hash, []).append('CONFIGURATION_DATA')
            if fcc.fixes_dependency():
                commits_labels.setdefault(commit.hash, []).append('DEPENDENCY')
            if fcc.fixes_documentation():
                commits_labels.setdefault(commit.hash, []).append('DOCUMENTATION')
            if fcc.fixes_idempotency():
                commits_labels.setdefault(commit.hash, []).append('IDEMPOTENCY')
            if fcc.fixes_security():
                commits_labels.setdefault(commit.hash, []).append('SECURITY')
            if fcc.fixes_service():
                commits_labels.setdefault(commit.hash, []).append('SERVICE')
            if fcc.fixes_syntax():
                commits_labels.setdefault(commit.hash, []).append('SYNTAX')

            if commit.hash in commits_labels:
                commits.append(commit.hash)

        if commits:
            # Discard commits that do not touch IaC files
            self.discard_undesired_fixing_commits(commits)

            # Update the list of fixing commits
            self.fixing_commits.extend(commits)

            # Sort fixing_commits in ascending order of date
            self.sort_commits(self.fixing_commits)

            for sha in list(commits_labels.keys()):
                if sha not in commits:  # It means it was an undesired commit
                    del commits_labels[sha]

        return commits_labels

    def get_fixed_files(self) -> None:
        """
        Populate the list of FixedFile objects.

        A FixedFile is a file modified in a bug-fixing commit that consists of a filename, hash of the commit that fixed
        it, and hash of the commit that introduced the bug.

        It uses the SZZ algorithm implemented in PyDriller to identify the oldest commit that introduced the bug,
        referred to as bug-introducing commit.

        `Note:` before calling this method, it is necessary that you run at least one between
        `get_fixing_commits_from_closed_issues` and `get_fixing_commits_from_commit_messages`.


        Returns
        -------
        None

        """

        if not self.fixing_commits:
            return

        self.sort_commits(self.fixing_commits)

        self.fixed_files = list()
        renamed_files = dict()
        git_repo = Git(self.path_to_repo)

        if len(self.fixing_commits) == 1:
            repository_mining = Repository(self.path_to_repo, single=self.fixing_commits[0], only_in_branch=self.branch,
                                           num_workers=1)
        else:
            repository_mining = Repository(self.path_to_repo,
                                           from_commit=self.fixing_commits[-1],  # Last fixing-commit by date
                                           to_commit=self.fixing_commits[0],  # First fixing-commit by date
                                           order='reverse',
                                           only_in_branch=self.branch,
                                           num_workers=1)

        # Traverse commits from the latest to the first fixing-commit
        for commit in repository_mining.traverse_commits():

            for modified_file in commit.modified_files:

                # Not interested in ADDED and DELETED files
                if modified_file.change_type not in (ModificationType.MODIFY, ModificationType.RENAME):
                    continue

                # If RENAMED then handle renaming
                if modified_file.change_type == ModificationType.RENAME:
                    # if modified_file.new_path in renamed_files:
                    #     renamed_files[modified_file.old_path] = renamed_files[modified_file.new_path]
                    # else:
                    renamed_files[modified_file.old_path] = renamed_files.get(modified_file.new_path,
                                                                              modified_file.new_path)
                    # elif commit.hash in self.fixing_commits:
                    #     renamed_files[modified_file.old_path] = modified_file.new_path

                # This is to ensure that renamed files are tracked. Then, if the commit is not a fixing-commit then
                # go to the next (previous commit in chronological order)
                if commit.hash not in self.fixing_commits:
                    continue

                # Not interested in type of files
                if self.ignore_file(modified_file.new_path, modified_file.source_code):
                    continue

                # Identify bug-inducing commits. Dict[modified_file, Set[commit_hashes]]
                bug_inducing_commits = git_repo.get_commits_last_modified_lines(commit, modified_file)

                if not bug_inducing_commits.get(modified_file.new_path):
                    continue
                else:
                    bug_inducing_commits = list(bug_inducing_commits[modified_file.new_path])
                    self.sort_commits(bug_inducing_commits)
                    bic = bug_inducing_commits[0]  # bic is the oldest bug-inducing-commit

                current_fix = FixedFile(filepath=renamed_files.get(modified_file.new_path, modified_file.new_path),
                                        bic=bic,
                                        fic=commit.hash)

                if current_fix not in self.fixed_files:
                    self.fixed_files.append(current_fix)
                else:
                    idx = self.fixed_files.index(current_fix)
                    existing_fix = self.fixed_files[idx]

                    # If the current FIC is older than the existing bic, then save it as a new FixedFile.
                    # Else it means the current fix is between the existing fix bic and fic.
                    # If the current BIC is older than the existing bic, then update the bic.
                    if self.commit_hashes.index(current_fix.fic) < self.commit_hashes.index(existing_fix.bic):

                        if modified_file.new_path in renamed_files:
                            del renamed_files[modified_file.new_path]

                        current_fix.filepath = modified_file.new_path
                        self.fixed_files.append(current_fix)
                    elif self.commit_hashes.index(current_fix.bic) < self.commit_hashes.index(existing_fix.bic):
                        existing_fix.bic = current_fix.bic

    def ignore_file(self, path_to_file: str, content: str = None) -> bool:
        """
        Ignore a file.

        When looking for fixed files in ``get_fixed_files``, you might want to consider only files with some characteristics,
        and ignore all the others.
        For example, when instantiating an ``ToscaMiner``, this method ignore all the non-Ansible files, based on their
        filepath and content. That is, only files terminating with .yml, .yaml, or .tosca, or which content contains the
        keyword ``tosca_definitions_version`` are kept.

        Parameters
        ----------
        path_to_file: str
            The filepath (e.g., repominer/mining/base.py).

        content: str
            The file content.

        Returns
        -------
        bool
            True if the file must be ignore. False, otherwise.

        """
        return False

    def label(self) -> Generator[FailureProneFile, None, None]:
        """
        For each FixedFile object, yield a FailureProneFile object for each commit between the FixedFile's
        bug-introducing-commit and its fixing-commit.

        `Note:` make sure to run the method ``get_fixed_files`` before.

        Yields
        ------
        FailureProneFile
            A FailureProneFile object.

        """

        if not (self.fixing_commits and self.fixed_files):
            return

        labeling = dict()
        for file in self.fixed_files:
            labeling.setdefault(file.filepath, list()).append(file)

        self.sort_commits(self.fixing_commits)

        renamed_files = {}

        for commit in Repository(self.path_to_repo, from_commit=self.fixing_commits[-1],
                                 to_commit=self.commit_hashes[0],
                                 order='reverse', num_workers=1).traverse_commits():

            for file in self.fixed_files:

                idx_fic = self.commit_hashes.index(file.fic)
                idx_bic = self.commit_hashes.index(file.bic)
                idx_commit = self.commit_hashes.index(commit.hash)

                if idx_fic > idx_commit >= idx_bic:
                    yield FailureProneFile(filepath=renamed_files.get(file.filepath, file.filepath),
                                           commit=commit.hash,
                                           fixing_commit=file.fic)

            # Handle file renaming
            for modified_file in commit.modified_files:
                if modified_file.change_type == ModificationType.RENAME:
                    renamed_files[modified_file.new_path] = modified_file.old_path

    def sort_commits(self, commits: List[str]) -> None:
        """
        Sort a list of commits in chronological order.

        Parameters
        ----------
        commits : List[str]
            List of commits hash to sort.

        """
        sorted_commits = [sha for sha in self.commit_hashes if sha in commits]
        commits.clear()
        commits.extend(sorted_commits)


class FixingCommitClassifier:
    """
    This class implements rules to detect fixing commits categories related to IaC defects, as defined in
    http://chrisparnin.me/pdf/GangOfEight.pdf.
    """

    def __init__(self, commit: Commit):
        """
        The class constructor.

        Parameters
        ----------
        commit: Commit
            The commit to analyze.

        Raises
        ------
        TypeError
            If commit is None

        """

        if commit is None:
            raise TypeError('Expected a pydriller.domain.commit.Commit object.')

        self.commit = commit
        self.sentences = []  # will be list of tokens list

        for sentence in nltk.sent_tokenize(commit.msg):
            # split into words
            tokens = nltk.tokenize.word_tokenize(sentence)

            # remove all tokens that are not alphabetic
            tokens = [word.strip() for word in tokens if word.isalpha()]

            self.sentences.append(tokens)

    def is_comment_changed(self) -> bool:
        """
        Return True if the commit fixes a comment.

        Returns
        -------
        bool
            True if the commit modifies a comment

        """
        for modified_file in self.commit.modified_files:
            if modified_file.change_type != ModificationType.MODIFY:
                continue

            diff = [line.strip() for _, line in modified_file.diff_parsed.get('added', {})]
            diff.extend([line.strip() for _, line in modified_file.diff_parsed.get('deleted', {})])
            if any(line.startswith('#') for line in diff):
                return True

        return False

    def is_data_changed(self) -> bool:
        return False

    def is_include_changed(self) -> bool:
        return False

    def is_service_changed(self) -> bool:
        return False

    def fixes_conditional(self):
        """
        Return True if the commit fixes a conditional.

        Returns
        -------
        bool
            True if the commit fixes a conditional. False, otherwise.

        """
        for sentence in self.sentences:
            sentence = ' '.join(sentence)
            sentence_dep = ' '.join(utils.get_head_dependents(sentence))
            if rules.has_defect_pattern(sentence) and rules.has_conditional_pattern(sentence_dep):
                return True

        return False

    def fixes_configuration_data(self):
        """
        Return True if the commit fixes configuration data.

        Returns
        -------
        bool
            True if the commit fixes configuration data. False, otherwise.

        """

        for sentence in self.sentences:
            sentence = ' '.join(sentence)
            sentence_dep = ' '.join(utils.get_head_dependents(sentence))

            if rules.has_defect_pattern(sentence) \
                    and (rules.has_storage_configuration_pattern(sentence_dep)
                         or rules.has_file_configuration_pattern(sentence_dep)
                         or rules.has_network_configuration_pattern(sentence_dep)
                         or rules.has_user_configuration_pattern(sentence_dep)
                         or rules.has_cache_configuration_pattern(sentence_dep)
                         or self.is_data_changed()):
                return True

        return False

    def fixes_dependency(self):
        """
        Return True if the commit fixes a dependency.
        For example, if an import or include is changed.

        Returns
        -------
        bool
            True if the commit fixes a dependency. False, otherwise.

        """

        for sentence in self.sentences:
            sentence = ' '.join(sentence)
            sentence_dep = ' '.join(utils.get_head_dependents(sentence))
            if rules.has_defect_pattern(sentence) and (
                    rules.has_dependency_pattern(sentence_dep) or self.is_include_changed()):
                return True

        return False

    def fixes_documentation(self):
        """
        Return True if the commit fixes the documentation.

        Returns
        -------
        bool
            True if the commit fixes the documentation. False, otherwise.

        """

        for sentence in self.sentences:
            sentence = ' '.join(sentence)
            sentence_dep = ' '.join(utils.get_head_dependents(sentence))
            if rules.has_defect_pattern(sentence) and (
                    rules.has_documentation_pattern(sentence_dep) or self.is_comment_changed()):
                return True

        return False

    def fixes_idempotency(self):
        """
        Return True if the commit fixes an idempotency issue.

        Returns
        -------
        bool
            True if the commit fixes an idempotency. False, otherwise.

        """

        for sentence in self.sentences:
            sentence = ' '.join(sentence)
            sentence_dep = ' '.join(utils.get_head_dependents(sentence))
            if rules.has_defect_pattern(sentence) and rules.has_idempotency_pattern(sentence_dep):
                return True

        return False

    def fixes_security(self):
        """
        Return True if the commit fixes a security issue.

        Returns
        -------
        bool
            True if the commit fixes security. False, otherwise.

        """

        for sentence in self.sentences:
            sentence = ' '.join(sentence)
            sentence_dep = ' '.join(utils.get_head_dependents(sentence))
            if rules.has_defect_pattern(sentence) and rules.has_security_pattern(sentence_dep):
                return True

        return False

    def fixes_service(self):
        """
        Return True if the commit fixes a service issue.

        Returns
        -------
        bool
            True if the commit fixes a service. False, otherwise.

        """

        for sentence in self.sentences:
            sentence = ' '.join(sentence)
            sentence_dep = ' '.join(utils.get_head_dependents(sentence))
            if rules.has_defect_pattern(sentence) and (
                    rules.has_service_pattern(sentence_dep) or self.is_service_changed()):
                return True

        return False

    def fixes_syntax(self):
        """
        Return True if the commit fixes a syntax issue.

        Returns
        -------
        bool
            True if the commit fixes syntnax. False, otherwise.

        """

        for sentence in self.sentences:
            sentence = ' '.join(sentence)
            sentence_dep = ' '.join(utils.get_head_dependents(sentence))
            if rules.has_defect_pattern(sentence) and rules.has_syntax_pattern(sentence_dep):
                return True

        return False
