import json

from ..compile_domain import wb_gql_op_plugin
from ..api import op
from .. import errors
from .. import weave_types as types
from . import wb_domain_types as wdt
from .wandb_domain_gql import (
    _make_alias,
    gql_prop_op,
    gql_direct_edge_op,
    gql_connection_op,
)

import typing
from . import wb_util
from urllib.parse import quote
from .. import artifact_fs
from .. import artifact_wandb


static_art_file_gql = """
            commitHash
            artifactSequence {
                id
                name
                defaultArtifactType {
                    id
                    name
                    project {
                        id
                        name
                        entity {
                            id
                            name
                        }
                    }
                }
            }
        """

# Section 1/6: Tag Getters
# None


def _safe_nested_pick(obj: typing.Optional[dict], path: list[str]) -> typing.Any:
    if len(path) == 0:
        return obj
    if not isinstance(obj, dict):
        return None
    return _safe_nested_pick(obj.get(path[0]), path[1:])


# Section 2/6: Root Ops
@op(
    name="root-artifactVersionGQLResolver",
    input_type={
        "gql_result": types.TypedDict({}),
        "entityName": types.String(),
        "projectName": types.String(),
        "artifactTypeName": types.String(),
        "artifactVersionName": types.String(),
    },
    output_type=types.optional(wdt.ArtifactVersionType),
)
def root_artifact_version_gql_resolver(
    gql_result, entityName, projectName, artifactTypeName, artifactVersionName
):
    project_alias = _make_alias(entityName, projectName, prefix="project")
    artifact_type_alias = _make_alias(artifactTypeName, prefix="artifactType")
    artifact_alias = _make_alias(artifactVersionName, prefix="artifact")

    # This nested property access is required because if an particular
    # GQL does not exist, then it returns None for that key. So, if
    # the user requests something that does not exist, then we want
    # to safely return None in such a case
    artifact_alias_data = _safe_nested_pick(
        gql_result, [project_alias, artifact_type_alias, artifact_alias]
    )
    if artifact_alias_data is not None:
        return wdt.ArtifactType.from_gql(artifact_alias_data)
    return None


def _root_artifact_version_plugin(inputs, inner):
    project_alias = _make_alias(
        inputs.raw["entityName"], inputs.raw["projectName"], prefix="project"
    )
    artifact_type_alias = _make_alias(
        inputs.raw["artifactTypeName"], prefix="artifactType"
    )
    artifact_alias = _make_alias(inputs.raw["artifactVersionName"], prefix="artifact")
    return f"""
        {project_alias}: project(entityName: {inputs['entityName']}, name:{inputs['projectName']}){{
            id
            {artifact_type_alias}: artifactType(name: {inputs['artifactTypeName']}){{
                id
                {artifact_alias}: artifact(name: {inputs['artifactVersionName']}){{
                    {wdt.ArtifactVersion.REQUIRED_FRAGMENT}
                    {inner}
                }}
            }}
        }}
    """


@op(
    name="root-artifactVersion",
    input_type={
        "entityName": types.String(),
        "projectName": types.String(),
        "artifactTypeName": types.String(),
        "artifactVersionName": types.String(),
    },
    output_type=wdt.ArtifactVersionType,
    plugins=wb_gql_op_plugin(
        _root_artifact_version_plugin,
        is_root=True,
        root_resolver=root_artifact_version_gql_resolver,
    ),
)
def root_artifact_version(
    entityName, projectName, artifactTypeName, artifactVersionName
):
    raise errors.WeaveGQLCompileError(
        "root-artifactVersion should not be executed directly. If you see this error, it is a bug in the Weave compiler."
    )


# Section 3/6: Attribute Getters
gql_prop_op("artifactVersion-id", wdt.ArtifactVersionType, "id", types.String())
gql_prop_op("artifactVersion-digest", wdt.ArtifactVersionType, "digest", types.String())
gql_prop_op(
    "artifactVersion-hash", wdt.ArtifactVersionType, "commitHash", types.String()
)
gql_prop_op("artifactVersion-size", wdt.ArtifactVersionType, "size", types.Int())
gql_prop_op(
    "artifactVersion-description", wdt.ArtifactVersionType, "description", types.Int()
)
gql_prop_op(
    "artifactVersion-createdAt", wdt.ArtifactVersionType, "createdAt", types.Timestamp()
)

gql_prop_op(
    "artifactVersion-versionId", wdt.ArtifactVersionType, "versionIndex", types.Number()
)

gql_prop_op(
    "artifactVersion-referenceCount",
    wdt.ArtifactVersionType,
    "usedCount",
    types.Number(),
)


@op(
    plugins=wb_gql_op_plugin(lambda inputs, inner: "metadata"),
)
def refine_metadata(
    artifactVersion: wdt.ArtifactVersion,
) -> types.Type:
    return wb_util.process_run_dict_type(
        json.loads(artifactVersion.gql["metadata"] or "{}")
    )


