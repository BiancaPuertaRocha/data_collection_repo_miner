from python_utils.python_miner import PythonMiner
#from repominer.metrics.base import BaseMetricsExtractor

miner = PythonMiner('https://github.com/binux/pyspider', clone_repo_to='tmp', branch='master')
miner.get_fixing_commits()
miner.get_fixed_files()
failure_prone_files = miner.label()

#metrics_extractor = BaseMetricsExtractor('tmp/pyspider')
#metrics_extractor.extract(failure_prone_files)
#metrics_extractor.to_csv('metrics.csv')

# print('FIXING COMMITS:', miner.fixing_commits)
print('FP Files:', failure_prone_files)
#print('METRICS:', metrics_extractor.dataset.head())