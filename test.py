from python_utils.python_miner import PythonMiner
from python_utils.python_metrics import PythonMetricsExtractor
#from repominer.metrics.base import BaseMetricsExtractor

miner = PythonMiner('https://github.com/pytest-dev/pytest.git', clone_repo_to='./tmp', branch='main')
miner.get_fixing_commits()
miner.get_fixed_files()
failure_prone_files = miner.label()

metrics_extractor = PythonMetricsExtractor('./tmp/pytest')
metrics_extractor.extract(failure_prone_files)
metrics_extractor.to_csv('metrics_pytest.csv')

print('FIXING COMMITS:', miner.fixing_commits)
print('FP Files:', failure_prone_files)
print('METRICS:', metrics_extractor.dataset.head())