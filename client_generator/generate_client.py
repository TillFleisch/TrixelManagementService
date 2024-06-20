"""Client module generator for the Trixel Management Server API."""

import json
import shutil
from pathlib import Path

import toml
from fastapi.openapi.utils import get_openapi
from openapi_python_client import MetaType
from openapi_python_client.cli import generate

from trixelmanagementserver import app

if __name__ == "__main__":

    # Generate openapi description
    # source: https://github.com/tiangolo/fastapi/issues/1173
    with open(Path("openapi.json"), "w") as file:
        json.dump(
            get_openapi(
                title=app.title,
                version=app.version,
                openapi_version=app.openapi_version,
                description=app.description,
                routes=app.routes,
            ),
            file,
        )

    # Generate client module
    generate(
        url=None,
        path=Path("./openapi.json"),
        custom_template_path=None,
        meta=MetaType.PDM,
        file_encoding="utf-8",
        config_path=Path("./openapi-generator-config.yaml"),
        overwrite=True,
        output_path=None,
    )

    # Complete resources from parent project
    shutil.copyfile(Path("../LICENSE"), Path("trixelmanagementclient/LICENSE"))

    child_toml = Path("trixelmanagementclient/pyproject.toml")
    child = toml.load(child_toml)
    parent = toml.load(Path("../pyproject.toml"))

    entries = [
        ("project", "version"),
        ("project", "authors"),
        ("project", "license"),
        ("project", "urls"),
    ]

    for category, key in entries:
        child[category][key] = parent[category][key]

    child["project"]["description"] = "A client module for accessing the Trixel Management Service (API)"

    file = open(child_toml, "w")
    toml.dump(child, file)
    file.close()

    # Add prefix to generated readme
    with open(Path("trixelmanagementclient/README.md"), "r+") as target:
        content = target.read()
        target.seek(0, 0)
        with open(Path("readme_prefix.md")) as source:
            target.write(source.read() + content)