@op(
    name="artifactVersion-metadata",
    refine_output_type=refine_metadata,
    plugins=wb_gql_op_plugin(lambda inputs, inner: "metadata"),
)
def metadata(
    artifactVersion: wdt.ArtifactVersion,
) -> dict[str, typing.Any]:
    return wb_util.process_run_dict_obj(
        json.loads(artifactVersion.gql["metadata"] or "{}")
    )


# Section 4/6: Direct Relationship Ops
gql_direct_edge_op(
    "artifactVersion-aliases",
    wdt.ArtifactVersionType,
    "aliases",
    wdt.ArtifactAliasType,
    is_many=True,
)

gql_direct_edge_op(
    "artifactVersion-artifactType",
    wdt.ArtifactVersionType,
    "artifactType",
    wdt.ArtifactTypeType,
)

gql_direct_edge_op(
    "artifactVersion-artifactSequence",
    wdt.ArtifactVersionType,
    "artifactSequence",
    wdt.ArtifactCollectionType,
)


@op(
    name="artifactVersion-createdBy",
    plugins=wb_gql_op_plugin(
        lambda inputs, inner: f"""
        createdBy {{
            __typename
            ... on Run {{
                {wdt.Run.REQUIRED_FRAGMENT}
                {inner}
            }}
        }}
        """
    ),
)
def artifact_version_created_by(
    artifactVersion: wdt.ArtifactVersion,
) -> typing.Optional[wdt.Run]:
    if artifactVersion.gql["createdBy"]["__typename"] == "Run":
        return wdt.Run.from_gql(artifactVersion.gql["createdBy"])
    return None


@op(
    name="artifactVersion-createdByUser",
    plugins=wb_gql_op_plugin(
        lambda inputs, inner: f"""
        createdBy {{
            __typename
            ... on User {{
                {wdt.User.REQUIRED_FRAGMENT}
                {inner}
            }}
        }}
        """
    ),
)
def artifact_version_created_by_user(
    artifactVersion: wdt.ArtifactVersion,
) -> typing.Optional[wdt.User]:
    if artifactVersion.gql["createdBy"]["__typename"] == "User":
        return wdt.User.from_gql(artifactVersion.gql["createdBy"])
    return None


# Section 5/6: Connection Ops
gql_connection_op(
    "artifactVersion-artifactCollections",
    wdt.ArtifactVersionType,
    "artifactCollections",
    wdt.ArtifactCollectionType,
)

gql_connection_op(
    "artifactVersion-memberships",
    wdt.ArtifactVersionType,
    "artifactMemberships",
    wdt.ArtifactCollectionMembershipType,
)

gql_connection_op(
    "artifactVersion-usedBy",
    wdt.ArtifactVersionType,
    "usedBy",
    wdt.RunType,
)


# Section 6/6: Non Standard Business Logic Ops
@op(
    name="artifactVersion-name",
    plugins=wb_gql_op_plugin(
        lambda inputs, inner: """
            versionIndex
            artifactSequence {
                id
                name
            }
        """,
    ),
)
def op_artifact_version_name(
    artifact: wdt.ArtifactVersion,
) -> str:
    return f'{artifact.gql["artifactSequence"]["name"]}:v{artifact.gql["versionIndex"]}'


@op(
    name="artifactVersion-link",
    plugins=wb_gql_op_plugin(
        lambda inputs, inner: """
            versionIndex
            artifactSequence {
                id
                name
                defaultArtifactType {
                    id
                    name
                    project {
                        id
                        name
                        entity {
                            id
                            name
                        }
                    }
                }
            }
        """,
    ),
)
def artifact_version_link(
    artifactVersion: wdt.ArtifactVersion,
) -> wdt.Link:
    home_sequence_name = artifactVersion.gql["artifactSequence"]["name"]
    home_sequence_version_index = artifactVersion.gql["versionIndex"]
    type_name = artifactVersion.gql["artifactSequence"]["defaultArtifactType"]["name"]
    project_name = artifactVersion.gql["artifactSequence"]["defaultArtifactType"][
        "project"
    ]["name"]
    entity_name = artifactVersion.gql["artifactSequence"]["defaultArtifactType"][
        "project"
    ]["entity"]["name"]
    return wdt.Link(
        f"{home_sequence_name}:v{home_sequence_version_index}",
        f"/{entity_name}/{project_name}/artifacts/{quote(type_name)}/{quote(home_sequence_name)}/v{home_sequence_version_index}",
    )


# The following two ops: artifactVersion-isWeaveObject and artifactVersion-files
# need more work to get artifact version file metadata.


@op(
    name="artifactVersion-isWeaveObject",
    plugins=wb_gql_op_plugin(lambda inputs, inner: static_art_file_gql),
)
def artifact_version_is_weave_object(
    artifactVersion: wdt.ArtifactVersion,
) -> bool:
    art_local = _artifact_version_to_wb_artifact(artifactVersion)
    path = art_local._manifest_entry("obj.type.json")
    return path is not None


