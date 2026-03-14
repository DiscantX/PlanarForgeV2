from core.resource import Resource
import yaml


cre = Resource(
    resref="bandit",
    restype="CRE",
    data={
        "name": 10423,
        "hp": 32,
        "script_override": "bandit_ai"
    }
)