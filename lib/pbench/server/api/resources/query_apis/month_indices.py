from flask import jsonify
from logging import Logger
from typing import Any, AnyStr, Dict

from pbench.server import PbenchServerConfig
from pbench.server.api.resources.query_apis import ElasticBase, Schema
from pbench.server.database.models.template import Template


class MonthIndices(ElasticBase):
    """
    Get the range of dates in which datasets exist.
    """

    def __init__(self, config: PbenchServerConfig, logger: Logger):
        super().__init__(config, logger, Schema())
        template = Template.find("run")
        self.template_name = template.template_name + "."
        self.logger.info("month index key is {}", self.template_name)

    def assemble(self, json_data: Dict[AnyStr, Any]) -> Dict[AnyStr, Any]:
        """
        Report the month suffixes for run data indices.

        NOTE: No authorization or input parameters are required for this API,
        and there is no JSON query to form.
        """
        return {"path": "/_aliases", "kwargs": {}}

    def postprocess(self, es_json: Dict[AnyStr, Any]) -> Dict[AnyStr, Any]:
        months = []
        self.logger.debug("looking for {} in {}", self.template_name, es_json)
        for index in es_json.keys():
            if self.template_name in index:
                months.append(index.split(".")[-1])
        months.sort(reverse=True)
        self.logger.info("found months {!r}", months)
        # construct response object
        return jsonify(months)