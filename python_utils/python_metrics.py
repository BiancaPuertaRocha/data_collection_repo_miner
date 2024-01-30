
from typing import Any, Dict
from repominer.metrics.base import BaseMetricsExtractor

class PythonMetricsExtractor(BaseMetricsExtractor):

    def __init__(self, path_to_repo: str, clone_repo_to: str = None, at: str = 'release'):
        super().__init__(path_to_repo, clone_repo_to, at)
    
    def get_product_metrics(self, script: str) -> Dict[str, Any]:
        return super().get_product_metrics(script)

    def ignore_file(self, path_to_file: str, content: str = None):
        return not path_to_file.endswith('.py')