@op(name="artifactVersion-files")
def files(
    artifactVersion: wdt.ArtifactVersion,
) -> list[artifact_fs.FilesystemArtifactFile]:
    # TODO: What is the correct data model here? - def don't want to go download everything
    return []


def _get_history_metrics(
    artifactVersion: wdt.ArtifactVersion,
) -> dict[str, typing.Any]:
    from ..compile import enable_compile
    from weave.graph import OutputNode, ConstNode
    from . import wb_domain_types
    from .. import weave_internal

    created_by = artifactVersion.gql["createdBy"]
    if created_by["__typename"] != "Run":
        return {}

    run_name = created_by["name"]
    project_name = created_by["project"]["name"]
    entity_name = created_by["project"]["entity"]["name"]
    history_step = artifactVersion.gql["historyStep"]

    node = OutputNode(
        types.TypedDict({}),
        "run-historyAsOf",
        {
            "run": OutputNode(
                wb_domain_types.RunType,
                "project-run",
                {
                    "project": OutputNode(
                        wb_domain_types.ProjectType,
                        "root-project",
                        {
                            "entity_name": ConstNode(types.String(), entity_name),
                            "project_name": ConstNode(types.String(), project_name),
                        },
                    ),
                    "run_name": ConstNode(types.String(), run_name),
                },
            ),
            "asOfStep": ConstNode(types.Int(), history_step),
        },
    )

    with enable_compile():
        res = weave_internal.use(node)
    if isinstance(res, list):
        res = res[0]

    return res


# This op contains a bunch of custom logic, punting for now
@op(
    plugins=wb_gql_op_plugin(
        lambda inputs, inner: """
            historyStep
            createdBy {
                __typename
                ... on Run {
                    id
                    name
                    project {
                        id
                        name 
                        entity {
                            id
                            name
                        }
                    }
                }
            }
        """,
    ),
)
def refine_history_metrics(
    artifactVersion: wdt.ArtifactVersion,
) -> types.Type:
    return wb_util.process_run_dict_type(_get_history_metrics(artifactVersion))


@op(
    name="artifactVersion-historyMetrics",
    plugins=wb_gql_op_plugin(
        lambda inputs, inner: """
            historyStep
            createdBy {
                __typename
                ... on Run {
                    id
                    name
                    project {
                        id
                        name 
                        entity {
                            id
                            name
                        }
                    }
                }
            }
        """,
    ),
    refine_output_type=refine_history_metrics,
)
def history_metrics(
    artifactVersion: wdt.ArtifactVersion,
) -> dict[str, typing.Any]:
    return _get_history_metrics(artifactVersion)


# Special bridge functions to lower level local artifacts

# TODO: Move all this to helper functions off the artifactVersion object
def _artifact_version_to_wb_artifact(artifactVersion: wdt.ArtifactVersion):
    entity_name = artifactVersion.gql["artifactSequence"]["defaultArtifactType"][
        "project"
    ]["entity"]["name"]
    project_name = artifactVersion.gql["artifactSequence"]["defaultArtifactType"][
        "project"
    ]["name"]
    type_name = artifactVersion.gql["artifactSequence"]["defaultArtifactType"]["name"]
    home_sequence_name = artifactVersion.gql["artifactSequence"]["name"]
    commit_hash = artifactVersion.gql["commitHash"]
    return artifact_wandb.WandbArtifact(
        name=home_sequence_name,
        type=type_name,
        uri=artifact_wandb.WeaveWBArtifactURI(
            home_sequence_name, commit_hash, entity_name, project_name
        ),
    )


@op(
    name="artifactVersion-_file_refine_output_type",
    output_type=types.TypeType(),
    plugins=wb_gql_op_plugin(lambda inputs, inner: static_art_file_gql),
)
def _file_refine_output_type(artifactVersion: wdt.ArtifactVersion, path: str):
    art_local = _artifact_version_to_wb_artifact(artifactVersion)
    return types.TypeRegistry.type_of(art_local.path_info(path))


# Warning: the return type of this is incorrect! Weave0 treats
# type 'file' (FilesystemArtifactFile) as both dir and file.
# We have a refiner to do the correct thing, but the return
# type is set to `File` so that the first non-refine compile
# path will still work.
@op(
    name="artifactVersion-file",
    refine_output_type=_file_refine_output_type,
    plugins=wb_gql_op_plugin(lambda inputs, inner: static_art_file_gql),
)
def file_(
    artifactVersion: wdt.ArtifactVersion, path: str
) -> typing.Union[
    None, artifact_fs.FilesystemArtifactFile  # , artifact_fs.FilesystemArtifactDir
]:
    art_local = _artifact_version_to_wb_artifact(artifactVersion)
    return art_local.path_info(path)  # type: ignore
