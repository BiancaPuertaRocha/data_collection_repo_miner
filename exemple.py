from repominer.mining.ansible import AnsibleMiner
from repominer.metrics.ansible import AnsibleMetricsExtractor
    
miner = AnsibleMiner(url_to_repo='https://github.com/adriagalin/ansible.motd', clone_repo_to='tmp') 
miner.get_fixing_commits()
miner.get_fixed_files()
failure_prone_files = miner.label()

metrics_extractor = AnsibleMetricsExtractor(path_to_repo='tmp/ansible.motd')
metrics_extractor.extract(failure_prone_files, product=True, process=True, delta=True)
metrics_extractor.to_csv('metrics.csv')

print('FIXING COMMITS:', miner.fixing_commits)
print('FAILURE-PRONE FILES:', failure_prone_files)
print('METRICS:', metrics_extractor.dataset.head())